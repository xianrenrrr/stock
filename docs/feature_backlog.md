# STOCK — feature backlog

Each feature is an atomic unit the pipeline implements end-to-end (planner → creator → validator → screener → writer). Keep features small enough to complete in a single pipeline run.

Statuses: `TODO` · `IN_PROGRESS` · `DONE` · `BLOCKED`

---

## F00 — Project scaffold
**Status**: DONE

**Description**: Create the baseline project skeleton so all later features have somewhere to land. No business logic yet.

**Key files**:
- `pyproject.toml` (new) — Python 3.12, deps listed in `docs/requirements.md`.
- `.env.example` (new) — `ANTHROPIC_API_KEY=`, `MINIMAX_API_KEY=`, `STOCK_API_TOKEN=` (random token for FastAPI auth), `DAILY_COST_CEILING_USD=0.50`.
- `.gitignore` (new) — Python + `.env` + `data/stock.db` + `.venv/`.
- `src/stock/__init__.py` (new) — empty, just the package marker.
- `src/stock/config.py` (new) — `Settings` pydantic model loading from env.
- `src/stock/db.py` (new) — `get_conn()`, schema creation, migration helper. Implement all tables from `design.md` §7 but don't insert seed data yet.
- `data/watchlist.yaml` (new) — empty list with a comment explaining format.
- `tests/test_config.py` (new) — verifies Settings load from env correctly.
- `tests/test_db.py` (new) — verifies schema creation on `:memory:`.

**Acceptance criteria**:
- `python -m pytest` passes.
- `python -m mypy --strict src/stock` passes.
- `python -m ruff check src/stock` passes.
- `python -c "from stock.db import get_conn; get_conn(':memory:')"` creates all tables without error.

---

## F01 — Ingestion (news + prices)
**Status**: DONE
**Depends on**: F00

**Description**: Pull news and prices on demand and write to SQLite. No LLM yet — just data plumbing and dedup.

**Key files**:
- `src/stock/ingest/__init__.py` (new) — exports `fetch_news`, `fetch_prices`.
- `src/stock/ingest/news_rss.py` (new) — parse RSS feeds from a configurable list (Yahoo Finance per ticker, MarketWatch top stories, CNBC, SEC EDGAR filings).
- `src/stock/ingest/news_yahoo.py` (new) — use `yfinance.Ticker(sym).news`.
- `src/stock/ingest/prices.py` (new) — daily OHLCV via `yfinance.download`.
- `src/stock/cli.py` (new or append) — `stock ingest news` and `stock ingest prices` typer commands.
- `data/feeds.yaml` (new) — list of RSS URLs.
- `tests/test_ingest_news.py` (new) — mock RSS fixture, verify dedup by URL hash.
- `tests/test_ingest_prices.py` (new) — mock yfinance response, verify table writes.

**Acceptance criteria**:
- `stock ingest news --ticker AAPL --dry-run` prints at least 1 item (given live network — validator can skip).
- Duplicate URLs are not inserted twice.
- All tests pass; mypy + ruff clean.

---

## F02 — Single-shot predictor (no memory, no rules)
**Status**: DONE
**Depends on**: F01

**Description**: Given a ticker, build the predict prompt from current features + recent prices, call MiniMax, parse JSON, store to `predictions`. Establish the `stock.models` client layer.

**Key files**:
- `src/stock/models.py` (new) — `get_client(provider)` returning a thin wrapper with `.chat(messages, model, max_tokens, cached_system=...)`. Supports `"minimax"` and `"claude"`. Enforces cost-ceiling check.
- `src/stock/features.py` (new) — per-news-item feature extraction via MiniMax. Stores to `features` table.
- `src/stock/predict.py` (new) — `predict_ticker(ticker)` orchestrates features + price history + prompt + LLM call + parse + insert.
- `prompts/feature.txt` (new) — feature extraction prompt.
- `prompts/predict.txt` (new) — prediction prompt. No rules or retrieved cases yet (leave placeholder sections for F04/F06).
- `src/stock/cli.py` (append) — `stock predict <ticker>`.
- `tests/test_features.py`, `tests/test_predict.py` (new) — mock the LLM, verify parsing + DB writes + cost ceiling enforcement.

**Acceptance criteria**:
- `stock predict AAPL` inserts a row into `predictions` with a parsed JSON block.
- Cost ceiling blocks the call when exceeded (unit-tested).
- Tests pass; mypy + ruff clean.

---

## F03 — Score + daily report
**Status**: DONE
**Depends on**: F02

