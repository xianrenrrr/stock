# STOCK Runtime Source Of Truth

Last verified: 2026-06-11 from `src/stock/orchestrator.py:create_scheduler()`
(39 active jobs in local mode).

This file is the source of truth for what runs automatically. Older roadmap
files describe design history and may be stale.

## Operating Modes

| Mode | Setting | Behavior |
|---|---|---|
| Local full pipeline | `STOCK_MODE=local` | Scheduler runs all jobs below plus FastAPI/dashboard sync and email. OpenClaw auto-delivery is disabled by default. |
| Render cloud proxy | `STOCK_MODE=cloud_proxy` | Scheduler is disabled. FastAPI only serves `/channel/*` and `/sync/*`. |

## Delivery Policy

Primary delivery is Boss app / Render sync plus SMTP email. The legacy OpenClaw
GUI-delivery path is retained only for manual fallback testing and must stay
disabled in normal orchestration:

```env
OPENCLAW_AUTO_DELIVER=false
```

The orchestrator should not spawn `openclaw agent --local` automatically. If
OpenClaw is running separately, it is not required for reports, alerts, or
emails.

## LLM Backend Policy

Runtime LLM calls are Codex-first:

- `CORE_LLM_BACKEND=codex_cli` is the default and applies to research, grading,
  predictions, features, intent classification, thesis extraction, discovery
  extraction, replies, and self-review.
- Codex CLI falls back only to Claude CLI when available.
- MiniMax is retired for runtime use. `CORE_LLM_BACKEND=minimax` is treated as a
  legacy value and routed to Codex CLI. Direct `get_client("minimax")` calls fail
  closed so leftover code cannot silently use MiniMax again.
- Image uploads use Codex CLI image input first (`codex exec -i <png>`), then
  Anthropic vision only as an optional fallback when `ANTHROPIC_API_KEY` is
  configured. They never call MiniMax.

## Job Observability (2026-06-09)

Every scheduled job execution is recorded in the `job_runs` table by an
APScheduler listener installed in `create_scheduler()`:

- `ok` rows are kept ONE per job (replaced on each success) so the 5-second
  `sync_to_render` job cannot bloat the table; `error`/`missed` rows are
  append-only history, pruned after 14 days by the nightly `backup_db` job.
- `_job_pull_broker_positions` records its deliberate `BrokerPullError` skips
  as error rows too (the exception is swallowed, so the listener alone would
  log them as ok). Holdings previously went 5 days stale with zero trace.
- The warning dashboard raises a HIGH "Robinhood holdings sync is stale"
  warning when broker-synced holdings have not updated for >36h on a weekday
  (>84h on Monday to allow the weekend pause).

Operator commands:

```powershell
python -m stock.cli jobs               # every job: next fire, last ok, last error
python -m stock.cli trigger <job_id>   # run any scheduled job right now
python -m stock.cli usage --days 7     # LLM usage: codex/claude calls, tokens,
                                       # fallback share, top callers by tokens
```

`stock usage` reads the `llm_calls` ledger. Codex/Claude CLI backends are
subscription (cost_usd=0), so TOKENS are the quota signal; a rising claude_cli
share means the codex credit/usage circuit breaker (F17c) is tripping.

## Quota-Aware Leftover Retry (Plan I, 2026-06-10)

Codex/Claude CLI subscription quotas refresh on a ~5-hour session window. The
broker positions pull was dead June 4-10 purely from codex usage-limit
exhaustion. Now:

- When F17c detects a codex credit/usage-limit hit, the event is persisted to
  `usage_limit_events` (provider, caller, detected_at) in addition to opening
  the in-memory circuit breaker.
- `retry_quota_leftovers` (every 30 min) maps open events -- and job_runs
  errors whose text looks credit-shaped -- back to scheduler job ids via the
  caller prefix map in `src/stock/quota.py`, and re-runs each job once
  `detected_at + 5h` has passed (quota refreshed). Allowlisted jobs only
  (research/dives/predictions/scoring/broker pull etc.; 5-min plumbing jobs
  excluded), max 2 retries per job per 24h, and a job that already succeeded
  on its next scheduled fire is marked recovered instead of re-run.
