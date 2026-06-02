# STOCK Orchestrator — Complete Logic Overview

Audience: the project owner ("boss"), morning read.
Source of truth: written directly from the code in `src/stock/orchestrator.py`
(`create_scheduler()` plus every `_job_*` function) and the modules each job
calls. Where this conflicts with older design docs, **the code wins**. This
document describes what actually runs.

Not financial advice.

---

## 1. Overview & Operating Modes

The orchestrator is a single long-running Python process built on
**APScheduler** (`BlockingScheduler`, timezone fixed to **UTC**). It owns every
automated job in the pipeline: ingest, predict, research, score, grade,
discovery, alerts, backups, delivery sync. It is started by `run_orchestrator()`,
which configures logging (`pipeline/logs/orchestrator.log`, daily rotation, 14
days kept, also streamed to stderr), syncs holdings from YAML, logs the active
watchlist, builds the scheduler, and blocks until Ctrl+C.

The behavior is gated by the `STOCK_MODE` setting:

| Mode | Setting | Behavior |
|---|---|---|
| **Local full pipeline** | `STOCK_MODE=local` (default) | `create_scheduler()` registers **all** jobs below. The laptop runs the entire pipeline: LLM calls, scoring, research, alerts, email, plus the 5-min push/pull sync to the Render proxy. This is the real brain. |
| **Render cloud proxy** | `STOCK_MODE=cloud_proxy` | `create_scheduler()` returns an **empty scheduler** (a no-op). Render only serves the FastAPI `/channel/*` (boss app/dashboard) and `/sync/*` (laptop↔Render bridge) endpoints. It runs no jobs and makes no LLM calls. |

The split exists so the always-on, $0/month Render free tier holds the
boss-facing dashboard, while the laptop (which has the API keys, Codex/Claude
logins, and yfinance access) does all the work and pushes results up every 5
minutes. That same 5-min push doubles as a keepalive so the free instance never
cold-sleeps.

**Narrow vs wide universe.** Two ticker sets matter:
- **Watchlist / predict universe** (`_get_active_tickers`) — the `watchlist`
  table (`active=1`), falling back to `data/watchlist.yaml`. This is the
  LLM-priced universe: one prediction call per ticker. Stays AI-supply-chain
  focused.
- **Ingest universe** (`_get_ingest_universe`) — watchlist **+** active holdings
  **+** F25 secular-theme tickers. Used for price/news ingest so every ticker the
  research note might mention has fresh data, without burning LLM cost on
  feature extraction for the non-watchlist names.

---

## 2. Complete Scheduled-Job Table

All times **UTC**. "Mon-Fri" = US trading week. In local mode there are ~32
registered jobs. Most LLM-touching jobs are wrapped with `CostCeilingError`
handling and per-item exception isolation so one failure doesn't crash the tick.

