# Forward-discovery research stack (find before it explodes)

Background reading that informed F19. Boss complaint: "By the time we tell him Bloomberg Energy was up 20x, the move is over. Find these BEFORE they explode and provide sufficient evidence in both logic and information."

The current pipeline (news ingest + Tavily search + technical anomalies) is structurally **lagging** -- everything we read is post-event by definition. F19 adds a leading-indicator layer alongside it.

## Papers

### 1. Cohen, Malloy, Pomorski -- "Decoding Inside Information"
- NBER w16454, J. Finance 2012. https://www.nber.org/papers/w16454
- Splits insider filers into "routine" (predictable monthly buys) vs "opportunistic" (irregular). Opportunistic-only portfolio earns ~82bps/month value-weighted alpha and predicts subsequent corporate news.
- **Steal:** tag every Form 4 filer by trading-frequency stdev over a 3-year window; weight only opportunistic buys. F19's `compute_insider_acceleration` does this.

### 2. Alldredge & Blank -- "Insider Cluster Trading"
- SSRN 2781761, J. Financial Research 2019.
- Cluster purchases (3+ insiders within 10 days) earn 3.8% over 21 days vs 2% for solo buys.
- **Steal:** count distinct insider buyers per 10-day window; cluster_size >= 3 fires the signal as a multiplier on the score.

