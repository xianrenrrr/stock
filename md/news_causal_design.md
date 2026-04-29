# News → price: the causal-chain design

How we make the link between a news story and a stock move rigorous, measurable, and self-correcting.

This is a design doc — the current system (F00–F08) ships a first-cut of this loop, but does not model the chain at the individual-news-item level and does not evaluate outcomes beyond close-to-close returns. This doc specifies what to build next (F09–F11) so we can answer:

> "Given this specific headline, what is our predicted impact in basis points, with what half-life, and did it actually play out after controlling for the broader market?"

---

## 1. What the current pipeline does (and doesn't do)

### Does

1. `features.py` extracts **categorical** per-news features: `sentiment`, `novelty`, `catalyst_type`, `time_sensitivity`, `summary`. No numbers.
2. `predict.py` aggregates the last 20 feature rows + 10 price bars + retrieved memory + rules into one LLM call that returns **ticker-level** `{direction, prob_up, expected_return_bps, confidence, rationale}`.
3. `score.py` computes **raw close-to-close return** at `due_at`, direction hit (0/1), Brier score. Writes to `outcomes`.
4. Learning layers: memory retrieval, weekly rules rewrite, bandit over strategy arms, calibration on `prob_up` → `prob_up_calibrated`.

### Doesn't

1. **No per-news-item quantitative impact**. We can't say "the earnings beat is worth +80 bps, the analyst downgrade is worth −40 bps, net +40 bps" — we collapse all news into one ticker-level verdict.
2. **No market adjustment**. If SPY is down 3% and AAPL is down 2%, our current scorer says "prediction of 'up' was wrong" even though AAPL *outperformed* its market. Real alpha comes from residual, not raw return.
3. **No volume signal** in prediction input or in outcome evaluation. Volume spikes are the single best confirmation that news was material; we ignore them on both ends.
4. **No per-news attribution**. When AAPL moves after 5 news items hit, we can't say which item "earned its keep" in our impact estimate. So our calibration feedback is stuck at the ticker level.
5. **No time-of-day routing**. Pre-market news, intraday news, and after-hours news behave very differently. We treat them identically.
6. **No surprise-vs-expected modeling**. Stock reaction depends on the delta from consensus, not the raw report. We ask the LLM to figure this out implicitly.

These gaps are why hit rate probably plateaus around 52–54% (slight-edge-over-random) even with a good LLM. The fix is to turn the ticker-level prediction into an **explicit additive chain of per-news impacts with market-adjusted outcome attribution**.

---

## 2. The chain we want to build

```
                                                   ┌─────────────────────┐
                                                   │ baseline model      │
                                                   │ (SPY × β + α)       │
                                                   └─────────┬───────────┘
                                                             │
                                                             ▼
news_i ──► per-news impact LLM ──► {Δbps_i, half_life_i,     + residual_ticker
                                     confidence_i,               │
                                     category_i,                 │
                                     direction_i}                ▼
                                            │                attribution:
                                            ▼                 residual → each news_i
                                      aggregate daily
                                            │
                                            ▼
                                      ticker prediction
                                      = Σ Δbps_i × time_decay_i
                                            │
                                            ▼
                                      confirm next day:
                                         • price: AR_t = R_t − β·R_mt
                                         • volume: log(V_t / V̄_20d)
                                         • range: (H−L)/C_{t−1}
```

Everything in that diagram is a place where we write a number, compare to a realization, and calibrate.

### 2.1. Per-news impact prediction (new — this is the core missing piece)

Every news item, the moment it's ingested, runs through a **second** LLM call (not the current `features.extract_single`) that returns a **quantitative** structured prediction:

```json
{
  "category": "earnings_surprise",
  "direction": "up",
  "magnitude_bps": 120,
  "half_life_hours": 36,
  "confidence": 0.7,
  "surprise_score": 0.8,
  "novelty_score": 0.9,
  "expected_volume_multiplier": 2.5,
  "horizon_coverage": "1d",
  "key_quote": "Q3 EPS of $2.15 vs consensus $1.92, raises FY guidance",
  "caveats": ["guidance could be walked back on call", "macro headwinds cited"]
}
```

Why each field matters:

| Field | Why |
|---|---|
| `magnitude_bps` | The quantitative claim we'll score against the post-news abnormal return. |
| `half_life_hours` | Separates a 1-day trading catalyst from a multi-week structural change. Enables time-decayed aggregation. |
| `confidence` | Weights this item's contribution in the aggregation and shrinks our point estimate. |
| `surprise_score` | Expected-vs-consensus delta. A beat of a beat-and-raise is not news; an in-line print from a beat-and-raise company is a negative surprise. |
| `novelty_score` | Is this a fresh story or a rehash? If 4 outlets republished the same AP story, only the first is material. |
| `expected_volume_multiplier` | We cross-check against realized volume — a "big" story that draws no volume is a false positive. |
| `category` | Calibration is per-category. Earnings calibrate differently from analyst notes. |