| Job id | Cadence (UTC) | What it does | Reads | Writes | Prerequisites |
|---|---|---|---|---|---|
| `ingest_and_extract` | Mon-Fri 02:00, 14:00 | For the **wide** universe: pull Yahoo/RSS news (`fetch_news`) + daily OHLCV bars (`fetch_prices`); extract LLM features **only** for watchlist tickers; then scan active holdings for news sell-triggers + stop-breach + intraday moves (`alerts.scan_all_holdings`). | `watchlist`, `holdings`, secular list, `news`, `prices` | `news`, `prices`, `features`, `research_reports(kind='alert')`, `cloud_sync_state` | Network for Yahoo/RSS/yfinance; utility LLM for features |
| `run_predictions` | Mon-Fri 02:15, 14:15 | One prediction per watchlist ticker via `predict_ticker` (core LLM, calibration, guardrails, thesis extraction). | `watchlist`, `features`, `prices`, `rules`, memory | `predictions`, `prediction_theses`, `llm_calls` | Fresh features+prices from ingest; core backend reachable |
| `web_discovery_morning` | Mon-Fri 02:00 | Web search (Tavily/Serper/Brave) + page fetch + LLM extraction of mentions/themes. Feeds the morning push. | search APIs, web | `web_research`, `data/emerging_fields.yaml` | One of `TAVILY_API_KEY`/`SERPER`/`BRAVE` set |
| `web_discovery_evening` | Mon-Fri 14:00 | Same as above, before the evening push. | search APIs, web | `web_research` | Search key set |
| `research_push_morning` | Mon-Fri 02:30 | Generate the daily multi-field AI-supply-chain research note (`generate_daily_research`). Retries on network errors (30/90/180s). | ~20 context blocks (see §3) | `research_reports(kind='daily')`, `action_queue`, `tracked_events`, `llm_calls` | Predictions/news/discovery in place; core backend |
| `research_push_evening` | Mon-Fri 14:30 | Same generator, evening session label. | same | `research_reports(kind='daily')` | same |
| `daily_action_email` | Mon-Fri 14:45 | Email the latest `kind='daily'` note to the boss, prepending the warning dashboard and appending an upload/feedback link. | `research_reports`, warning dashboard, `recipient_tokens` | SMTP email | SMTP configured; a daily note exists |
| `learn_from_feedback` | every 5 min | Process new boss replies: record inbound, classify intent, answer questions, queue instructions, and fire the prompt-rewriter on instruction turns. | `wechat_feedback.md`, `conversations` | `conversations`, `research_reports(kind='reply')`, `action_queue`, `prompt_rewrites` | New inbound entries present |
| `sync_to_render` | every 5 min | Push recent notes + recipient tokens to Render, pull boss replies typed in the dashboard, run F13 inline on them. Keepalive. No-op if `RENDER_SYNC_URL` unset. | `research_reports`, `recipient_tokens`, `cloud_sync_state` | Render-side tables, `wechat_feedback.md`, `cloud_sync_state` | `RENDER_SYNC_URL` + `STOCK_API_TOKEN` set |
| `warning_dashboard_publish` | every 15 min | Build the risk dashboard; if its content **changed** (sha256 digest), persist a note and email if any high-severity items. | `holdings`, `prices`, `price_anomalies`, `ai_loop_health`, `option_*`, alerts | `research_reports(kind='warning_dashboard')`, `cloud_sync_state`, SMTP (high only) | — |
| `broker_snapshot_import` | every 5 min | Import filled Robinhood positions from `data/robinhood_positions_snapshot.json` into holdings; deactivate broker rows that disappeared. Quiet no-op if file missing. | snapshot JSON, `holdings` | `holdings` | Codex/RH MCP session wrote the snapshot |
| `intraday_holding_move_alerts` | Mon-Fri every 15 min, 13:00–20:59 | Live yfinance quote crash/spike scan for active holdings (drop ≤ −8% or spike ≥ +12%). Severity-bucket dedup. | `holdings`, yfinance live quotes | `research_reports(kind='alert')`, `cloud_sync_state` | Active holdings; yfinance reachable |
| `post_close_snapshot` | Mon-Fri 20:05 | Subprocess `scripts/post_close_snapshot.py`: re-fetch the FINAL settled daily bar (4:05 PM ET) and flag conviction-list volume spikes (≥2×) / quiets (≤0.5×). | conviction list, yfinance | `prices`, `research_reports` (per the script) | Script present; yfinance reachable |
| `score_daily` | Mon-Fri 21:30 | Score every due, unscored prediction (`score_due`): entry/exit close lookup → actual return → direction hit → Brier; update memory index, bandit, calibration. | `predictions`, `prices` | `outcomes`, bandit/calibration state | Entry + exit price bars exist for the prediction |
| `anomaly_compute` | Mon-Fri 21:35 | Recompute daily price/volume anomalies. | `prices` | `price_anomalies` | Fresh prices |
| `thesis_verify` | Mon-Fri 21:40 | Verify up to 30 due theses whose prediction is now scored, against post-window news. | `prediction_theses`, `news` | `prediction_theses` verdicts, `llm_calls` | Scored predictions with theses |
| `grade_and_reply` | Mon-Fri 21:45 | Refresh prices → score → pull recent outcomes → LLM grading note → queue follow-ups → **auto-apply model improvements** (see §6). | `predictions`, `outcomes`, `prediction_theses`, `rules` | `research_reports(kind='grading')`, `action_queue`, `prompt_rewrites`, `data/rules/current.md`, SMTP on failure | Scored outcomes in the lookback window |
| `verify_tracked_events` | Mon-Fri 21:50 | Verify up to 30 pending tracked catalyst events against post-window news. | `tracked_events`, `news` | `tracked_events` statuses, `llm_calls` | Pending events due |
| `uoa_scan` | Mon-Fri 21:55 | Scan watchlist + holdings + FUTU + TIGR for unusual options activity and call/put ratios; extreme hit on a holding fires an alert. | yfinance option chains | `option_anomalies`, `option_ratio_snapshots`, `research_reports(kind='alert')` | yfinance option data |
| `smallcap_scan` | Mon-Fri 22:15 | Score the curated 3-sector small-cap universe (market cap + revenue trajectory); persist rows ≥ `MIN_SCORE_TO_PERSIST`. | `data/smallcap_universe.yaml`, yfinance | `smallcap_candidates` | yfinance reachable |
| `discovery_engine` | Mon-Fri 23:00 | Forward-looking candidate scoring (FWP) over the discovery universe; auto-promote top names (FWP ≥ 0.65, QAP gate, ≤3/run) onto the watchlist and write a discovery thesis. | watchlist, holdings, `news`, supply-chain map, ApeWisdom | `discovery_candidates`, `watchlist`, `research_reports(kind='discovery_thesis')` | Fresh news/insider tables; leading-signal data |
| `backup_db` | daily 23:30 | SQLite online backup to `data/backups/stock.db.<date>.bak`; retains recent snapshots. | live DB | `data/backups/` | DB file present |
| `action_queue_runner` | daily 00:00, 12:00 | Drain up to 4 pending follow-up topics into deep-dive notes (90 min before each push). | `action_queue` | `research_reports(kind='deep_dive')`, `action_queue` status | Pending queued items |
| `daily_self_review` | daily 06:00 | Compile the operational self-review packet `pipeline/daily_review_YYYY-MM-DD.md` and route to the configured backend (Codex/Claude CLI or off). | `llm_calls`, `predictions`, `outcomes`, `conversations`, `action_queue`, `prompt_rewrites`, grading | `pipeline/daily_review_*.md`, optional code proposals | — |
| `reflect_weekly` | Sat 06:00 | Weekly prediction-rules reflection (`reflect_weekly`). | `predictions`, `outcomes` | `data/rules/vNNN.md`, `data/rules/current.md`, `rules` table | Enough scored history |
| `health_check_weekly` | Sat 07:00 | Per-holding health-check deep dive (anomalies + Form 4 + news + chain). | `holdings`, `price_anomalies`, `insider_filings`, `news` | `research_reports(kind='health_check')` | Active holdings |
| `weekly_qa_dive` | Sat 07:00 | Q&A deep dive on the top-5 FWP discovery candidates, 5 rounds each. | `discovery_candidates` | `research_reports(kind='deep_qa')` | Candidates exist |
| `weekly_tech_dive` | Sun 04:30 | F43 sector-rotated 5-round tech-trend dive with Chokepoint scoring (see §4). | `data/topic_queue.yaml` | `research_reports(kind='tech_dive')`, `tech_dive_runs` | Enabled topics in the rotated sector |
| `insiders_pull` | Sun 05:00 | Pull SEC EDGAR Form 4 filings for holdings + watchlist. | EDGAR | `insider_filings` | EDGAR reachable |
| `weekly_entry_scan` | Sun 06:00 | Pullback entry-zone scan over conviction + DD-queue names (pure price math, no LLM). | `prices` | `research_reports(kind='entry_signals')` | Price history |
| `ai_loop_measure` | Mon 06:30 | Measure the AI commercial-loop closure-risk panel (quarterly financials). | yfinance income statements | `ai_loop_health` | yfinance reachable |
| `company_dd_dive` | Wed 09:15 | Run one queue-rotated company DD checklist; appends to `pipeline/dd/<TICKER>.md`. | `data/company_dive_queue.yaml` | `pipeline/dd/<TICKER>.md`, `research_reports` | Enabled companies in queue |