- Retries are recorded in `job_runs` with `trigger='quota_retry'`.
- `stock usage --windows` shows per-provider consumption bucketed into fixed
  5h UTC windows plus the latest limit event and its expected refresh time.

## Feature Extraction Is Batched (2026-06-11)

`extract_features` sends 8 articles per LLM call (id-keyed items array) with
per-article fallback on unparseable batch responses — cutting the biggest CLI
quota consumer (~430 calls/day) roughly 8×. Caller: `features.extract_batch`.

## Context DAG + Ablation (Plan H phases H1/H4, 2026-06-11)

Shared prediction blocks (macro, market_internals, sector_breadth) resolve
through memoized `context_nodes` (rendered once per batch; fingerprint-based
invalidation; failures degrade to direct render). Each prediction records a
`context_manifest` of node content hashes in `feature_context_json`.
`stock ablation [--days N]` reports hit rate/Brier WITH vs WITHOUT each
signal. First live run (45d, n=2064): knowledge-era predictions 62.4% hit
vs 49.1% without (n=322/1742) — attribution between knowledge/macro is
still confounded (same era).

## Gov Trades Collector (Plan H phase H3, 2026-06-11)

`gov_trades_pull` (daily 05:30 UTC) reads the JSON feed in `GOV_TRADES_URL`
into the `gov_trades` table (QuiverQuant + stock-watcher field names parsed;
dedup on politician/ticker/type/date/amount). **It is a NO-OP until
`GOV_TRADES_URL` is set** — the free community mirrors are dead (403), so the
operator must choose: paid QuiverQuant API vs building an eFD scraper.
When data exists, predictions append a per-ticker gov-trades block (with the
45-day disclosure-lag caveat) and `stock gov-trades <TICKER>` inspects it.

## Active Scheduled Jobs

There are 39 active APScheduler jobs in local mode.