The prompt is seeded with the ticker, the news text, and — crucially — **recent context** (last 5 news items for same ticker, current-quarter consensus if available, 20-day price history, sector ETF return today). The LLM is asked to reason about **the marginal informational content given what's already known**, not the headline in a vacuum.

Cost: MiniMax at 500-token prompt + 200-token response ≈ $0.0004 per news item. At 30 news/day, ~$0.012/day added. Well inside the $0.50 ceiling.

### 2.2. Daily aggregation

Once every scheduler tick, for each watchlist ticker, we combine all live news-impact estimates into a single ticker-level forecast:

```
predicted_AR_bps(t, horizon) = Σ_i impact_bps_i × decay(age_i, half_life_i) × confidence_i
                              + prior(ticker, macro_regime)
```

Where:
- `decay(age, hl) = 2^(-age / hl)` — exponential decay from each news item's half-life.
- `prior(...)` — a small learned constant per ticker × regime capturing baseline drift (momentum, earnings cycle position).
- Aggregation is capped to ±300 bps per day to avoid any single item blowing up the estimate.

**This is the explicit, auditable number**: for every prediction, we can point at a list of news items with their individual contributions summing to the forecast. That makes the system legible both to us and to the LLM on its next pass.

### 2.3. Outcome evaluation, done properly

`score.py` currently computes `actual_return = (exit_close − entry_close) / entry_close`. We replace that with three signals:

**Price signal — abnormal return (AR):**
```
expected_return_i = α_i + β_i × R_market
AR_i = R_i − expected_return_i
CAR_i(t1, t2) = Σ AR_i(t) over event window
```
We estimate β on a rolling 120-day window against SPY. AR isolates the idiosyncratic move — the thing news could have caused.

**Volume signal — abnormal volume:**
```
AV = log(V_t / median(V_{t-20..t-1}))
```
Above 0.5 means volume was >1.6× normal — a material-news footprint. Below −0.3 means the "news" was ignored.

**Range signal — realized volatility:**
```
RR = (H_t − L_t) / C_{t-1}
vs 20d median
```
Picks up cases where the open/close looked flat but there was intraday violence (knee-jerk reversed).

**Composite outcome row:**
```python
outcomes_v2 {
  prediction_id, entry_ts, exit_ts,
  raw_return_bps,
  abnormal_return_bps,       # AR — the signal we now score against
  abnormal_volume_z,         # AV
  range_ratio,               # RR
  market_return_bps,         # R_market for audit
  beta_used,                 # β used for expected return
  direction_hit_raw,         # legacy, kept for backward compat
  direction_hit_abnormal,    # new primary metric
  brier_raw,                 # legacy
  brier_abnormal,            # new
  surprise_confirmed,        # did realized volume confirm predicted materiality?
  scored_at
}
```

The primary hit-rate metric becomes `direction_hit_abnormal`: did we predict the right direction of the **idiosyncratic** move? This is what alpha actually means.

### 2.4. Per-news attribution

After the ticker outcome is scored, we push the realized abnormal return back to each news item that contributed:

```
attributed_i = AR_realized × (pred_impact_i × confidence_i × decay_i) / Σ(pred_impact_j × confidence_j × decay_j)
residual_i = attributed_i − pred_impact_i
```

That `residual_i` is the **per-news-item error signal**. We write it to a new `news_impact_outcomes` table:

```sql
CREATE TABLE news_impact_outcomes (
  news_id INTEGER,
  prediction_id INTEGER,
  predicted_bps REAL,
  attributed_bps REAL,
  residual_bps REAL,
  category TEXT,
  half_life_hours REAL,
  created_at TEXT,
  PRIMARY KEY (news_id, prediction_id)
);
```

With this, we can compute:
- **Per-category MAE**: was our earnings-surprise estimator off by 50 bps on average? Analyst notes off by 20? Use this to add per-category bias corrections.
- **Per-LLM-confidence calibration**: when the news LLM says `confidence=0.7`, do those items really hit within ±X% of predicted? If confidence is systematically overstated, shrink it.
- **Half-life audit**: if we said earnings decay with 36h half-life but realized decay shows 72h, update the half-life prior.

The weekly Opus reflection reads this table and rewrites `rules.md` with pattern-level findings ("our system overestimates rumor-M&A impact by 60 bps on average; cut those estimates by half until confirmed").

---

## 3. New schema additions