Every LLM call (core, utility, or CLI subprocess) is logged to the **`llm_calls`**
table with model/provider/tokens/cost/duration/caller.

---

## 3. The End-to-End Daily Loop (UTC timeline)

The weekday loop, narrated top to bottom:

| UTC | Stage | What happens |
|---|---|---|
| **02:00** | **Discovery + Ingest** | `web_discovery_morning` searches the web and extracts themes. `ingest_and_extract` pulls news + prices for the wide universe, extracts features for watchlist names, and scans holdings for sell-triggers/stop-breaches/intraday moves. |
| **02:15** | **Predictions** | `run_predictions` runs `predict_ticker` per watchlist name. |
| **02:30** | **Morning research push** | `generate_daily_research` builds the note from ~20 context blocks and persists `kind='daily'`; cloud_sync carries it to the boss app within ~1 min. |
| **12:00** | **Action-queue drain** | `action_queue_runner` turns queued follow-ups into deep dives (also 00:00). |
| **14:00–14:30** | **Evening cycle** | Evening discovery → ingest → predictions → evening research push, mirroring the morning. |
| **14:45** | **Email** | `daily_action_email` mails the latest daily note (warning dashboard prepended). |
| **20:05** | **Post-close snapshot** | Final settled bar refresh + volume spike/quiet flags. |
| **21:30** | **Score** | `score_due` grades every due prediction; updates bandit + calibration. |
| **21:35** | **Anomaly** | Recompute price/volume anomalies. |
| **21:40** | **Thesis verify** | Grade theses of freshly-scored predictions vs post-window news. |
| **21:45** | **Grade + auto-improve** | Grading note; follow-ups queued; model-improvement loop fires (§6). |
| **21:50** | **Events** | Verify pending tracked catalyst events. |
| **21:55** | **Options** | UOA + call/put ratio scan; extreme holding hits alert. |
| **22:15** | **Smallcap** | Score small-cap universe. |
| **23:00** | **Discovery engine** | FWP scoring + auto-promote + discovery theses. |
| **23:30** | **Backup** | Nightly SQLite online backup. |
| **06:00 (next)** | **Self-review** | Operational packet compiled and routed. |