| Job id | Cadence UTC | What it actually does | Main output |
|---|---:|---|---|
| `ingest_and_extract` | Mon-Fri 02:00, 14:00 | Fetch prices/news and extract features for active tickers. | `news`, `prices`, `features` |
| `run_predictions` | Mon-Fri 02:15, 14:15 | Run prediction cycle for watchlist. | `predictions` |
| `research_push_morning` | Mon-Fri 02:30 | Generate morning research note and push/sync it. | `research_reports(kind='daily')` |
| `research_push_evening` | Mon-Fri 14:30 | Generate evening research note and push/sync it. | `research_reports(kind='daily')` |
| `daily_action_email` | Mon-Fri 14:45 | Email the latest daily research/action report to `DAILY_REPORT_EMAIL_TO`. | SMTP email |
| `learn_from_feedback` | every 5 min | Process boss replies, classify intent, queue follow-ups, apply prompt rewrites when safe. | `conversations`, `action_queue`, `prompt_rewrites` |
| `sync_to_render` | every 5 sec | Push local notes/tokens to Render and pull dashboard replies (near-instant reply latency; also keeps the Render free tier warm). No-op if `RENDER_SYNC_URL` is empty. | Render sync state |
| `warning_dashboard_publish` | every 15 min | Publish changed warning dashboard snapshots to Boss app/Render and email high-risk changes. | `research_reports(kind='warning_dashboard')`, SMTP email |
| `broker_snapshot_import` | every 5 min | Import filled Robinhood positions from `data/robinhood_positions_snapshot.json` into local holdings. Queued orders are ignored until filled. | `holdings` |
| `broker_positions_pull` | Mon-Fri every 30 min, 12:00-21:00 | Pull LIVE Robinhood positions via a codex/RH-MCP session (read-only `get_equity_positions`), write the snapshot, import it, and refresh daily bars for held tickers. Keeps the holdings table + warning dashboard in sync with the real account + latest prices. | `data/robinhood_positions_snapshot.json`, `holdings`, `prices` |
| `intraday_holding_move_alerts` | Mon-Fri every 15 min, 13:00-20:59 | Live quote crash/spike alerts for active holdings; catches moves like AMBA -20% before close. | `research_reports(kind='alert')` |
| `post_close_snapshot` | Mon-Fri 20:05 | Refresh settled daily bars and flag close/volume snapshots. | prices/anomaly context |
| `stop_order_propose` | Mon-Fri 20:10 | Compute desired SELL stop-limit orders for active holdings and PROPOSE them (human-armed). Writes `data/desired_stop_orders.json` + an alert note. NEVER places. | `research_reports(kind='alert')`, proposal file |
| `score_daily` | Mon-Fri 21:30 | Score due predictions. | `outcomes`, bandit/calibration updates |
| `anomaly_compute` | Mon-Fri 21:35 | Recompute price/volume anomalies. | `price_anomalies` |
| `thesis_verify` | Mon-Fri 21:40 | Verify prediction theses after outcomes are scored. | `prediction_theses` verdicts |
| `grade_and_reply` | Mon-Fri 21:45 | Generate grading note, queue follow-ups, and auto-improve rules/prompts when safe. | `research_reports(kind='grading')`, `action_queue`, `prompt_rewrites` |
| `verify_tracked_events` | Mon-Fri 21:50 | Verify tracked catalyst events. | `tracked_events` |
| `uoa_scan` | Mon-Fri 21:55 | Scan unusual options activity and aggregate call/put ratios. | `option_anomalies`, `option_ratio_snapshots` |
| `smallcap_scan` | Mon-Fri 22:15 | Score curated small-cap universe. | `smallcap_candidates` |
| `discovery_engine` | Mon-Fri 23:00 | Forward-looking candidate scoring and auto-promotion. | `discovery_candidates`, watchlist adds |
| `backup_db` | daily 23:30 | SQLite online backup. | `data/backups/` |
| `action_queue_runner` | daily 00:00, 12:00 | Drain pending follow-up topics into deep dives (auto-generated follow-ups). | `research_reports(kind='deep_dive')` |
| `action_queue_expedite` | every 5 min | Fast-track ONE user-initiated (dashboard-typed) pending item into a deep dive so boss research requests are answered in minutes, not at the 00:00/12:00 batch. The instruction path also posts an instant ack note. | `research_reports(kind='deep_dive')` |

Dashboard message handling: identical re-sends within 6h are de-duplicated
(`conversation.is_duplicate_inbound`) so a repeated boss message does not queue a
second deep-dive or generate a duplicate reply. Deep dives (`generate_deep_dive`)
prepend live yfinance quotes for any tickers named in the request so answers cite
current prices, not stale local bars.
| `daily_self_review` | daily 06:00 | Compile operational self-review packet and run configured autopilot. | `pipeline/daily_review_YYYY-MM-DD.md` |
| `reflect_weekly` | Sat 06:00 | Weekly prediction-rules reflection. | `data/rules/vNNN.md`, `data/rules/current.md` |
| `health_check_weekly` | Sat 07:00 | Per-holding weekly health-check deep dive. | `research_reports(kind='health_check')` |
| `weekly_qa_dive` | Sat 07:00 | Q&A deep dive on top forward-discovery candidates. | `research_reports(kind='deep_qa')` |
| `weekly_tech_dive` | Sun 04:30 | F43 tech-trend deep dive from `data/topic_queue.yaml`, now sector-rotated by ISO week across information / biopharma_ai / energy / ai_demand (buyer-side) / space_tech, and ending with a Chokepoint 5-dim research-priority score. The topic's `phase` (early/emerging/mature) flows into scoring. | `research_reports(kind='tech_dive')`, `tech_dive_runs` (now incl. `phase` + `score_*` columns) |
| `insiders_pull` | Sun 05:00 | Pull SEC Form 4 insider filings. | `insider_filings` |
| `weekly_entry_scan` | Sun 06:00 | Scan conviction/DD names for pullback entry zones. | `research_reports(kind='entry_signals')` |
| `ai_loop_measure` | Mon 06:30 | Measure AI commercial-loop risk panel. | `ai_loop_health` |
| `company_dd_dive` | Wed 09:15 | Run one queue-rotated company DD checklist. | `pipeline/dd/<TICKER>.md`, `research_reports` |
| `web_discovery_morning` | Mon-Fri pre-morning push | Search/fetch/extract web discovery context. | `web_research` |
| `web_discovery_evening` | Mon-Fri pre-evening push | Search/fetch/extract web discovery context. | `web_research` |