```sql
-- News-level quantitative impact predictions (one row per news item)
CREATE TABLE news_impact (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  news_id INTEGER NOT NULL UNIQUE,
  ticker TEXT NOT NULL,
  category TEXT NOT NULL,
  direction TEXT NOT NULL,
  magnitude_bps REAL NOT NULL,
  half_life_hours REAL NOT NULL,
  confidence REAL NOT NULL,
  surprise_score REAL NOT NULL,
  novelty_score REAL NOT NULL,
  expected_volume_mult REAL NOT NULL,
  horizon_coverage TEXT NOT NULL,
  key_quote TEXT,
  caveats_json TEXT,
  model TEXT NOT NULL,
  cost_usd REAL NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (news_id) REFERENCES news(id)
);

-- Per-news attribution after outcome is known
CREATE TABLE news_impact_outcomes (
  news_id INTEGER NOT NULL,
  prediction_id INTEGER NOT NULL,
  predicted_bps REAL NOT NULL,
  attributed_bps REAL NOT NULL,
  residual_bps REAL NOT NULL,
  category TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (news_id, prediction_id)
);

-- Rolling beta estimates per ticker (updated nightly)
CREATE TABLE ticker_beta (
  ticker TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  beta REAL NOT NULL,
  alpha REAL NOT NULL,
  r_squared REAL NOT NULL,
  n_samples INTEGER NOT NULL,
  PRIMARY KEY (ticker, as_of_date)
);

-- Abnormal outcome fields (extend, don't replace, existing outcomes)
ALTER TABLE outcomes ADD COLUMN abnormal_return_bps REAL;
ALTER TABLE outcomes ADD COLUMN abnormal_volume_z REAL;
ALTER TABLE outcomes ADD COLUMN range_ratio REAL;
ALTER TABLE outcomes ADD COLUMN market_return_bps REAL;
ALTER TABLE outcomes ADD COLUMN beta_used REAL;
ALTER TABLE outcomes ADD COLUMN direction_hit_abnormal INTEGER;
ALTER TABLE outcomes ADD COLUMN brier_abnormal REAL;
ALTER TABLE outcomes ADD COLUMN surprise_confirmed INTEGER;

-- Need SPY prices for market-model math (same table as prices, ticker='SPY')
-- No schema change needed — just add SPY to an always-fetched list in ingest.
```

---

## 4. New LLM prompt — `prompts/news_impact.txt`

The heart of the new pipeline. Short sketch:

```
[SYSTEM]
You are a buy-side analyst estimating the idiosyncratic price impact of a single news item on a single stock. You respond ONLY with JSON matching the schema below. No prose, no markdown fences.

Scoring discipline:
- magnitude_bps is the IDIOSYNCRATIC move you expect after controlling for the market. Not the raw close-to-close.
- Default to LOW magnitudes. Most news is noise. Only stories that move a typical analyst's earnings model should exceed 100 bps.
- If you cannot assess surprise vs consensus, set surprise_score=0.5 and explain in caveats.
- If the article is a rehash of a story already out, set novelty_score below 0.3.

Schema:
{
  "category": "earnings_surprise | guidance | analyst_change | mna | regulatory | product_launch | lawsuit | macro_passthrough | insider | rumor | rehash | other",
  "direction": "up | down | neutral",
  "magnitude_bps": <number, -300..+300>,
  "half_life_hours": <number, 1..720>,
  "confidence": <number, 0..1>,
  "surprise_score": <number, 0..1, where 0=fully expected, 1=total shock>,
  "novelty_score": <number, 0..1, where 0=duplicate of existing coverage, 1=entirely new>,
  "expected_volume_mult": <number, 0.5..20>,
  "horizon_coverage": "intraday | 1d | 3d | 5d | 2w+",
  "key_quote": "<≤160 chars>",
  "caveats": ["<short phrase>", ...]
}

Calibration hints (learned from prior outcomes):
{category_priors_text}

[USER]
Ticker: {ticker}
Current time: {now_iso}
Sector ETF {sector_etf} 1d return: {sector_return_bps} bps
Market (SPY) 1d return: {spy_return_bps} bps

Most recent 5 news items for {ticker} (for novelty comparison):
{recent_news_compact}

Consensus snapshot (if available):
{consensus_snapshot_or_none}

News item to score:
Title: {title}
Published: {published_at}  (age: {age_hours}h)
Source: {source}
Body (truncated to 5000 chars):
{body}

Return JSON only.
```

`{category_priors_text}` is injected from the `news_impact_outcomes` table — a one-line summary per category of our running bias (e.g. "earnings_surprise: we overestimate magnitudes by +40 bps on average; trim your estimates accordingly"). This is how the system self-corrects in-context.