Two continuous loops run underneath this: `learn_from_feedback`, `sync_to_render`,
and `broker_snapshot_import` every 5 minutes; `warning_dashboard_publish` every 15
minutes; `intraday_holding_move_alerts` every 15 minutes during the cash session.

### What goes into the daily research note

`generate_daily_research` (in `research.py`) assembles a large prompt from these
blocks before a single core-backend call: focus supply-chain layer (rotated),
watchlist predictions, **forced** broad-watchlist movers (≥5% move or ≥1.5×
volume), featured news, 7-day performance (hit rate / Brier / spend), cross-layer
sample, web-discovery extractions, emerging fields, thesis stats, F19 discovery
candidates, tracked events + calibration, F25 secular theme, **F24 pre-computed
stop-loss table** for every mentioned ticker, UOA + option-ratio blocks, smallcap
candidates, AI-loop monitor, F41 trend radar, **Chokepoint cross-field
leaderboard** (last 21 days of scored tech dives), conviction watchlist, recent
boss feedback, anomalies, previous follow-ups, holdings, and conversation context.
After generation it enforces the `Not financial advice.` disclaimer, persists the
note, then auto-queues follow-up topics and extracts any `[NEW EVENT]` lines into
`tracked_events`.

### How a prediction is made

`predict_ticker`: ensure features → load last 10 price bars + 20 feature rows →
load `data/rules/current.md` into the system prompt → retrieve similar past cases
from the memory vector store → select a strategy arm (Thompson-sampling bandit) →
call the **core backend** → parse JSON, clamp `prob_up`/`confidence`, infer
direction if invalid → apply **deterministic guardrails** (caps stale AI/semis
bullish narratives without a fresh hard catalyst; floors over-bearish calls when
peer breadth is positive) → apply calibration (with a direction-preservation
guard) → insert the `predictions` row → best-effort thesis extraction into
`prediction_theses`.

### How scoring works

`score_due`: for each due, unscored prediction, look up entry close (≤ creation
date) and exit close (≥ due date). Actual return = (exit−entry)/entry; "up" =
return > 0; direction hit if predicted direction matches; Brier =
(clamped prob_up − outcome)². Insert `outcomes`, index into memory, update the
bandit posterior. After any scoring, refit calibration. Idempotent.

---

## 4. Weekly & Periodic Jobs

