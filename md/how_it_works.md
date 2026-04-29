# How STOCK works — plain-English walkthrough

This doc explains what happens from the moment a news headline is published to the moment a suggestion lands in your WeChat. It is the friendly companion to `md/complete_workflow.md` (which is the spec) and `design.md` (which is the architecture).

If you only read one section, read section 5 — "What happens on day 1, day 10, day 20."

---

## 1. The big picture in one paragraph

A scheduler wakes up the laptop every few minutes. It pulls fresh news for every ticker on the watchlist, grabs the latest prices, asks a small cheap LLM (MiniMax) "given this news and these prices, will the stock go up or down in the next N days?", and writes the answer to a SQLite file on disk. A few days later, when the real price is known, a separate job scores the prediction: was it right? by how much? That score flows into four learning layers — memory, rules, a bandit, and a calibration regressor — so the next prediction is slightly better. Every so often (1–2x/week) Claude Opus reads the recent log and rewrites the rules document. You can ask for the current state at any time from WeChat through the OpenClaw gateway; the gateway runs 24/7 and never logs out.

---

## 2. Where the news comes from

Module: `src/stock/ingest/`

Two sources, both free, both polled on a timer:

- **RSS feeds** (`ingest/news_rss.py`) — Yahoo Finance per-ticker feeds, MarketWatch top stories, CNBC, SEC EDGAR filings. URLs live in `data/feeds.yaml`. New items are keyed by a SHA256 of the URL so duplicates are silently dropped.
- **Yahoo Finance per-ticker news** (`ingest/news_yahoo.py`) — uses the `yfinance.Ticker(sym).news` API for headlines the RSS doesn't cover (e.g. analyst notes, earnings notes).

Everything lands in the `news` SQLite table with columns `(id, ticker, url_hash, title, body, source, published_at, fetched_at)`. We keep the full body when the feed provides one; otherwise just the title.

## 3. Where the stock data comes from

Module: `src/stock/ingest/prices.py`

Daily OHLCV (open, high, low, close, volume) via `yfinance.download()`. Stored in the `prices` table keyed by `(ticker, ts)`. We only pull the bars we don't already have, so repeated calls are cheap.

Intraday prices are not used — the model is deliberately short-horizon daily, not minute-level.

## 4. How we keep track of everything

One SQLite file: `data/stock.db`. Tables:

| Table | What it holds |
|---|---|
| `watchlist` | Tickers currently being tracked. Add/remove via WeChat. |
| `news` | Every headline ever fetched, deduped by URL hash. |
| `prices` | Daily OHLCV bars. |
| `features` | Derived per-(ticker, day) signals: recent return, volatility, news count, sentiment score. |
| `predictions` | Every LLM call's output: direction, prob_up, expected_return_bps, confidence, rationale, key_factors, due_at. |
| `outcomes` | What actually happened by `due_at`: direction_hit, real_return_bps, brier_score. |
| `memory` | Embedded snippets of past (context, prediction, outcome) triples for similarity retrieval. |
| `rules` | The self-authored rules document, versioned. Each weekly reflection bumps the version. |
| `bandit_state` | Per-strategy-arm pull counts and reward sums (for Thompson sampling). |
| `calibration` | The fitted `prob_up → prob_up_calibrated` regressor coefficients. |
| `llm_calls` | Every LLM call with model, input tokens, output tokens, cost_usd, duration_ms. |
| `daily_spend` | Running total per UTC day for the cost ceiling. |

Nothing is ever deleted. If the disk fills up we rotate, but by then we have months of data.

## 5. What happens on day 1, day 10, day 20

This is the learning curve.

### Day 1
You add `AAPL` to the watchlist from WeChat.

- The next scheduler tick (within a few minutes) ingests AAPL news + prices.
- `predict.py` builds a prompt: system rules + retrieved similar past cases (empty at day 1) + current features + recent 30-day price history.
- MiniMax returns `{direction: "up", prob_up: 0.58, confidence: 0.4, rationale: "...", key_factors: [...]}`.
- We write it to `predictions` with `due_at = now + 5 trading days`.
- The reply back to WeChat includes the direction, a calibrated probability (at day 1 this is just the raw probability, since calibration has no data yet), and the one-paragraph rationale. Always suffixed with `Not financial advice.`

No real learning yet — just a single bet on the table.

### Day 6 (first prediction comes due)
- `score.py` runs after close, compares the real 5-day return to what was predicted, writes to `outcomes`.
- The (context, prediction, outcome) triple is embedded by `sentence-transformers` and appended to `memory` (stored via `sqlite-vec` for fast similarity search).
- `bandit.py` updates the arm used for that prediction — did it win or lose? Reward gets added.

### Day 10
By now there are ~30–50 scored predictions across the watchlist.