---

## 5. Evaluation: what "better" looks like

At day 20, 50, 100 we answer these questions:

| Metric | Target at day 50 | How computed |
|---|---|---|
| Abnormal direction hit rate | > 54% | `AVG(direction_hit_abnormal)` |
| Brier on calibrated prob | < 0.24 (0.25 = random) | `AVG(brier_abnormal)` |
| Per-category MAE (earnings) | < 80 bps | `AVG(ABS(residual_bps))` where category='earnings_surprise' |
| Volume-confirmation rate | > 60% for predicted magnitude > 100 bps | `AVG(surprise_confirmed)` where `predicted > 100` |
| Sharpe of paper P&L | > 0.5 annualized | daily sum of signed AR weighted by confidence |
| Per-news residual distribution | mean ≈ 0, σ declining over time | residuals should converge on zero-mean if calibration works |

If abnormal hit rate converges toward 50% but raw hit rate stays above 50%, we're riding market beta, not news alpha — a diagnosis we currently cannot make.

---

## 6. Implementation plan: F09, F10, F11, F12, F13, F14

These are the next three features to append to `docs/feature_backlog.md`:

### F09 — Per-news impact scoring

- New module `src/stock/impact.py` with `score_news_item(news_id, conn) -> NewsImpact`.
- New prompt `prompts/news_impact.txt`.
- New table `news_impact`.
- Scheduler hook: after `_job_ingest_and_extract`, fire `_job_score_impacts` for any new-but-unscored news items.
- Also fetch SPY price bars in the default ingest loop so market return is always available.
- Tests: mock MiniMax response, verify DB row, verify idempotency.

**Acceptance**: for every news row, exactly one `news_impact` row exists within 15 min.

### F10 — Market-adjusted outcome scoring

- New module `src/stock/beta.py` for rolling-β estimation against SPY (120-day OLS, refitted nightly). Writes to `ticker_beta`.
- Extend `score.py`: compute `abnormal_return_bps`, `abnormal_volume_z`, `range_ratio` from SPY and 20-day rolling stats. Store in extended `outcomes` columns.
- Extend `predict.py` aggregation: sum time-decayed `news_impact` contributions and feed as a secondary signal to the ticker-level LLM (not replacing it — adding as context).
- Tests: fixed SPY + ticker price fixtures, assert correct AR and AV computation.

**Acceptance**: every outcome has non-null abnormal_* columns; β table has ≥1 row per active ticker.

### F11 — Per-news attribution + category calibration

- Extend `score.score_due`: after writing each outcome, compute per-news attribution and write `news_impact_outcomes` rows.
- Extend `learn.py`: compute per-category bias and MAE; format as the `{category_priors_text}` block for the impact prompt.
- Extend weekly reflection: Claude Opus reads `news_impact_outcomes` and appends category-specific findings to `rules.md`.
- New CLI `stock calibration news` showing per-category predicted-vs-realized table.
- Tests: synthetic outcomes with known attribution answers.

**Acceptance**: `stock calibration news` returns a table with mean residual < 30 bps per category after 50 scored predictions.

### F12 — Multi-horizon predictions + size tiers

- Extend `predict.py` to emit three predictions per cycle (short/mid/long), each with its own `due_at` and `horizon_label`.
- Add `size_tier` classification to `news_impact` output; update prompt to demand tier.
- Split calibration into three per-horizon regressors.
- Update `stock report` / API to accept `horizon` param.
- Tests: fixture with known news impact + horizon, verify routing and weights.

**Acceptance**: every `on_demand` call produces 3 prediction rows (short, mid, long); `stock report horizon=long` returns a separate hit rate from `horizon=short`.

### F13 — Macro event analysis (big-news pipeline)

- New module `src/stock/macro.py`: `analyze_macro_event(news_id, conn) -> MacroEvent`.
- Call Claude Opus; store in `macro_events` + `macro_event_tickers`.
- Trigger from `impact.py` when `size_tier == 'big'` or macro-vocab hit.
- Cross-ticker propagation into predictions: every active watchlist ticker listed in `macro_event_tickers` pulls the decayed impact into its aggregation.
- Tests: mock Opus response, verify multi-ticker rows.

**Acceptance**: a seeded "Fed 50bps cut" news item produces ≥3 affected-ticker rows; subsequent predictions for those tickers reference the macro_event_id in their `feature_context_json`.

### F14 — Smart-money ingestion