| Job | When (UTC) | Detail |
|---|---|---|
| **Weekly reflection** | Sat 06:00 | Reviews recent predictions/outcomes and writes a new versioned rules file `data/rules/vNNN.md` + updates `data/rules/current.md`. |
| **Holdings health check** | Sat 07:00 | Per active holding, a deep-dive note injecting recent anomalies, 90-day Form 4 insider activity, ticker news, and supply-chain context. Persisted `kind='health_check'`. |
| **Weekly QA dive** | Sat 07:00 | Top-5 FWP discovery candidates; 5-round Q&A each, seeded with the FWP score + signal components. Cost-ceiling aware. |
| **Weekly tech dive (F43)** | Sun 04:30 | See below — the centerpiece weekly deep dive. |
| **Insiders pull** | Sun 05:00 | EDGAR Form 4 for holdings + watchlist into `insider_filings`. |
| **Entry scan (F45)** | Sun 06:00 | Pure price arithmetic; flags conviction + DD-queue names in their recommended pullback zone. Persisted `kind='entry_signals'`. |
| **AI-loop measure (F39)** | Mon 06:30 | Pulls quarterly income statements across the AI commercial-loop panel; flags simultaneous revenue deceleration + margin compression into `ai_loop_health`. |
| **Company DD (F44)** | Wed 09:15 | Pops the longest-untouched enabled company from `data/company_dive_queue.yaml` (priority, then last-run), runs the DD checklist, appends to `pipeline/dd/<TICKER>.md`. |

### Weekly tech dive — Chokepoint 5-dim scoring, buyer-side `ai_demand`, phase awareness

`_job_daily_tech_dive` rotates sectors by ISO week across
`["information", "biopharma_ai", "energy", "ai_demand", "space_tech"]` (so every
field eventually fires, not just the day-of-week default). It pops the
longest-untouched enabled topic from `data/topic_queue.yaml` for the rotated
sector (falling back through the others), then runs `tech_dive.run_and_persist`.

The dive is **5 sequential rounds** (`tech_dive.py`), each ≤1500 tokens, with the
prior transcript fed forward:
1. **Technology closed loop** — what the tech is, the incumbent it challenges,
   pros/cons with numbers, where it's been validated.
2. **Business closed loop** — revenue flow, unit-economics inflection, demand
   magnitude, customer concentration, time-to-revenue.
3. **Company chain** — ≥3 public companies with tickers across different layers,
   plus critical-path private players.
4. **Falsification + synthesis** — observable falsifiers, before-it-20x vs
   crowded read, cleanest entry.
5. **Chokepoint 5-dim research-priority score.**

The Chokepoint composite is:
`trend·0.25 + bottleneck·0.25 + validation·0.25 + valuation·0.15 − risk·0.15`.

Key mechanics:
- The model must emit a machine-readable `SCORES: trend=N bottleneck=N ...`
  line. The server **re-clamps each dimension to 0–10 and recomputes the
  composite itself** — the LLM's own number is ignored.
- **Buyer-side reinterpretation:** for sector `ai_demand`, the "supply
  bottleneck" dimension is scored as **moat/defensibility** (proprietary data,
  distribution, switching costs, workflow lock-in — can the company *keep* the
  value AI creates?) instead of a physical supply chokepoint.
- **Phase awareness:** the topic's `phase` (`early`/`emerging`/`mature`) flows
  in. Early/emerging fields (space, pre-revenue biopharma) score validation +
  valuation on an **option-value** basis and are flagged HIGH VARIANCE, so
  pre-revenue names aren't penalized like a mature-cap miss.

Persisted to `research_reports(kind='tech_dive')` and `tech_dive_runs` (with
`phase` and `score_*` columns). The daily research note then shows a cross-field
research-priority leaderboard built from the last 21 days of scored dives.

---

## 5. LLM Backend Architecture

All LLM-touching modules route through helpers in `models.py`. There are two
lanes.

### Core lane — Codex-first with a Claude guarantee

`get_core_client()` returns the backend selected by `CORE_LLM_BACKEND`
(default `codex_cli`):