**Description**: For every prediction whose `due_at` has passed, compute the realized return vs expected; write `outcomes`. CLI command prints a summary.

**Key files**:
- `src/stock/score.py` (new) — `score_due()` function.
- `src/stock/cli.py` (append) — `stock score`, `stock report [--days N]`.
- `tests/test_score.py` (new).

**Acceptance criteria**:
- `stock score` processes all due predictions exactly once (idempotent on rerun).
- `stock report --days 7` prints hit rate, mean Brier, best / worst call.
- Tests pass; mypy + ruff clean.

---

## F04 — Memory (embed + retrieve)
**Status**: DONE
**Depends on**: F03

**Description**: Embed each (news, prediction, outcome) tuple and make retrieval available to future predict calls. Update the predict prompt to include retrieved cases.

**Key files**:
- `src/stock/memory.py` (new) — `embed(text)`, `retrieve(ticker, query_embedding, k=5)`, `index_outcome(prediction_id)`.
- `src/stock/db.py` (append) — ensure sqlite-vec loaded; add `news.embedding` column if not present.
- `src/stock/predict.py` (modify) — inject retrieved cases into the prompt context.
- `prompts/predict.txt` (modify) — add `{retrieved_cases}` placeholder.
- `tests/test_memory.py` (new).

**Acceptance criteria**:
- Retrieval returns k cases for a known ticker given a fake embedding.
- `stock predict AAPL` now includes retrieved cases in the stored `feature_context_json`.
- Tests pass; mypy + ruff clean.

---

## F05 — Bandit + calibration
**Status**: DONE
**Depends on**: F03 (can run in parallel with F04, but assume F04 landed first)

**Description**: Thompson-sampling bandit picks which `(model, prompt_variant)` arm runs per ticker. Local sklearn calibration regressor maps raw `prob_up` to calibrated probability.

**Key files**:
- `src/stock/bandit.py` (new) — Thompson sampling over `bandit_state` rows.
- `src/stock/calibrate.py` (new) — sklearn `IsotonicRegression`, fit on last N=500 scored predictions.
- `src/stock/predict.py` (modify) — consult bandit for strategy, apply calibration to output.
- `src/stock/learn.py` (new) — `update_bandit(outcome)`, `refit_calibration()`; called from `score.py`.
- `src/stock/score.py` (modify) — call `learn.update_bandit` after each outcome; refit calibration end-of-day.
- `tests/test_bandit.py`, `tests/test_calibrate.py` (new).

**Acceptance criteria**:
- Simulated outcomes shift bandit arm selection probabilities visibly.
- Calibration reduces Brier score on synthetic miscalibrated data.
- Tests pass; mypy + ruff clean.

---

## F06 — Weekly reflection (rules)
**Status**: DONE
**Depends on**: F03

**Description**: Weekly job reads last 7 days of predictions + outcomes + current rules, asks LLM (Claude Opus if balance ≥ $1, else MiniMax-M2.5) to produce a new rules document. Write `rules/vNNN.md`, update `current.md`, insert into `rules` table.

**Key files**:
- `src/stock/learn.py` (append) — `reflect_weekly()`.
- `prompts/reflect.txt` (new).
- `data/rules/v001.md` (new) — seed rules (brief placeholder).
- `data/rules/current.md` (new) — copy of v001.
- `src/stock/cli.py` (append) — `stock reflect`.
- `tests/test_reflect.py` (new).

**Acceptance criteria**:
- `stock reflect --dry-run` prints a proposed rules doc without writing.
- `stock reflect` writes a new version and bumps `current.md`.
- Tests pass; mypy + ruff clean.

---

## F07 — Orchestrator + scheduled task
**Status**: DONE
**Depends on**: F06

**Description**: Main loop using `apscheduler`: news + features every 15 min during market hours, predictions every 60 min, score end-of-day, reflect weekly. Install as a Windows Startup item like the OpenClaw Gateway.

**Key files**:
- `src/stock/orchestrator.py` (new).
- `src/stock/cli.py` (append) — `stock serve` runs the orchestrator in the foreground.
- `scripts/install_service.ps1` (new) — creates a Startup folder shortcut that runs `stock serve`.
- `tests/test_orchestrator.py` (new) — uses `apscheduler` BlockingScheduler in a mocked time setup.

**Acceptance criteria**:
- `stock serve` runs indefinitely without crashing on a 60-second smoke test.
- Schedule reports next-run times for each job.
- Tests pass; mypy + ruff clean.

---

## F08 — FastAPI + OpenClaw skill
**Status**: DONE
**Depends on**: F07