## Tracked Fields

Daily research is now multi-field. Active manually configured fields include:

- IT / AI semis
- AI biology / biopharma
- AI-DC energy
- Space tech
- AI compute cloud / miner-to-AI conversion
- Critical materials / rare earths
- AI demand / buyer-side (who consumes AI compute to produce value at scale —
  the demand that justifies the capex; "if AI can't find a buyer, it's a bubble").
  Seeded in `data/tech_trends.yaml` + `data/topic_queue.yaml` under sector
  `ai_demand`. In the Chokepoint score, the "supply bottleneck" dimension is
  scored as moat/defensibility (proprietary data, distribution, lock-in).

### Chokepoint research-priority score

Every weekly tech dive ends with a 5-dimension Chokepoint score (industry trend
25% + supply-bottleneck/moat 25% + company validation 25% + valuation mismatch
15% − risk 15%). The composite is recomputed server-side (the LLM's own number is
ignored) and persisted in `tech_dive_runs.score_*`. The daily research note shows a
cross-field research-priority leaderboard built from the last 21 days of scored
dives. Early/emerging `phase` fields score validation + valuation on an
option-value basis and are flagged high-variance, so pre-revenue names (space,
early bio) are not penalized like mature-cap misses.

## Warning Dashboard

Boss app `/channel/` now has a top warning panel backed by
`/channel/api/warnings`.

It aggregates:

- active holding P&L and F24 stop distance from the local holdings/prices DB,
- recent `research_reports(kind='alert')`,
- recent price/volume anomalies for active holdings.
- general AI-cycle crash warnings from `ai_loop_health`,
- broad AI-production-chain breadth breakdowns from the prices table,
- bearish options pressure from `option_ratio_snapshots` and unusual put
  activity from `option_anomalies`.

Every 15 minutes, changed warning content is also persisted as
`research_reports(kind='warning_dashboard')`, which means it is synced to the
Boss app / Render through the normal notes pipeline. If the changed warning set
contains high-severity items, the same warning report is emailed through SMTP.
The weekday daily action email also prepends the current warning dashboard above
the daily action report.

Real broker stop-loss order creation or edits are not automatic. The system can
compute and display stop levels and alert on breaches; actual broker orders
still require an explicit confirmed trading instruction.

## Human-Armed Stop-Loss Orders

`src/stock/stop_orders.py` adds an OPTIONAL, human-armed path to actually place
stop-loss orders via the `robinhood-trading` MCP (which exposes
`place_equity_order` with `type=stop_limit`, `review_equity_order` for dry-run,
`get_equity_orders`, and `cancel_equity_order`). It is a file bridge, the placing
mirror of `broker_snapshot_import`:

1. `stop_order_propose` (Mon-Fri 20:10 UTC) computes a SELL stop-limit order per
   active holding from `stops.compute_stop_loss` (stop_price = F24 recommended
   stop; limit_price = 1% below the stop). It writes `data/desired_stop_orders.json`
   (mode=`proposed`) and an alert note. **It never places an order.**
2. The operator arms placement explicitly:
   - `stock stops propose` — recompute + write the proposal.
   - `stock stops place` — dry-run REVIEW only (`review_equity_order`); no orders.
   - `stock stops place --confirm` — spawns a codex / RH-MCP session that places
     the REAL sell stop-limit orders (review -> dedup via `get_equity_orders` +
     `ref_id` idempotency -> `place_equity_order`), writing
     `data/stop_orders_result.json`.
   - `stock stops status` — show the last proposal + placement result.