- **Memory retrieval is live**: when predicting AAPL on day 10, the prompt now includes 3–5 of the most similar past cases with their real outcomes. The LLM sees "when I said this kind of thing in the past, here's what actually happened."
- **Bandit is starting to prefer arms that won**: if "lean-on-earnings" arm won 7/10 times and "lean-on-analyst-upgrade" won 3/10, the bandit will sample the first more often.
- **Calibration regressor kicks in at 50 scored predictions**: if the model's stated `prob_up=0.7` historically resolves to 55% wins, the output shows `prob_up=0.70, prob_up_calibrated=0.55`. The calibrated number is what you actually trust.

### Day 20
Two weekly reflections have run (Sunday 00:00 UTC).

- **Rules document has been rewritten twice** by Claude Opus (`learn.py`). Opus reads the last 7 days of (prediction, outcome) pairs, asks "what patterns are winning, what's losing, what should the rules say?", and writes a new `rules.md` snapshot into the `rules` table. Version 3 lives there now.
- The next prediction's prompt uses the new rules → the model is (hopefully) smarter than day 1.
- `/stock report days=20` will show real numbers now: hit rate, mean Brier score, best call, worst call, total return in basis points, total spend in USD.

By day 20 you can meaningfully ask "is this thing working?" Before day 20, sample size is too small to judge.

## 6. How learning works (4 layers, none of them neural RL)

We cannot fine-tune Claude or MiniMax — they are closed-weight. "Learning" happens outside the model:

1. **Memory** — similar past cases get injected into the prompt. Prompt-level few-shot that grows over time.
2. **Rules** — a `rules.md` document the system rewrites weekly. Next prediction reads the updated rules.
3. **Bandit** — Thompson sampling over strategy arms (e.g. "weight earnings news heavily" vs "weight analyst revisions heavily"). Winning arms get picked more.
4. **Calibration** — a tiny sklearn isotonic regressor that maps stated probability to historical actual probability. Fixes overconfidence.

All four are computed locally from the SQLite log. No gradient descent on the LLM itself.

## 7. How suggestions reach WeChat

OpenClaw Gateway (already installed on this laptop) is the bridge.

```
WeChat (you) ──► OpenClaw Gateway (local, port 8080) ──► main agent
                                                            │
                                                            │ calls stock skill
                                                            ▼
                                      STOCK FastAPI (127.0.0.1:18790)
                                                            │
                                                            ▼
                                                       SQLite + LLM
```

- OpenClaw is logged into your WeChat account and **never logs out** as long as the laptop stays on and the gateway process runs.
- Your message ("how's AAPL looking?") hits the OpenClaw main agent.
- The main agent sees the `stock` skill is available (defined in `openclaw_skill/stock.skill.md`) and decides whether to call `stock.predict(AAPL)`, `stock.on_demand(AAPL)`, `stock.report(days=7)`, `stock.rules()`, `stock.watchlist(add, AAPL)`, or `stock.calibration()`.
- The skill makes an HTTP call to `127.0.0.1:18790` with the `STOCK_API_TOKEN` bearer. Loopback only — nothing is exposed to the internet.
- The FastAPI app reads from SQLite (or triggers a fresh prediction for `on_demand`), returns JSON, the skill formats it, the main agent sends it back to you on WeChat.

Every reply that mentions a direction, probability, or rule ends with `Not financial advice.` — enforced in the skill.

## 8. What runs on a timer

`src/stock/orchestrator.py` defines four jobs via APScheduler:

| Job | Cadence | What it does |
|---|---|---|
| `_job_ingest_and_extract` | every 15 min, market hours | pull news + prices, extract features |
| `_job_run_predictions` | every hour, market hours | predict for each watchlist ticker with new features |
| `_job_score_daily` | daily 23:00 UTC | score predictions whose `due_at` passed |
| `_job_reflect_weekly` | Sunday 00:00 UTC | Claude Opus rewrites rules.md |

Single-process, single-node. If the laptop reboots, the scheduler restarts and catches up on whatever it missed.

## 9. Cost & kill switch

- MiniMax: ~$1/month in typical use.
- Claude Opus weekly reflection: ~$2/month (API, separate from the $100 Max plan).
- Hard daily cap: `DAILY_COST_CEILING_USD=0.50` in `.env`. Once hit, every LLM call returns `503 cost_ceiling_reached` and the skill tells you "budget exhausted, resumes at UTC midnight."
- Worst-case monthly: **~$15**, even if something goes wrong, because the daily cap × 30 ≤ $15.

## 10. What you need to keep running

Three processes on the laptop:

1. **OpenClaw Gateway** — the WeChat bridge. Already running.
2. **STOCK orchestrator** — `python -m stock orchestrator` (the scheduler). Run via `scripts/run_orchestrator.ps1` or a scheduled task.
3. **STOCK FastAPI** — `python -m stock api` (port 18790). Run via `scripts/run_api.ps1`.

If the laptop reboots, both STOCK processes need to start on boot. `scripts/` has the Windows startup helpers.

No cloud, no database server, no external ingress. Everything is loopback.

---

**Not financial advice.**
