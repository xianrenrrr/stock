# Plan H — Signal DAG: incremental context graph for predictions

Status: DESIGN (2026-06-09). Not implemented. Review before coding.

## 1. Problem

`predict_ticker` rebuilds its full prompt context from scratch on every call:
20 news features, 10 price bars, vector retrieval over past cases, knowledge-base
direct + semantic retrieval (up to 9 × 700-char excerpts), macro block, rules.
Meanwhile high-value signals we ALREADY collect never reach the prediction at
all: options flow (UOA + put/call ratios), price/volume anomalies, intraday
alerts, tracked catalyst events, insider filings. Naively appending those to the
prompt makes it balloon (cost, noise, lost-in-the-middle) and recomputes
everything per ticker per run.

Goal: feed the model MORE signal with FEWER tokens, recomputing each piece only
when its inputs actually changed.

## 2. Core idea — a memoized context DAG

Every prompt section becomes a **node**: a compact text block with declared
inputs, a deterministic or cheap-LLM transform, a token budget, and an
**input fingerprint**. At predict time we walk the node list (lazy pull —
no new scheduler/daemon):

```
fingerprint = cheap probe of inputs (e.g. MAX(id) of source rows + config/prompt version)
if fingerprint == stored fingerprint -> reuse stored block (free)
else                                 -> recompute, store block + fingerprint
```

So a macro block computed at 01:55 is reused verbatim by all ~20 ticker
predictions at 02:15; a knowledge card is re-distilled only when a new research
report mentioning that ticker lands; the tape block recomputes only after a new
price bar. Deterministic nodes cost $0; LLM nodes amortize to near-$0 because
they fire on input change, not per prediction.

```
L0 collectors (exist)        L1 distilled nodes                L2 assembly        L3
news/features ────────────► news_digest (det) ──┐
prices ───────┬───────────► tape (det) ─────────┤
price_anomalies/alerts ────┘                    │
option_ratio/anomalies ───► flow (det) ─────────┤
insider_filings ──────────► insider (det) ──────┤
tracked_events+earnings ──► events (det) ───────┼──► prediction_context ─► LLM ─► guardrails
research_reports ─────────► knowledge_card (LLM)│      (ordered, budgeted,        + calibration
outcomes/theses ──────────► lessons (det) ──────┤       manifest logged)
macro digest ─────────────► macro (exists) ─────┤
index/ETF/VIX bars ───────► market_internals(det)
peers in prices ──────────► sector_breadth (det)┘
gov_trades (NEW) ─────────► gov (det) ──────────┘
```

## 3. Storage

```sql
CREATE TABLE IF NOT EXISTS context_nodes (
  node TEXT NOT NULL,            -- 'tape', 'flow', 'knowledge_card', ...
  scope TEXT NOT NULL,           -- ticker, or '*' for shared nodes
  content TEXT NOT NULL,         -- the rendered prompt block
  content_hash TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  token_estimate INTEGER,
  compute_cost_usd REAL DEFAULT 0,
  computed_at TEXT NOT NULL,
  PRIMARY KEY (node, scope)
);
```

New module `src/stock/context_graph.py`: node registry (name, scope, budget,
fingerprint fn, render fn), `build_context(ticker, conn) -> dict[str, str]`,
plus `stock context <TICKER>` CLI to inspect any node's current block and
freshness. Tests with `:memory:` DBs per node.

## 4. Node catalog

### Shared (scope `*`)

| Node | Transform | Inputs / fingerprint | Budget |
|---|---|---|---:|
| `macro` | exists (LLM 2×/day job) — wrap as node | latest research_reports(kind='macro') id | 500 tok |
| `market_internals` | deterministic | NEW index/ETF bars: SPY QQQ SMH SOXX XLK ^VIX ^TNX — 1d/5d returns, VIX level+Δ, 10Y Δ | 80 tok |
| `sector_breadth` | deterministic — promote the existing AI-infra guardrail math into a visible block (positive share, median return, leaders) per sector bucket | prices of peer set, latest ts | 60 tok |
| `policy_digest` | cheap LLM daily — tariffs/export controls/federal contracts/political-trading flags relevant to tracked sectors (the Trump/DELL class of signal, systematized) | NEW daily Tavily policy query → research_reports(kind='policy') | 150 tok |

### Per ticker

