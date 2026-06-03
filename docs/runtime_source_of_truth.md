# STOCK Runtime Source Of Truth

Last verified: 2026-05-31 from `src/stock/orchestrator.py:create_scheduler()`.

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

## Active Scheduled Jobs

There are 35 active APScheduler jobs in local mode.

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