- New modules `ingest/volume_anomaly.py`, `ingest/insider_form4.py`, `ingest/congressional.py`.
- New tables `volume_anomalies`, `insider_trades`, `congressional_trades`.
- Extend the ticker prediction prompt with a smart-money context block (30-day lookback).
- Extend `impact.py`: news items arriving after a detected anomaly get `tags += ['anomaly_confirmed']` and `+0.15` confidence.
- Weekly reflection reads smart-money attribution to tune anomaly thresholds.
- Tests: fixtures for EDGAR XML, CSV STOCK Act filings, synthetic volume spikes.

**Acceptance**: new Form 4 filings appear in `insider_trades` within 24h of EDGAR publication; anomalies land in `volume_anomalies` nightly; ticker prompt shows the smart-money block when data exists.

---

## 7. Known pitfalls and how we guard against them

- **Overfitting to recent regime**: priors refit weekly, not daily. Half-lives and β use 120-day windows.
- **Survivorship in memory retrieval**: when we inject similar past cases, we retrieve both hits and misses with balanced sampling — not only the successful ones.
- **Look-ahead leakage**: `news_impact` prediction is made at news ingest time; scoring uses only prices that post-date the news `published_at`. Entry price in `outcomes` is the first close after news time, not before.
- **Self-fulfilling rehash loops**: `novelty_score` shrinks duplicate coverage. A high-impact claim from a rehash-flagged item contributes ≤ half weight in aggregation.
- **LLM confabulation of consensus**: if `consensus_snapshot` is unavailable, the prompt forces `surprise_score=0.5` and records the uncertainty as a caveat rather than letting the model guess.
- **Category inflation**: we cap categories to the 11 listed. `"other"` is explicitly offered; misuse is flagged in validation.

---

## 7a. Multi-horizon predictions

A single 1-day horizon is too narrow. News behaves very differently depending on how far out you score it, and the system should forecast at three fixed horizons per prediction cycle:

| Horizon | Window | What it answers | Dominant signals |
|---|---|---|---|
| **short** | 1–10 trading days | "Does this news have a tradeable swing move?" | fresh news impacts, momentum, volume, short half-life items |
| **mid** | ~1 month (20 trading days) | "Is the stock mis-priced through the next catalyst?" | earnings cycle position, guidance changes, analyst revisions, 30-day drift from known catalysts |
| **long** | ~3 months (60 trading days) | "Has something structural changed in the thesis?" | thematic/regime news, supply-chain shifts, product-cycle changes, analyst model revisions |

### How this slots into the pipeline

The per-news impact prompt already asks for `half_life_hours` and `horizon_coverage`, which is exactly the data we need. The change is:

1. **Three predictions per cycle, not one.** `predict.py` runs three LLM calls (or one call returning a 3-element structured output — cheaper, but harder to prompt well). Each has its own `due_at`:
   - short: `now + 5 trading days`
   - mid: `now + 20 trading days`
   - long: `now + 60 trading days`
2. **Horizon-specific aggregation weights.** Short-horizon aggregation filters out items with `half_life_hours > 120`; long-horizon aggregation filters out items with `half_life_hours < 48` and gives higher weight to items with `horizon_coverage` in `{"2w+"}`.
3. **Per-horizon calibration.** Three separate calibration regressors. The same 0.65 `prob_up` probably means different things at 5d vs 60d, so we train three isotonic models on three populations of scored outcomes.
4. **Per-horizon reporting.** `stock report` takes a `horizon` param (`short|mid|long|all`) and shows hit rate, Brier, abnormal return separately. A prediction that nails long-term and whiffs short-term should be visible as such.

### Schema addition

```sql
ALTER TABLE predictions ADD COLUMN horizon_label TEXT;  -- 'short' | 'mid' | 'long'
-- horizon_minutes already exists, keep it for precise due_at computation
```

Predictions are grouped by `(ticker, created_at, horizon_label)`. The three horizons share the same news-impact inputs but get separate LLM outputs, separate outcomes, separate calibration.

### Why not more horizons?

Three gives enough resolution to detect mispricing across time scales without multiplying LLM cost 10x. Between-horizon gaps (e.g. 15-day moves) can be interpolated if needed. We tried specifying 5 or 7 horizons in scratch design and got diminishing signal; 3 is the sweet spot.

---

## 7b. Macro and big-news handling

Most news moves one stock. A minority of news moves entire sectors or the whole market — Fed rate decisions, tariff announcements, landmark AI releases ("ChatGPT launches", "NVIDIA AI export controls"), major regulatory actions, geopolitical shocks. These items have three properties the current design does not handle:

1. **Cross-ticker reach** — a tariff on Chinese semis moves NVDA, AMD, TSM, INTC, AVGO, QCOM, plus adjacent supply chain. A single news item must propagate to many tickers, each with its own sensitivity.
2. **Longer half-life** — regime changes persist for months, not hours. Half-life can be 30–90 days.
3. **Path-dependent impact** — interacts with other macro news. A second rate cut after the first one is priced in produces a different reaction than the first.