Nothing in the background orchestrator places an order. Live placement requires
the explicit `--confirm` CLI path and an "agentic-allowed" Robinhood account.

## Robinhood MCP Bridge

Codex can access Robinhood through the `robinhood-trading` MCP in an interactive
session. The background Python orchestrator cannot directly call Codex MCP
tools, so the runtime bridge is file based:

1. A Codex/RH MCP session writes a positions snapshot to
   `data/robinhood_positions_snapshot.json`. This is now AUTOMATED: the
   `broker_positions_pull` job (Mon-Fri every 30 min) spawns a read-only codex
   session (`broker_sync.pull_positions_via_codex`) that calls
   `get_equity_positions` and writes the snapshot. Run on demand with
   `stock broker pull`.
2. `broker_snapshot_import` (and the pull job) import only non-zero filled
   positions into `holdings`, and `broker_positions_pull` then refreshes daily
   bars for the held tickers.
3. Existing holding alerts, stop-loss tables, anomaly scans, daily research, and
   the warning dashboard monitor those holdings -- now backed by LIVE positions +
   latest prices rather than a stale `holdings.yaml`.

Queued/pending buy orders are not counted as holdings until Robinhood reports a
filled non-zero position.

**Pull reliability (2026-06-04):** the robinhood-trading MCP is interactively
authenticated and is often UNAVAILABLE in headless `codex exec`, so the auto-pull
returns empty/partial unpredictably. Two safeguards: (1) `pull_positions_via_codex`
raises `BrokerPullError` (skips, writes no snapshot) when it gets zero positions or
an MCP-unavailable error; (2) all AUTOMATED imports are UPSERT-ONLY
(`deactivate_missing=False`) -- they never deactivate holdings, because a flaky
empty/partial pull must not be mistaken for "sold everything" and wipe real
positions. Sold positions are removed manually (`stock holding remove <TICKER>`)
or via an explicit `stock broker import-snapshot` of a trusted full snapshot
(which keeps `deactivate_missing=True`). The pull also now reads ALL accounts
(`{"accounts":[...]}` multi-account format).

**Warning dashboard de-noise (2026-06-04):** warnings render only in the top
warning panel. `publish_warning_dashboard` updates a SINGLE
`research_reports(kind='warning_dashboard')` row in place (was inserting a new row
every 15 min), and `/channel/api/notes` excludes `kind='warning_dashboard'` from
the feed, so the boss app no longer shows a wall of duplicate warning notes.

### Holdings source of truth (2026-06-02)

Live Robinhood is now the SOLE source of truth for holdings. `data/holdings.yaml`
is intentionally EMPTY (`holdings: []`) so startup `sync_from_yaml()` is a no-op
and does not fight the live pull. Previously a populated yaml re-added stale names
(e.g. MSFT) and culled live-only positions on every restart. Do NOT repopulate
`holdings.yaml` to "fix" it — to force-track a non-Robinhood name use
`stock holding add <TICKER> <qty> <cost>`. The `broker_positions_pull` job keeps
the holdings table in sync with the live account; `broker_snapshot_import`
deactivates exited positions.
- AI network equipment
- Defense drones / autonomy
- Robotics / autonomous systems
- Rotating secular themes

`web_discovery` also updates `data/emerging_fields.yaml` when recent discovery
themes repeatedly point to AI-driven or breakthrough technology shifts such as
space tech, quantum, robotics/autonomy, fusion, advanced materials, or synthetic
biology. Candidate fields are shown in the daily research prompt and can be
promoted into `data/tech_trends.yaml`, `data/smallcap_universe.yaml`, and
`data/topic_queue.yaml`.

## Designed But Not Scheduled