- **`CodexWithClaudeFallback`** (default): tries `codex exec` first (subprocess,
  paid via the user's ChatGPT plan, cost logged as **$0**). On any
  `CodexCliUnavailable` (missing binary, timeout, non-zero exit, **or** a
  detected credit/rate-limit message), it transparently falls back to
  **`ClaudeCliClient`** (`claude -p`, paid via the Claude Code subscription, also
  $0). The Claude default model is `claude-opus-4-7`.
- This is the **always-a-fallback guarantee**: a core call is never left without
  a backstop. Both subprocesses failing propagates the error — MiniMax is
  **never** used as a safety net (it is fully retired; legacy `minimax` settings
  are routed to Codex).
- Used by: research notes, replies, grading, deep dives, tech dives, QA dives,
  discovery theses, prompt rewriter, self-review.

**Circuit breaker (F17c).** Codex credit-limit hits are detected on both
channels (stderr and the response file). After **2 hits within 300s**, the
breaker **opens for 1800s (30 min)**: every core call routes straight to
`claude_cli` for the cooldown, instead of having all (e.g.) 26 watchlist
predictions each hammer a known-capped backend before falling back individually.

Subprocess details: both CLIs are resolved with `shutil.which` (handles
Windows `.CMD`), the prompt is piped via **stdin** (avoids Windows' 32 KB
command-line limit), and on Windows they run with `CREATE_NO_WINDOW` so no
console windows flash. Codex's final message is read from a dedicated `-o`
temp file (stdout is noisy).

### Fast utility lane (new)

`get_utility_client()` / `get_utility_model()` serve **high-frequency cheap
classifiers** — feature extraction and intent classification — where Codex's
reasoning latency (20–50s each) was overkill for small JSON tasks.

- **`FastUtilityClient`**: primary is `claude -p` on a fast model
  (`claude-haiku-4-5-20251001` by default via `UTILITY_CLAUDE_MODEL`). On
  `ClaudeCliUnavailable` it falls back to the **full core backend**
  (`codex → claude`), so a utility call also always has the "claude is always
  behind it" safety net.
- If `UTILITY_CLAUDE_MODEL` is blank, the utility lane simply reuses the core
  backend (reversible switch).
- Used by: `features.extract_single`, `intent.classify`.

### Cost ceiling + logging

Every `chat()` call first runs `check_cost_ceiling`: it sums today's
`llm_calls.cost_usd` since UTC midnight and raises `CostCeilingError` if it meets
or exceeds `DAILY_COST_CEILING_USD`. Subscription-backed CLI calls log
`cost_usd=0` (token counts are estimated at ~4 chars/token for visibility), so
they don't trip the ceiling but stay auditable. Pricing for metered models lives
in `PRICING`. Jobs catch `CostCeilingError` and skip gracefully.

---

## 6. The Self-Improvement Loop

Triggered inside `grade_and_reply` (21:45 UTC) via
`grading.generate_grading_note` → `_auto_apply_model_improvements`:

1. `score_due` grades recent predictions; if there are **no** scored outcomes in
   the window, a minimal note is written and **no rewrite is attempted**.
2. With outcomes present, the LLM grading note is generated (hit rate, Brier,
   confident misses, biggest win/loss, thesis stats) and persisted
   `kind='grading'`.
3. The note's **模型改进方向 / Model Improvement Directions** section is extracted
   by regex.
4. That section is sent to `prompt_rewriter.propose_rewrite_from_text`, which
   asks the core backend for **byte-exact `<patch>`** edits.
5. `apply_rewrite(..., force=True)` applies a patch automatically when it passes:
   target is allow-listed (`prompts/research.txt`, `data/rules/current.md`,
   `prompts/intent_classify.txt`, `prompts/reply.txt`), the `before` text matches
   the file **byte-for-byte**, and the diff-size cap holds. `force=True` bypasses
   the normal 24h-per-file rate limit for grading-driven edits.
6. Unsafe / mismatched / oversized rewrites are **staged** in `prompt_rewrites`
   with `applied=0` for human review (with dedup + a 5-pending-per-target cap).
7. **Aggressive fallback:** if *no* rewrite applied, the improvement section is
   appended verbatim to `data/rules/current.md` under a dated heading, so the
   next prediction prompt sees the lesson regardless.
8. If the whole auto-improve path raises, it logs and sends a best-effort email
   alert to `DAILY_REPORT_EMAIL_TO`.

A separate, conversation-driven rewrite path runs from `learn_from_feedback`:
boss messages classified as `instruction` are summarized and fed to
`prompt_rewriter.propose_rewrite` / `apply_rewrite` (this path **respects** the
24h rate limit). The weekly `reflect_weekly` job is the slower companion that
rewrites the versioned rules file from accumulated outcomes.

---

## 7. Delivery

There is no automatic WeChat/OpenClaw GUI delivery in normal operation
(`OPENCLAW_AUTO_DELIVER=false`). Delivery is three surfaces, all fed from the
`research_reports` table:

- **Boss app / Render sync.** Every note (`daily`, `grading`, `alert`,
  `warning_dashboard`, `tech_dive`, `entry_signals`, `deep_dive`, `reply`, …)
  lands in `research_reports`. `sync_to_render` (every 5 min) pushes recent notes
  + recipient tokens to Render via `POST /sync/notes` / `/sync/tokens`, and pulls
  boss replies typed into the dashboard via `GET /sync/replies` (then runs F13
  inline so a reply note rides the same tick). The APK/dashboard polls
  `/channel/api/notes`. This push is also the keepalive.
- **SMTP email.** `emailer.send_email` is a best-effort plain-text SMTP helper
  (logged no-op if SMTP unset). The weekday `daily_action_email` (14:45) sends
  the latest daily note with the warning dashboard prepended and an upload link
  appended. High-severity warning changes and auto-improve failures also email.
- **Warning dashboard.** `warning_dashboard.build_warning_dashboard` aggregates,
  severity-ranked: active-holding P&L + F24 stop distance, recent `kind='alert'`
  notes, recent price/volume anomalies for holdings, AI-cycle crash risk from
  `ai_loop_health`, AI-production-chain breadth breakdowns from `prices`, bearish
  put/call pressure from `option_ratio_snapshots`, and unusual put activity from
  `option_anomalies`. Every 15 min, if the content digest changed, it's persisted
  `kind='warning_dashboard'` (so it flows to the app via the normal notes
  pipeline) and emailed when high-severity items are present.

---

## 8. Broker / Stop-Loss Reality

Today's stop-loss handling is **monitor-and-warn, not auto-trade**:

- **Compute** — `stops.compute_stop_loss` returns three candidate stops per
  ticker: ATR stop (`entry − 2·ATR(20)`), 30-day swing-low, and a −15% percent
  stop, plus a **recommended** pick (the tightest defensible level, with sanity
  guards). `format_stop_loss_block` injects a real-number stop table into the
  daily research prompt so recommendations cite actual levels, not "set a stop."
  `compute_entry_zone` similarly powers the weekly pullback entry scan.
- **Display** — the warning dashboard shows holding P&L and stop distance; the
  daily note and health checks surface stop tables.
- **Alert on breach** — `alerts.scan_holdings_for_stop_breach` fires a
  `kind='alert'` note when the latest close drops below either the −15%
  cost-anchored stop or the F24 recommended stop (with low-close dedup).
  `scan_holdings_for_intraday_moves` catches large live moves before the daily
  bar settles. `scan_ticker_news_for_triggers` fires on sell-trigger keywords in
  fresh news. All three run via `scan_all_holdings` during ingest.
- **Broker import** — `broker_sync.import_snapshot_file` reads
  `data/robinhood_positions_snapshot.json` (written by a Codex/RH MCP session,
  since the background Python process can't call MCP tools directly) and upserts
  only **non-zero filled** positions into `holdings`; queued orders are ignored
  until filled. This is **read-only**: a file bridge that imports positions, not
  a trading interface.

**Explicitly:** the system does **not** create or edit real broker stop-loss
orders automatically. It computes stops, displays them, and alerts on breach;
actual order placement still requires an explicit confirmed instruction. Auto
stop-loss order placement is being added as a **separate, human-armed** feature.

---

### Quick verification

```powershell
@'
from stock.orchestrator import create_scheduler
s = create_scheduler()
for job in s.get_jobs():
    print(job.id, job.trigger)
print("TOTAL", len(s.get_jobs()))
'@ | python -
```

Not financial advice.