**Description**: HTTP API on `127.0.0.1:18790` for the OpenClaw agent to call. Skill file describes the tools. Include the required `STOCK_API_TOKEN` auth.

**Key files**:
- `src/stock/api.py` (new) — endpoints: `GET /stock/predict/{ticker}`, `POST /stock/on_demand`, `GET /stock/report`, `GET /stock/rules`, `GET /stock/watchlist`, `POST /stock/watchlist`.
- `openclaw_skill/stock.skill.md` (new).
- `scripts/install_skill.ps1` (new) — copies `stock.skill.md` into `~/.openclaw/agents/main/agent/skills/`.
- `tests/test_api.py` (new) — uses FastAPI TestClient, verifies auth + happy path.

**Acceptance criteria**:
- `curl -H "Authorization: Bearer $STOCK_API_TOKEN" http://127.0.0.1:18790/stock/predict/AAPL` returns a JSON prediction.
- Missing/wrong token returns 401.
- Skill file registered in OpenClaw and visible via `openclaw agents list` tooling.
- Tests pass; mypy + ruff clean.

---

## Backfilled 2026-05-08 -- F09-F44 shipped outside the 5-agent pipeline

The features below were built directly via Claude Code interactive sessions (not via `./development.sh`). Each is in production -- see `WORKFLOW.md` for the runtime view, `code_structure.md` for the module map. Briefer entries than F00-F08 because the implementation has already shipped; this is a ledger.

## F09 -- Web search + autonomous discovery
**Status**: DONE
LLM-driven web search + page extraction; 2x/day. Files: `src/stock/discover.py`, `src/stock/webfetch.py`, `src/stock/websearch.py`, `prompts/discover_extract.txt`.

## F10 -- (skipped, conflated into F09)
**Status**: DONE

## F11 -- Action queue + auto follow-ups
**Status**: DONE
Daily research note auto-queues 2-4 deep-dive topics into action_queue table. Files: `src/stock/action_queue.py`, `tests/test_action_queue.py`.

## F12 -- Daily price/volume anomaly flagger
**Status**: DONE
Rolling pct_change + volume_ratio per ticker; flags >2 sigma into price_anomalies. Cron 16:00 UTC. Files: `src/stock/anomaly.py`, `tests/test_anomaly.py`.

## F13 -- Self-rewriting prompts (boss feedback loop)
**Status**: DONE
Boss reply triggers intent classifier; prompt_rewriter proposes diff in prompt_rewrites for review. Files: `src/stock/intent.py`, `src/stock/prompt_rewriter.py`, `prompts/rewrite_prompt.txt`.

## F14, F15, F17 -- (slots reserved, not used)
**Status**: DONE

## F16 -- Atomic-claim thesis verification
**Status**: DONE
Decompose prediction rationale into claims; verify against post-window news 48h later. Files: `src/stock/thesis.py`, `prompts/thesis_extract.txt`, `prompts/thesis_verify.txt`.

## F18 -- Image upload + vision pipeline
**Status**: DONE
APK uploads via `/upload_image`; vision LLM extracts text/charts. Files: `src/stock/api.py` upload route, `prompts/vision_extract.txt`.

## F19 -- Forward-discovery FWP composite
**Status**: DONE
Daily 23:00 UTC composite: insider cluster + 8-K novelty + reddit accel + theme velocity + supply-chain proximity. QAP gate filter. Files: `src/stock/discovery_engine.py`, `tests/test_discovery_engine.py`.

## F20-F23 -- (slots reserved, not used)
**Status**: DONE

## F24 -- Stop-loss + entry-zone helper
**Status**: DONE
ATR(20) + 30d swing-low + -15% percent stop. Plus pullback entry-zone tool (MA20 + swing-low + ATR levels). Files: `src/stock/stops.py`, `tests/test_stops.py`.

## F25 -- Secular themes (5-10y)
**Status**: DONE
5 long-horizon themes with beneficiaries + losers + leading indicators. Day-rotated into research note. Files: `src/stock/secular.py`, `data/secular_themes.yaml`.

## F26 -- Tracked event predictions
**Status**: DONE
Named catalyst events with windows; nightly verification, calibration summary feeds back into prompts. Files: `src/stock/events.py`, `prompts/event_verify.txt`.

## F27 -- Holdings risk dashboard
**Status**: DONE
Holdings table with cost / last / P&L / stop / distance / 7d alerts / 14d anomalies. Files: `src/stock/holdings.py` (modified).