| Feature | Current state | How to run manually | Reason |
|---|---|---|---|
| On-demand deep dive | Manual plus action-queue driven | `python -m stock.cli deep-dive "<topic>"` | Runs automatically only when `action_queue` has pending items. |
| Daily Chinese activity report | Manual only | `python -m stock.cli daily-zh` | Not scheduled. |
| Morning note | Manual only | `python -m stock.cli morning-note` | Not scheduled. |
| Earnings review | Manual only | `python -m stock.cli earnings-review <TICKER>` | Event-driven by operator. |
| DD checklist | Manual plus weekly company queue | `python -m stock.cli dd-checklist <TICKER>` | One company is scheduled weekly through `company_dd_dive`. |
| WeChat GUI inbox pull | Manual only | `python -m stock.cli pull-feedback` | Scheduled GUI control was removed to avoid laptop takeover behavior. |

## Daily US Macro Regime (2026-06-06)

`stock.macro.generate_macro_digest` produces a daily US macro snapshot (labor,
Fed rate path + cut/hike odds, inflation, rates/liquidity, big-cap cashflow,
market regime, with a "NET REGIME + equity implication" line) via the
web-search-capable core LLM. The `macro_digest` job runs Mon-Fri 01:55 + 13:55
UTC (just before the prediction batches). `macro.format_macro_block` injects the
latest snapshot as SHARED context into EVERY prediction (`{macro_block}` in
prompts/predict.txt) so a single-name read can be overridden by the macro tide
(rate path, liquidity). Persisted as `research_reports(kind='macro')`, synced to
the dashboard feed, and indexed into the knowledge base. Inspect/generate with
`stock macro` / `stock macro --show`.

The knowledge base is now UNIFIED: `KNOWLEDGE_KINDS` includes `macro` and `daily`
notes in addition to the deep-research kinds, so predictions retrieve from one
store covering macro + daily notes + all deep research.

## Market Tape In Predictions (Plan H phase H0, 2026-06-10)

Every prediction prompt now ends with a `市场盘面 / Market tape` block built by
`stock.market_context.build_market_context`:

- **Market internals**: SPY/QQQ/SMH/SOXX/XLK/^VIX/^TNX last close + 1d/5d moves
  from the local prices table. The `ingest_and_extract` job pulls these index
  bars (prices only, no news/LLM) before the watchlist loop.
- **Live quote**: yfinance fast_info at predict time with the gap vs the last
  daily close -- the 14:15 UTC batch runs after the US open but daily bars are
  yesterday's, so the overnight gap was previously invisible.
- **Next earnings date**: yfinance calendar, flagged loudly when it falls
  inside the 1-day prediction horizon.

Live quote + earnings are best-effort: network failures degrade to
"unavailable" lines and never block the prediction.

## Knowledge Base In Predictions

`predict_ticker` injects a per-ticker KNOWLEDGE BASE into the prediction prompt so
the deep research we generate informs the quantitative call (not just the
boss-facing notes). Two retrieval modes, combined in
`stock.knowledge.gather_knowledge`:

- **Direct**: research that names the ticker (`research_reports` of kind deep_dive
  / tech_dive / deep_qa / reply / health_check / discovery_thesis / earnings_review
  / dd_checklist), word-boundary matched (so 'ON' != 'iON'), tagged by kind + date.
- **Semantic (thematic)**: research bodies are embedded into the `knowledge_embeddings`
  vec0 table; at predict time we pull the nearest neighbours of the ticker's current
  news embedding, so a relevant dive that never named the ticker still surfaces
  (e.g. an AI-DC power dive informing a CEG prediction). A cosine-similarity floor
  (`MIN_SEMANTIC_SIMILARITY=0.30`) drops weak matches so unrelated research is not
  injected. Tagged "(thematic)" in the prompt.

The `knowledge_index` job (every 2h, UTC :50) incrementally embeds new research
(local sentence-transformers, $0). Backfill/inspect manually with
`stock knowledge-index` and `stock knowledge <TICKER>`.

## Accuracy-Driven Model Improvement (2026-06-05)

Following a 1-month review (hit rate ~45%, calibration was hurting), five levers
were added so the system improves from its own scoreboard:

- **Calibration guard** (`calibrate.fit_calibration`): the isotonic model is now
  validated on a NEWEST-data holdout and only applied (`helps=1`) when it beats
  raw Brier; otherwise predictions use raw. Refit on live data flipped it from
  hurting to helping (holdout Brier 0.254 -> 0.230).