### 3. PEAD.txt -- "Post-Earnings-Announcement Drift Using Text"
- JFQA, Cambridge. https://www.cambridge.org/core/journals/jfqa
- Text features from the 8-K/earnings release add alpha beyond SUE, especially in micro-caps.
- **Steal:** when an 8-K lands, score its NOVELTY (cosine distance vs the firm's last 4 8-Ks). High novelty + positive sentiment flag = pre-PEAD candidate.

### 4. MarketSenseAI 2.0
- arXiv 2502.00415 (2025). https://arxiv.org/abs/2502.00415
- Multi-agent LLM fuses transcripts + fundamentals + news + macro. Q&A tone + forward-looking language is alpha-generative; prepared remarks alone are not.
- **Steal:** when we eventually parse transcripts, weight Q&A hesitancy + topic novelty separately from prepared text.

### 5. "Can AI Read Between the Lines?"
- arXiv 2505.16090 (2025). https://arxiv.org/html/2505.16090v1
- Frontier LLMs underperform on strategically ambiguous earnings-call language; fine-tune/RAG approaches beat zero-shot.
- **Steal:** never trust raw GPT/Claude sentiment on transcripts. Build a domain rubric (capex direction, hiring plans, supply commentary) and score each axis separately.

### 6. Bianchi et al. -- "Supplier Disclosures and Customer Performance"
- https://www.herbert.miami.edu/faculty-research/business-conferences/winter-warmup/krupa_paper_miami.pdf
- Supplier 10-K mentions of "a major customer" predict customer outcomes.
- **Steal:** when an upstream supplier (TSMC, ASML, AMAT) mentions an unnamed large customer in commentary, dereference it via product line and supply-chain map. F19 reuses our existing `data/ai_supply_chain.yaml`.

### 7. Survivorship-bias correction (Bessembinder cited in lit)
- Only 42.1% of US common stocks beat T-bills over their lifetime; median public life ~7 years. SSRN 5833162.
- **Steal:** any backtest must include delisted tape; otherwise small-cap returns are fictional. F20 backtest harness flags this explicitly and treats five-name lookback as DIAGNOSTIC, not statistical.

## Free / near-free leading-indicator APIs

| # | Source | Install / endpoint | Signal |
|---|---|---|---|
| 1 | SEC EDGAR (Form 4, 8-K, 10-K) | already wired in `stock.ingest.insiders`; extend for 8-K novelty | insider buys, item-tagged 8-Ks, supplier commentary |
| 2 | PatentsView (USPTO) | `https://api.patentsview.org/patents/query` no key | patent grants/applications by assignee, growth rate |
| 3 | SAM.gov contract awards | `https://api.sam.gov/...` (free key, 1000/day) | federal contract wins |
| 4 | USAspending.gov | `https://api.usaspending.gov/` no key | higher-volume contract data |
| 5 | FINRA short interest | `https://api.finra.org/data/group/otcMarket/name/EquityShortInterest` | biweekly short-interest changes |
| 6 | Reddit (PRAW) | `pip install praw`, OAuth required, 100 qpm | r/wallstreetbets / r/stocks mentions |
| 7 | ApeWisdom | `https://apewisdom.io/api/v1.0/filter/wallstreetbets/` no key | pre-aggregated WSB ticker mention counts + sentiment |
| 8 | arXiv API | already installed (`pip install arxiv`) | company-name / product mentions in CS/ML papers |
| 9 | HN Algolia | `https://hn.algolia.com/api/v1/search` no key | HN mention timeline per ticker / product |
| 10 | yfinance options | already installed | IV-rank, put/call skew, OI deltas (dirty but free) |
| 11 | Revelio public labor stats | https://www.reveliolabs.com/public-labor-statistics/ | free aggregated headcount/job-posting trends |

## Scoring formulas (F19 implements 1, 2, 4 in v1; 3 deferred)

### 1. Opportunistic-Cluster Insider Score (OCIS)
```
OCIS_t = sum over Form 4 buys in [t-30, t]:
         1{opportunistic} * log(1 + buy_value_usd) * cluster_multiplier
cluster_multiplier = 1 + 0.5 * max(0, distinct_insiders_in_window - 1)
opportunistic = stdev(filer's prior 3yr trade months) > threshold
```

### 2. Quiet Accumulation Pattern (QAP) -- Wyckoff-lite gate
```
QAP = (price_range_60d / ATR_60d < 1.5)               # tight base
    AND (avg_volume_60d / avg_volume_prior_180d < 0.7) # volume dried up
    AND (OBV_slope_60d > 0)                            # OBV creeping
```
Used as a binary GATE -- pattern present, then rank gated names by composite score.

### 3. Theme-Velocity Score (TVS) -- DEFERRED to F19.5
```
TVS_theme = 0.4 * z(arxiv_mentions_30d)
          + 0.3 * z(hn_mentions_30d)
          + 0.2 * z(reddit_mentions_30d ex-WSB)
ticker_TVS = sum_themes (TVS_theme * cosine(ticker_10K_embedding, theme_keywords))
```
Requires a ticker-to-10K-embedding map we don't have yet; punt to a future feature.

### 4. Composite Future-Winner Probability (FWP)
```
FWP = sigmoid(
        0.40 * z(OCIS)
      + 0.20 * z(8K_novelty)        # cosine distance vs firm's prior 8-Ks
      + 0.15 * z(short_interest_decline_3mo)
      + 0.15 * z(reddit_mention_acceleration)  # ApeWisdom delta
      + 0.10 * z(supplier_mention_count)       # placeholder; manual for now
      ) * QAP_gate
```
F19 ships with these weights as defaults; a calibration step on a delisted-inclusive universe is F20.

## Honest caveats (all from the agent's research)

- **Survivorship is the killer.** Backtests on today's tickers overstate small-cap returns by ~5pp/yr (SSRN 5833162). Use CRSP with delisted returns or your numbers are fiction.
- **Five-name lookback (BE/NVDA/SMCI/ENPH/AMD) is not a backtest.** It's diagnostic only -- tells us whether a signal would have caught a known winner, not its true hit rate.
- **Reddit data is broken post-Pushshift.** PRAW caps at ~1000 historical posts per listing. Don't backtest on it; use forward-only.
- **Free options data (yfinance) is dirty.** Delayed mid-quotes with stale OI; "unusual activity" without true tape access is mostly noise.
- **LLM thesis-discovery hallucinates tickers.** Use LLMs for theme surfacing, never as the final stock-selection filter.
- **PEAD micro-cap effect is mostly transaction-cost illusion** for typical retail execution. Slippage on $2 stocks is brutal.

## Implementation map (F19)

| Idea | F19 module |
|---|---|
| Opportunistic insider tagging + clusters (CMP, Alldredge) | `stock/leading.py::compute_insider_acceleration` |
| 8-K novelty (PEAD.txt) | `stock/leading.py::compute_8k_novelty` |
| Quiet accumulation gate | `stock/leading.py::compute_quiet_accumulation` |
| Composite FWP scoring | `stock/discovery_engine.py::score_candidates` |
| Auto-promote top-N to watchlist | `stock/discovery_engine.py::promote_top_candidates` |
| Surface in research note + grading note | prompt updates + `format_candidates_block` |
| Backtest harness (diagnostic, not statistical) | `stock/backtest_winners.py` (F20) |

Not financial advice.