### Detection — two-tier triage

Every news item first passes the standard `news_impact` scoring in `stock.impact`. Additionally, if any of these trigger, the item is flagged `scope=macro` and routed to a second, heavier analysis:

- Predicted `magnitude_bps` > 200 AND `expected_volume_mult` > 3
- Category in `{"regulatory", "macro_passthrough"}` with `novelty_score` > 0.7
- Body mentions any term in the macro-trigger vocabulary (Fed, FOMC, tariff, CHIPS Act, export control, sanction, ECB, BOJ, OPEC, antitrust ruling, landmark court decision, major central bank pronouncement, top-3 AI lab model release)

Flagged items go to `stock.macro.analyze_macro_event(news_id)`, which calls **Claude Opus** (not MiniMax) for one deeper pass — macro reasoning is exactly where Opus beats MiniMax handily, and the call fires at most a few times per day so cost stays under $0.05/day.

### Macro output schema

```json
{
  "event_id": "auto-generated",
  "scope": "sector | supply_chain | market | commodity | geopolitical",
  "primary_dimensions": ["semiconductor_equipment", "china_exposure", "ai_capex"],
  "half_life_days": 45,
  "regime_shift": true,
  "affected_tickers": [
    {"ticker": "NVDA", "sensitivity": 1.0, "direction": "down", "magnitude_bps": 180, "confidence": 0.6},
    {"ticker": "AMD", "sensitivity": 0.7, "direction": "down", "magnitude_bps": 130, "confidence": 0.5},
    {"ticker": "TSM", "sensitivity": 0.9, "direction": "down", "magnitude_bps": 160, "confidence": 0.55}
  ],
  "non_obvious_affected": [
    {"ticker": "ASML", "sensitivity": 0.8, "rationale": "EUV demand proxy", "direction": "down", "magnitude_bps": 140}
  ],
  "second_order_effects": "China domestic chip names (SMIC) may benefit...",
  "watch_for": ["retaliation from China", "export license exemptions"],
  "precedent_events": ["2022 Oct 7 BIS rules"]
}
```

This goes to a new `macro_events` table:

```sql
CREATE TABLE macro_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  news_id INTEGER NOT NULL,
  scope TEXT NOT NULL,
  primary_dimensions_json TEXT NOT NULL,
  half_life_days REAL NOT NULL,
  regime_shift INTEGER NOT NULL,
  full_analysis_json TEXT NOT NULL,
  model TEXT NOT NULL,
  cost_usd REAL NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (news_id) REFERENCES news(id)
);

CREATE TABLE macro_event_tickers (
  event_id INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  sensitivity REAL NOT NULL,
  direction TEXT NOT NULL,
  magnitude_bps REAL NOT NULL,
  confidence REAL NOT NULL,
  is_non_obvious INTEGER NOT NULL,
  PRIMARY KEY (event_id, ticker),
  FOREIGN KEY (event_id) REFERENCES macro_events(id)
);
```

### How macro events enter predictions

When `predict.py` aggregates news impacts for a ticker, it also queries live macro events whose decay window still covers the horizon:

```
for each live macro_event where ticker in affected_tickers:
    decayed_impact = magnitude_bps × 2^(-age_days / half_life_days) × confidence
    add to aggregation with marker scope='macro'
```

Crucially, the ticker LLM prompt now receives a **separate section** listing active macro events with their full analysis text — so the model can reason about how a specific ticker's story interacts with the macro regime, not just receive a number. This is where LLM context wins vs a pure numerical model.

### How we learn which macro calls were right