- **Accuracy-driven grading** (`grading._format_error_patterns`): the grading note
  now sees systematic error breakdowns (hit rate by direction + confidence bucket,
  calibration verdict, recent-vs-prior trend), and the prompt requires each
  improvement hypothesis to target a specific measured weakness.
- **Knowledge instrumentation**: predictions record `knowledge_item_count` (direct
  + thematic) in `feature_context_json` so the knowledge base's impact on hit rate
  is measurable (with vs without research present).
- **Conviction nudge**: the predict prompt tells the model to commit (move prob_up
  off 0.50) when evidence is clear, instead of hedging everything to ~0.50.
- **Boss-suggestion auto-development** (`_auto_track_boss_tickers`): any ticker the
  boss names in chat is added to the watchlist (idempotent, capped), so a
  suggestion enters the predict -> score -> learn loop and gets graded over time.

## Auto-Improvement Reality

`模型改进方向 / Model Improvement Directions` is now part of the automatic loop:

1. `grade_and_reply` scores recent predictions.
2. If scored outcomes exist, it generates a grading note.
3. The grading note's Model Improvement section is extracted.
4. That section is sent to `prompt_rewriter.propose_rewrite_from_text()`.
5. Rewrites are auto-approved for grading-driven improvements when they pass
   the allowlisted target, byte-exact `before` match, and diff-size cap. The
   per-file rate limit is bypassed for this path.
6. Unsafe or mismatched rewrites are staged in `prompt_rewrites` with
   `applied=0` for review.
7. Aggressive fallback: if no rewrite applies, the Model Improvement section is
   appended to `data/rules/current.md` under a dated grading-derived heading so
   the next prediction prompt sees it anyway.
8. If the auto-improve path raises unexpectedly, it logs the failure and sends a
   best-effort email alert to `DAILY_REPORT_EMAIL_TO`.

## Email Configuration

Daily action emails and automation failure alerts use SMTP:

```env
DAILY_REPORT_EMAIL_TO=2001liqiyangdaily@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=2001liqiyangdaily@gmail.com
SMTP_PASSWORD=your_gmail_app_password
SMTP_FROM=2001liqiyangdaily@gmail.com
SMTP_STARTTLS=true
```

If SMTP is not configured, the scheduler logs that email was skipped and keeps
running.

If there are no scored predictions, no model-improvement note is generated and
no rewrite is attempted.

## Quick Verification Commands

```powershell
# Show the scheduler truth from code
@'
from stock.orchestrator import create_scheduler
s = create_scheduler()
for job in s.get_jobs():
    print(job.id, job.trigger)
print("TOTAL", len(s.get_jobs()))
'@ | python -

# Check pending/actioned follow-ups
python -m stock.cli action-queue list

# Force deep-dive queue drain
python -m stock.cli action-queue run --max-items 4

# Force scheduled-style scans manually
python -m stock.cli uoa-scan
python -m stock.cli smallcap-scan
python -m stock.cli entry-scan
python -m stock.cli weekly-qa-dive
```

## What To Check When Something Seems Dormant

| Symptom | First check |
|---|---|
| No deep dives appeared | `stock action-queue list`; if empty, no queued topic existed. |
| Weekly QA did not appear | Confirm it is Saturday after 07:00 UTC and `discovery_candidates` has top candidates. |
| Weekly tech dive did not appear | Confirm it is Sunday after 04:30 UTC and `data/topic_queue.yaml` has enabled topics for the rotated sector. |
| Company DD did not appear | Confirm Wednesday after 09:15 UTC and enabled rows in `data/company_dive_queue.yaml`. |
| Model improvements did not apply | Check `research_reports(kind='grading')`, then `prompt_rewrites` for staged unapplied rewrites. |
| Daily review lacks trade/action suggestions | Expected: `daily_review` is operational health, not trade instructions. Use the weekday `daily_action_email`, `research`, `entry-scan`, or `morning-note`. |