| Node | Transform | Inputs / fingerprint | Budget |
|---|---|---|---:|
| `news_digest` | deterministic (existing formatter + cluster dedup + age decay; drop sub-relevance items) | MAX(features.id) for ticker | 400 tok |
| `tape` | deterministic — 1/5/20d returns, volume vs 20d avg, % from 52w high, overnight gap (live quote), anomaly + intraday-alert flags | MAX(prices.ts), MAX(price_anomalies.id), latest alert id | 120 tok |
| `flow` | deterministic — latest put/call ratio + its 20d percentile, UOA hits last 5d with direction skew | MAX ids of option_ratio_snapshots / option_anomalies | 80 tok |
| `insider` | deterministic — net buy/sell count+$ 30/90d, cluster-buy flag, largest txn, % from 52w high at filing | MAX(insider_filings.id) for ticker | 60 tok |
| `events` | deterministic — upcoming tracked_events + next earnings date (days-until, est) | MAX(tracked_events.id), earnings calendar row | 80 tok |
| `gov` | deterministic — congressional/gov trades naming ticker last 90d, with disclosure-lag caveat line | NEW gov_trades MAX(id) | 60 tok |
| `knowledge_card` | **LLM-distilled living card** replacing raw 6×700-char excerpts: 1-para thesis, key drivers, key risks, last-3 research pointers (kind+date). Refreshed ONLY when new KNOWLEDGE_KINDS research mentioning the ticker lands | MAX(research_reports.id) matching ticker (direct or semantic-cached) | 300 tok |
| `lessons` | deterministic — per-ticker scoreboard (hit rate, n, streak) + last 3 misses with one-line thesis-verdict reasons + top-3 retrieved cases (shrunk from today's full block) | MAX(outcomes.scored_at) for ticker, retrieval hash | 200 tok |

### Coverage matrix — every collected input, accounted for

All 21 information types the system collects today, mapped to how they reach
(or deliberately don't reach) the prediction:

| # | Collected input | Path into prediction |
|---|---|---|
| 1 | Ticker news (Yahoo/MarketWatch/CNBC/EDGAR 8-K) | `news_digest` |
| 2 | LLM news features (sentiment/catalyst/novelty/…) | `news_digest` |
| 3 | Daily OHLCV prices | `tape` (+ `sector_breadth`, `market_internals`) |
| 4 | US macro digest | `macro` |
| 5 | Past prediction→outcome cases | `lessons` |
| 6 | Self-authored rules | system prompt (unchanged) |
| 7 | Deep research (deep_dive/tech_dive/deep_qa/reply/health_check/discovery_thesis/earnings_review/dd_checklist/daily/macro) | `knowledge_card` |
| 8 | Raw Tavily `web_research` rows | **indirect only** — vetted content reaches `knowledge_card` via daily notes/dives; raw rows stay out (unvetted, noisy, injection surface) |
| 9 | SEC Form 4 insider filings | `insider` (newly fed) |
| 10 | Unusual options activity | `flow` (newly fed) |
| 11 | Put/call ratio snapshots | `flow` (newly fed) |
| 12 | Price/volume anomalies | `tape` (newly fed) |
| 13 | Tracked catalyst events | `events` (newly fed) |
| 14 | Intraday crash/spike alerts | `tape` flags (newly fed) |
| 15 | Holdings / broker positions | **excluded by design** — what we own must not bias the forecast; stays in risk/warning layer |
| 16 | AI commercial-loop health panel | `sector_breadth` gains an AI-cycle risk flag line (newly fed) |
| 17 | Small-cap candidate scores | **watchlist-side** — decides WHICH tickers get predicted, not prompt content |
| 18 | Forward-discovery candidates | **watchlist-side** — same |
| 19 | Entry-zone signals | superseded by `tape` + `lessons` (open question 2) |
| 20 | Thesis verdicts | `lessons` (miss reasons) |
| 21 | Boss conversations/feedback | **excluded by design** — drives watchlist adds + prompt rewrites, not market data; keeps instructions out of the data path |

Net: 16 of 21 feed the prompt (8 of them newly), 5 are excluded with stated
reasons rather than by accident.

Assembly order is fixed, most-stable first (prompt-cache friendly):
`rules → macro → market_internals → sector_breadth → policy_digest →
knowledge_card → lessons → gov → insider → events → flow → tape → news_digest
→ instruction`. Target total ≈ 2.3–2.8k tokens (vs ~3–5k today) with roughly
double the signal coverage.

## 5. Close the loop (this is the point)

Each prediction stores a **context manifest** in `feature_context_json`:

```json
"context_manifest": {"flow": {"hash": "ab12", "present": true, "tokens": 74}, ...}
```

Grading (`_format_error_patterns`) gains a per-block ablation table: hit rate
and Brier for predictions WITH vs WITHOUT each block populated (flow had UOA
vs empty, knowledge_card fresh vs stale, etc.) — same pattern as the existing
`knowledge_item_count` instrumentation, generalized. The auto-improve path can
then propose budget/kind changes backed by measured deltas, and self-review
flags chronically stale nodes. Blocks that measurably don't help get cut; the
DAG makes adding/removing a block a one-line registry change.

## 6. Missing information we should regularly capture

All free unless noted. Each becomes one collector job + one node.

| Pri | Source | What / why (1-day horizon) | Cadence | Table |
|---|---|---|---|---|
| P0 | yfinance earnings calendar (`get_earnings_dates`) | next earnings date + EPS est — the single most important known 1-day catalyst; today the model only sees it if a news item mentions it | daily | auto-rows in `tracked_events` |
| P0 | yfinance `fast_info` live quote at predict time | overnight gap / current price vs last daily bar — the 14:15 UTC run is ~45 min after open and currently blind to it (deep dives already do this; predictions don't) | at predict | inline in `tape` |
| P0 | yfinance bars for SPY QQQ SMH SOXX XLK ^VIX ^TNX | market internals — quantitative regime numbers grounding the LLM macro text | with daily price job | `prices` |
| P1 | FINRA short interest (bi-monthly file) + Reg SHO daily short volume | squeeze/pressure context | daily file pull | `short_interest` |
| P1 | yfinance upgrades/downgrades | analyst revisions — well-documented short-horizon drift | daily | `analyst_actions` |
| P1 | Senate/House STOCK Act disclosures (Senate eFD / House Clerk PTR scrape, community JSON mirrors e.g. senate/house-stockwatcher; QuiverQuant API if paid later) | **the boss's government-trades ask, systematized.** Disclosure lag is up to 45 days → treat as slow conviction + political-risk flag (the DELL/Trump case), never fast alpha | daily | `gov_trades` |
| P2 | Daily Tavily policy sweep (tariffs, export controls, federal contracts, executive orders touching tracked sectors) | policy digest node — AI supply chain is policy-driven; today policy news arrives only if it names a ticker | daily | `research_reports(kind='policy')` |
| P2 | StockTwits/Reddit sentiment | skip for now — noisy, leakage-prone per literature; revisit if grading shows a sentiment gap | — | — |

## 7. Phases

| Phase | Deliverable | Notes |
|---|---|---|
| H0 | P0 collectors (earnings calendar, live quote, market internals) wired straight into the existing prompt | immediate signal win, no DAG dependency |
| H1 | `context_nodes` table + registry + deterministic nodes (tape/flow/insider/events/sector_breadth/market_internals) + prompt restructure + manifest instrumentation | the DAG itself; biggest token/coverage shift |
| H2 | `knowledge_card` + `lessons` distillation (event-driven cheap LLM) | replaces raw excerpt injection; big token cut |
| H3 | P1/P2 collectors (short interest, analyst actions, gov_trades, policy_digest) as new nodes | each lands as one registry entry |
| H4 | Grading per-block ablation + auto-tune of budgets/kinds | closes the loop |

Each phase: focused tests, ruff, `create_scheduler()` verification if jobs
change, and a `docs/runtime_source_of_truth.md` update.

## 8. Cost

Deterministic nodes: $0. `knowledge_card`/`policy_digest`: few calls/day on
codex_cli (≈$0 metered). Prediction prompt tokens flat-to-lower despite more
signal; shared nodes computed once per cycle instead of per ticker. Honors the
existing daily cost ceiling via the normal client helpers.

## 9. Open questions

1. Gov-trades source: community mirrors are free but unofficial; scraping eFD
   directly is sturdier but more code. Pick one for H3.
2. Should `alert` and `entry_signals` kinds join KNOWLEDGE_KINDS now (one-line
   change), or wait for the `tape`/`lessons` nodes that supersede them?
3. Per-block token budgets above are first guesses — let the H4 ablation tune them.
4. Keep vector retrieval of past cases inside `lessons`, or retire raw case
   text entirely once per-ticker scoreboard + rules carry the same information?

Not financial advice.