After macro-affected outcomes are scored, we compute:
- Per-event MAE across all affected tickers (was Opus's cross-ticker call directionally right on average?)
- Per-"non-obvious" flag accuracy (did the stretched-inference tickers actually move?)
- Half-life audit (did the effect actually decay on Opus's predicted schedule?)

These feed into a new section of the weekly rules update — "macro patterns we got right / wrong."

### Budget impact

Macro reasoning through Opus at ~20k input + 2k output per call × ~3–5 events/week ≈ **$0.50–$0.80/week** additional. Within budget. Still gated by `DAILY_COST_CEILING_USD`.

---

## 7c. Event size classification — small, medium, big

Every news item gets tagged with a `size_tier` during the impact scoring step, on top of its `category`. Size is *functional*, not editorial — it governs which horizons the event shows up in and whether it gets escalated to the macro pipeline.

| Tier | Criteria (any sufficient) | Routing | Horizon weight |
|---|---|---|---|
| **small** | magnitude_bps < 50 AND expected_volume_mult < 1.5 | news_impact only | short: 1.0, mid: 0.3, long: 0.0 |
| **medium** | 50 ≤ magnitude_bps < 200, OR 1.5 ≤ volume_mult < 3 | news_impact + confidence boost if anomaly-confirmed | short: 1.0, mid: 0.7, long: 0.2 |
| **big** | magnitude_bps ≥ 200 OR volume_mult ≥ 3 OR regulatory/macro category with novelty ≥ 0.7 OR macro-vocab hit | news_impact + **Claude Opus macro analysis** (§7b) + cross-ticker propagation | short: 0.5, mid: 1.0, long: 1.0 |

Examples:

| Event | Tier | Why |
|---|---|---|
| Analyst price-target bump on AAPL | small | 30-bps impact, normal volume |
| AAPL earnings beat + guidance raise | medium | 100–150 bps, 2–3× volume, horizon 1–5 days |
| FOMC 50bps cut | big | market-wide, regime-level, half-life 60+ days |
| Ukraine war escalation | big | geopolitical, cross-sector (energy, defense, cyber), half-life weeks |
| New Claude model release | big for NVDA/GOOG/MSFT/AMZN supply-chain and adj. AI names | cross-ticker AI capex signal |
| Iran–Israel peace deal | big | commodity (oil, tankers) + equities (defense, airlines) |
| Senate passes CHIPS Act amendment | big | regulatory, cross-ticker (semi ecosystem) |

Schema addition: `news_impact.size_tier TEXT NOT NULL CHECK(size_tier IN ('small','medium','big'))`.

The ticker-level prediction prompt receives events grouped by tier — "3 small items net +15 bps, 1 medium earnings beat +90 bps, 1 big macro shift (see macro_events #47) attached." This makes the aggregation legible to the LLM and forces it to weight tiers coherently instead of blending them into one fuzzy sentiment.

---

## 7d. Smart-money signals — pre-news anomalies and insider data

Our current pipeline reacts *to* news. But the real edge is often in the data that moves *before* news breaks. Three sources:

1. **Abnormal volume before public news** — the oil example: crude futures volume spiked days before the Iran war headline broke. Congressional/institutional/sovereign positioning leaves a volume fingerprint. The 12-day peace-deal example is the same phenomenon in reverse.
2. **Insider transactions** — SEC Form 4 filings (executives, directors, 10%+ holders) and congressional disclosures under the STOCK Act. Pelosi/Crenshaw-tracker style data. Executive *open-market buys* (not option exercises) are the single most replicated short-horizon alpha signal in the finance literature.
3. **Unusual options activity** — large single-strike call/put blocks, IV spikes, open-interest jumps before catalysts. Smart money often prefers options for leveraged conviction bets.

### 7d.1 Detection

Three new ingestion modules:

```
src/stock/ingest/
  volume_anomaly.py     # nightly: flag (ticker, date) pairs where V_t / median(V_{t-20..t-1}) > 2.5
                        #          and no news was ingested that day
                        #          store in volume_anomalies table
  insider_form4.py      # SEC EDGAR Form 4 RSS:
                        #   https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4&...
                        #          parse filings, extract transaction_type, shares, price, officer_title
                        #          store in insider_trades table
  congressional.py      # Quiver Quant public endpoints OR scrape disclosure.senate.gov /
                        #   clerk.house.gov. Both have filings required within 45 days of trade.
                        #          store in congressional_trades table
```

Options activity is a stretch goal — the free data is weak and paid feeds (Tradier, OPRA, unusual_whales) cost $50–200/mo. Defer to after first 60 days of results.

### 7d.2 Schema

```sql
CREATE TABLE volume_anomalies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  ts TEXT NOT NULL,                 -- trading day
  volume INTEGER NOT NULL,
  baseline_20d_median INTEGER NOT NULL,
  ratio REAL NOT NULL,              -- volume / baseline
  had_public_news INTEGER NOT NULL, -- 1 if a news item hit same day
  price_return REAL NOT NULL,       -- realized return that day (for later attribution)
  detected_at TEXT NOT NULL,
  UNIQUE(ticker, ts)
);

CREATE TABLE insider_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  filer_name TEXT NOT NULL,
  filer_title TEXT,                 -- 'CEO', 'CFO', 'Director', '10%+ Holder', etc.
  transaction_type TEXT NOT NULL,   -- 'P' (open-market buy), 'S' (sale), 'A' (grant), etc.
  transaction_date TEXT NOT NULL,
  filed_date TEXT NOT NULL,
  shares REAL NOT NULL,
  price REAL,
  value_usd REAL,
  form_url TEXT NOT NULL,
  UNIQUE(ticker, filer_name, transaction_date, shares, transaction_type)
);

CREATE TABLE congressional_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  filer_name TEXT NOT NULL,
  chamber TEXT NOT NULL,            -- 'senate' | 'house'
  party TEXT,
  transaction_type TEXT NOT NULL,   -- 'buy' | 'sell' | 'exchange'
  transaction_date TEXT NOT NULL,
  filed_date TEXT NOT NULL,
  amount_range_low REAL,            -- STOCK Act uses ranges, not exact amounts
  amount_range_high REAL,
  source_url TEXT NOT NULL,
  UNIQUE(ticker, filer_name, transaction_date, transaction_type)
);
```

### 7d.3 How smart-money data enters prediction

Two distinct uses:

**Use A — as a prediction input.** The ticker-level prompt gets a new context block:

```
Smart-money signals for AAPL (last 30 days):
- 3 volume anomalies without public-news attribution (20d ago +2.1%, 14d ago -1.8%, 3d ago +3.4%)
- 1 insider open-market buy: CFO bought 15,000 shares @ $172 on 14d ago ($2.6M)
- 2 congressional buys: Sen. X buy $50k-100k 21d ago, Rep. Y buy $15k-50k 18d ago
- No unusual options data (feed unavailable)
```

Net interpretation is left to the LLM, but the prompt includes calibration text like "CFO open-market buys historically precede positive 30d abnormal return with ~55% hit rate" (refreshed from our own data once we've scored enough).

**Use B — to tag news events.** When a news item arrives, we check:

```
news_arrives(ticker=AAPL, ts=T)
→ look back 14 days for volume anomalies on AAPL
→ look back 45 days for insider/congressional buys on AAPL (longer due to STOCK Act lag)
→ if found, news_impact.confidence_adjustment = +0.15
  AND news_impact.tags += ['anomaly_confirmed']
```

A news item that *confirms* prior smart-money positioning is higher-confidence than one arriving out of the blue. Conversely, a news item with NO prior anomaly but huge predicted magnitude is slightly downgraded — smart money didn't see this coming either.

### 7d.4 Outcome side — pre-news anomaly attribution

For the weekly reflection, we answer a specific question:

> Of the volume anomalies we detected with no public-news attribution, what fraction were followed by material news within 14 days? How does the stock's 30-day forward return differ between anomalies that were vs. weren't followed by news?

This tells us whether our anomaly detector is finding real signal or noise. Over time we tune the `ratio > 2.5` threshold and the lookback window from this data.

### 7d.5 Budget impact

- Form 4 EDGAR scraping: free, ~5 MB/day.
- Congressional disclosure scraping: free if we implement the scraper ourselves (low volume: ~30 trades/day across Congress). If we use Quiver's paid API it's ~$10/mo.
- Volume anomaly detection: zero API cost, pure math on existing prices data.
- No additional LLM calls — the smart-money block is formatted text injected into the existing ticker prompt.

**Total added cost: ~$0/mo (scraping) or ~$10/mo (Quiver paid).** Recommended path: start with free scraping for Form 4 + Congress, add Quiver only if free data turns out to be too lagged.

### 7d.6 Legal/ethical note

This is all **publicly disclosed** data. SEC Form 4 is a public filing within 2 business days of the transaction. Congressional disclosures are required under the STOCK Act and public within 45 days. We are not using material non-public information. We are reading what Congress and executives are legally required to reveal, and noting that the market often hasn't fully priced it in yet.

---

## 8. What stays the same

- The existing ticker-level prediction (F02) keeps running — it becomes the *envelope* forecast that reads the aggregated news-impact sum as one of its inputs.
- Existing memory, bandit, calibration, weekly rules all stay. They get more granular data to chew on, but the mechanisms don't change.
- OpenClaw skill contract is unchanged — `stock.predict(AAPL)` still returns the same JSON shape to WeChat.
- Cost ceiling unchanged; the new news-impact call adds ~$0.012/day.

---

## 9. Decision for you

Two sequencing choices:

1. **Ship F09 alone first** — start logging per-news impact predictions now, so that by the time F10/F11 land we have 30–60 days of data to calibrate on. Lowest risk, fastest feedback. **Recommended.**
2. **Ship F09 + F10 together** — full pipeline, but we won't have historical per-news predictions to backfill AR against.

Either way, the current system keeps running during the build — no downtime, no data loss. The new tables are additive; outcomes table gets new columns via `ALTER`.

Want me to add F09/F10/F11 to `docs/feature_backlog.md` and let the pipeline implement them in continuous mode?

---

**Not financial advice.**