## F28 -- Sell-trigger keyword alerts
**Status**: DONE
8 keyword categories scan news for active holdings; fires kind=alert research_reports row. Files: `src/stock/alerts.py`.

## F29 -- Wide ingest universe
**Status**: DONE
Ingest cron uses watchlist + holdings + secular tickers (~70 names); LLM feature extraction stays narrow. Files: `src/stock/orchestrator.py` `_get_ingest_universe`.

## F30 -- `stock check <ticker>` CLI
**Status**: DONE
9-section ad-hoc snapshot. Files: `src/stock/cli.py` `check_cmd`.

## F31 -- Prompt-format placeholder validation tests
**Status**: DONE
AST test ensures every {placeholder} in `prompts/research.txt` matches a `format()` kwarg. Files: `tests/test_prompt_format.py`.

## F32 -- Mechanical stop-breach alert
**Status**: DONE
scan_holdings_for_stop_breach: cost-anchored + recommended-stop fallback. Files: `src/stock/alerts.py` `scan_holdings_for_stop_breach`.

## F33 -- Nightly SQLite online backup
**Status**: DONE
23:30 UTC backup via sqlite3.Connection.backup(); retains 7 daily copies. Files: `src/stock/backup.py`, `tests/test_backup.py`.

## F34 -- `stock summary` CLI
**Status**: DONE
Morning view of holdings + watchlist + alerts + anomalies + UOA + AI loop + recent dives. Files: `src/stock/cli.py` `summary_cmd`.

## F35 -- EDGAR Form 4 XML body parser
**Status**: DONE
ATOM gives metadata only; this scrapes accession index.htm for the .xml URL, parses transactionCode/Shares/Price/Role into insider_filings. Files: `src/stock/ingest/insiders.py`.

## F36 -- Unusual options activity scanner
**Status**: DONE
yfinance options chain → flag strikes within 12% of spot, vol/OI >= 5, volume >= 1000. Cron 21:55 UTC. Files: `src/stock/options.py`, `tests/test_options.py`.

## F37 -- Q&A deep-dive engine
**Status**: DONE
5-round Q&A on a ticker; final round forces invalidation. CLI: `stock qa-dive <ticker>`. Files: `src/stock/qa_deepdive.py`, `tests/test_qa_deepdive.py`.

## F38 -- Three-sector smallcap forward scanner
**Status**: DONE
33 curated names. Composite: 40% mkt cap + 40% revenue inflection + 20% news sparsity. Cron 22:15 UTC. Files: `src/stock/smallcap_scanner.py`, `data/smallcap_universe.yaml`.

## F39 -- AI commercial-loop monitor
**Status**: DONE
15-co panel of AI-using SaaS; weekly Mon 06:30 UTC measures QoQ decel + GM compression. Files: `src/stock/ai_loop_monitor.py`, `tests/test_ai_loop_monitor.py`.

## F40 -- Weekly autonomous Q&A on top-FWP
**Status**: DONE
Sat 07:00 UTC fires F37 qa-dive on top-5 FWP candidates. Files: `src/stock/orchestrator.py` `_job_weekly_qa_dive`.

## F41 -- Tech trend atlas
**Status**: DONE
13 specific tech trends (10 enabled) with horizon + why_now + falsification + vehicles. Day-rotated into research note. Files: `src/stock/tech_trends.py`, `data/tech_trends.yaml`.

## F42 -- Conviction watchlist
**Status**: DONE
25+ deeply-tracked names linked to tech_trends. CLI: stock conviction list/toggle/swap/add/remove. Files: `src/stock/tech_trends.py`, `data/conviction_watchlist.yaml`.

## F43 -- 4-round structured tech-dive engine
**Status**: DONE (cron disabled 2026-05-07 after 10 topics covered)
4-round dive on a topic. Files: `src/stock/tech_dive.py`, `data/topic_queue.yaml`.

## F44 -- Equity-research analyst skills + per-company DD
**Status**: DONE
earnings_review (3-round), dd_checklist (1-shot 12-item, **appends to `pipeline/dd/<TICKER>.md`**), morning_note. Slash commands + CLI. Company DD cron weekly Wed 09:15 UTC (was 5x/day, changed 2026-05-08). Files: `src/stock/analyst_skills.py`, `data/company_dive_queue.yaml`, `~/.claude/commands/{earnings,dd-checklist,morning-note}.md`.

---

_The 5-agent pipeline (`./development.sh`) is still available for new TODO features. To use it, add a TODO entry above this backfill section with full plan/criteria/key-files like F00-F08, and the script will pick it up automatically._
