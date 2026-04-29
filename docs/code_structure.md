# STOCK — code structure

This file is the living map of what exists in `src/stock/`. Pipeline Writer agents append to this file after each feature. Never delete entries — mark as `[deprecated]` instead.

## Root files
- `pyproject.toml` — package metadata, dependencies (runtime + dev), tool config for ruff/mypy/pytest, `[project.scripts]` entry (`stock = "stock.cli:app"`).
- `.env.example` — template for required env vars (API keys, cost ceiling, API token).
- `.gitignore` — excludes .env, stock.db, caches, build artifacts, .venv.

## src/stock/
- `__init__.py` — package marker with module docstring.
- `config.py` — `Settings` pydantic model (env loading via pydantic-settings) + `get_settings()` cached singleton. Adds F12 `edgar_user_agent` for SEC EDGAR Form 4 requests.
- `db.py` — `get_conn()` connection factory (WAL mode, foreign keys, sqlite-vec extension loading) + `_ensure_schema()` creating all tables. F11 adds `action_queue`. F12 adds `holdings`, `insider_filings`, `price_anomalies`. F13 adds `conversations`, `prompt_rewrites`, plus the `conversation_embeddings` vec0 virtual table.
- `action_queue.py` — F11 follow-up engine: `extract_action_items(body)` regex-extracts bullets under "行动清单" / "Action items" / "AI 自动跟进", `enqueue_actions(conn, source_research_id, raw_items)` dedups + persists, `pending_items()` / `recent_completed()` query helpers, `run_pending(conn, max_items)` drains the queue by calling `generate_deep_dive`, `format_previous_followups(items, conn)` renders for prompt injection. Re-queues on `CostCeilingError`, marks failed otherwise.
- `anomaly.py` — F12 daily price/volume anomaly flagger: `compute_daily_anomalies(conn)` UPSERTs `price_anomalies` rows when `volume_ratio >= 1.5` or `abs(pct_change) >= 0.05`. `recent_anomalies(conn, days)` reads back, `format_anomaly_block(rows)` renders for prompt. Skips illiquid tickers below `MIN_AVG_VOLUME`.
- `holdings.py` — F12 portfolio tracker: `Holding` pydantic, `list_holdings`, `add_holding` (UPSERT), `remove_holding` (active=0), `set_note`, `sync_from_yaml` (reads `data/holdings.yaml`, deactivates missing rows), `format_holdings_block(rows, conn)` joins to `prices` for live P&L%.
- `conversation.py` — F13 two-way conversation memory: `record_inbound`, `record_outbound` (joins same run_id), `set_intent`, `has_entry`, `recent_turns`, `recent_instruction_ids(hours)`, `retrieve_similar(query_embedding, k)` via `conversation_embeddings` vec0 table, `format_context_block(turns)` for the daily prompt. Reuses `stock.memory.embed()`.
- `intent.py` — F13 intent classifier: `classify(text, recipient, conn)` calls cheap MiniMax with `prompts/intent_classify.txt`, returns `IntentResult(intent, confidence, summary, suggested_topic)`. Cost-ceiling and parse failures downgrade to `intent='unknown'` rather than raising.
- `prompt_rewriter.py` — F13 Opus-driven file editor: `propose_rewrite(conversation_ids, conn)` calls Opus (or MiniMax fallback below `OPUS_BUDGET_THRESHOLD`) with `prompts/rewrite_prompt.txt`, parses `<patch>` blocks, returns `RewriteProposal` rows. `apply_rewrite(proposal, conn)` requires byte-exact substring match; rate-limits to one apply per 24h per file; stages mismatched proposals with `applied=0` for human review. `revert_rewrite(rewrite_id, conn)` restores the original byte-exactly.
- `cli.py` — typer CLI: `stock ingest news`, `stock ingest prices`, `stock predict`, `stock reflect`.
- `models.py` — unified LLM client layer: `LLMClient` wrapping OpenAI-compatible (MiniMax) and Anthropic (Claude) APIs, `get_client(provider)` factory, `check_cost_ceiling()` enforcer, `parse_llm_json()` code-fence stripper, per-call logging to `llm_calls`.
- `features.py` — per-news-item feature extraction via MiniMax: `extract_features(ticker)` processes unfeatured news, `extract_single()` calls LLM and stores to `features` table, stops gracefully on cost ceiling.
- `predict.py` — single-ticker prediction cycle: `predict_ticker(ticker, conn)` orchestrates feature extraction, memory retrieval of similar past cases via `embed()`/`retrieve()`, prompt assembly with [SYSTEM]/[USER] split, bandit arm selection via `select_arm()`, LLM call using the bandit-selected provider/model, JSON parsing, validation/clamping, calibration of `prob_up` via `calibrate()`, DB insertion. Loads current rules from `data/rules/current.md` via `_load_current_rules(conn)` and injects into the `{rules}` system prompt placeholder. Stores `strategy_arm`, `prob_up_calibrated`, `rules_version`, and `retrieved_case_ids`. `compute_due_at()` handles weekday/weekend skipping.
- `memory.py` — embedding and retrieval: `embed(text)` via sentence-transformers all-MiniLM-L6-v2, `index_outcome(prediction_id)` stores vectors in sqlite-vec, `retrieve(ticker, embedding, conn, k)` finds similar past cases, `format_retrieved_cases()` renders for prompt.
- `score.py` — outcome scoring and daily report: `score_due(conn)` idempotently scores all due predictions, indexes each outcome into the memory vector store, updates bandit posteriors, and refits calibration. `build_report(conn, days)` aggregates hit rate / Brier / spend, `format_report(report)` renders human-readable CLI output.
- `bandit.py` — Thompson sampling arm selection: `ArmConfig` and `BanditSelection` models, `select_arm(ticker, conn)` picks strategy via Thompson sampling over `bandit_state` rows, `update_arm_posterior()` updates Beta posteriors, `get_ticker_bucket()` maps tickers to bandit buckets.
- `calibrate.py` — probability calibration: `calibrate(raw_prob_up, conn)` applies latest IsotonicRegression model, `fit_calibration(conn)` refits on last 500 scored predictions and stores to `calibration` table.
- `learn.py` — post-outcome learning coordination + weekly reflection: `update_bandit(prediction_id, conn)` reads prediction arm and outcome, updates bandit posteriors; `refit_calibration(conn)` delegates to calibrate.fit_calibration with logging; `reflect_weekly(conn, dry_run)` orchestrates weekly self-reflection — loads recent prediction+outcome pairs, chooses provider (Claude Opus if budget >= $1, else MiniMax), calls LLM with current rules + stats, extracts new rules from `<rules>` tags, writes versioned `data/rules/vNNN.md`, overwrites `current.md`, inserts `rules` table row. Helpers: `_choose_reflect_provider`, `_get_recent_prediction_outcomes`, `_format_prediction_outcomes`, `_format_stats_summary`, `_get_current_rules_text`, `_get_next_version`, `_extract_rules_text`, `_ensure_seed_rules`. Constants: `RULES_DIR`, `REFLECT_PROMPT_PATH`, `OPUS_BUDGET_THRESHOLD`, `OPUS_MODEL`, `REFLECT_MAX_TOKENS`.
- `orchestrator.py` — scheduled job runner: `_get_active_tickers()` loads watchlist, four job functions (`_job_ingest_and_extract`, `_job_run_predictions`, `_job_score_daily`, `_job_reflect_weekly`), `create_scheduler()` configures APScheduler 3.x BlockingScheduler with CronTrigger for each job, `get_schedule_info()` reports next run times, `run_orchestrator()` blocking entry point. Constants: `WATCHLIST_PATH`, `MARKET_HOURS_START`, `MARKET_HOURS_END`, `SCORE_HOUR`, `SCORE_MINUTE`, `REFLECT_DAY`, `REFLECT_HOUR`.
- `api.py` — FastAPI app on 127.0.0.1:18790 exposing OpenClaw skill tools: `health` (`GET /stock/health`, no auth), `get_latest_prediction` (`GET /stock/predict/{ticker}`), `run_on_demand` (`POST /stock/on_demand`), `get_report` (`GET /stock/report`), `get_rules` (`GET /stock/rules`), `get_watchlist` + `post_watchlist` (`GET/POST /stock/watchlist`), `get_calibration` (`GET /stock/calibration`). Bearer-token auth via `_require_token` comparing against `Settings.stock_api_token` using `secrets.compare_digest`. Per-request connection via `get_db_conn` dependency. Exception handlers map `StockHTTPException` → typed response, `CostCeilingError` → 503 with `Retry-After: 3600`, `ValueError` → 400, other `Exception` → 500 (traceback logged, not leaked). Watchlist CRUD helpers: `_watchlist_add`, `_watchlist_remove`, `_load_watchlist`. `_bucket_calibration()` groups (prob_up, direction_hit) pairs into equal-width bins. `run_api()` boots uvicorn. Constants: `API_HOST`, `API_PORT`, `RULES_CURRENT_PATH`, `CALIBRATION_CURVE_BINS`.

## src/stock/ingest/
- `__init__.py` — package entry: `NewsItem`, `PriceBar`, `IngestResult` models + `fetch_news`, `fetch_prices` orchestrators.
- `news_yahoo.py` — `fetch_yahoo_news(ticker)` via yfinance Ticker.news API.
- `news_rss.py` — `fetch_rss_news(ticker, feeds)` via feedparser + BeautifulSoup HTML stripping.
- `prices.py` — `fetch_daily_prices(ticker, days)` via yfinance.download.
- `insiders.py` — F12 SEC EDGAR Form 4 fetcher (free, no key): `lookup_cik(ticker)` with 7-day local cache at `data/.cache/cik_lookup.json`, `fetch_form4(ticker, limit)` parses ATOM feed, `persist_insiders(conn, ticker)` UPSERTs by accession_number, `recent_for_ticker(conn, ticker, days)` reads back, `format_insider_block(rows)`. Uses configurable `edgar_user_agent`.

## tests/
- `__init__.py` — test package marker.
- `conftest.py` — shared fixtures: `mem_db` (in-memory SQLite), `env_settings` (monkeypatched Settings).
- `test_config.py` — 3 tests: env loading, defaults, lru_cache behavior.
- `test_db.py` — 8 tests: all tables exist, idempotent schema, foreign keys, WAL mode, insert/read, composite PK, case_embeddings virtual table existence.
- `test_ingest_news.py` — news ingestion tests with mocked yfinance + feedparser.
- `test_ingest_prices.py` — price ingestion tests with mocked yfinance.download.
- `test_models.py` — 12 tests: client factory, empty API key, chat logging, ChatResponse structure, cost ceiling (exceeded/under/yesterday), parse_llm_json variants.
- `test_features.py` — 11 tests: extract_single (valid/fenced/invalid JSON), extract_features (skip featured, process unfeatured, stop on ceiling), get_unfeatured_news, NewsFeatures model.
- `test_memory.py` — 18 tests: embed dimension/normalize/empty-raises, serialize roundtrip, index_outcome (store/idempotent/missing prediction/missing outcome), retrieve (k cases/ticker filter/empty/fewer than k), format_retrieved_cases (empty/formatted), _extract_feature_text (none/invalid/valid/empty JSON).
- `test_predict.py` — 12 tests: predict_ticker (insert/no prices/no features/code fences/clamp prob_up/cost ceiling) with bandit+calibration mocks, compute_due_at (weekday/friday), prediction row structure, get_recent_prices/features.
- `test_score.py` — 10 tests: score_due (up/down/wrong direction/idempotent/skip no exit price/skip no entry price/zero return) with bandit+calibration mocks, build_report (empty/populated), format_report output.
- `test_bandit.py` — 8 tests: get_ticker_bucket, select_arm (single/multi/creates state), Thompson sampling shift, update_arm_posterior (reward/no reward), _ensure_arm_state idempotent.
- `test_calibrate.py` — 8 tests: calibrate (no model/applies model/clips bounds), fit_calibration (creates version/too few/increments/stores IDs), calibration reduces Brier.
- `test_learn.py` — 6 tests: update_bandit (hit/miss/no arm/missing prediction/missing outcome), refit_calibration delegates.
- `test_reflect.py` — 20 tests: reflect_weekly (writes version/dry run/version increment/no outcomes/cost ceiling/empty response), _choose_reflect_provider (claude/no key/low budget), _extract_rules_text (with tags/without/empty), _format_prediction_outcomes (populated/empty), _format_stats_summary (populated/empty), _ensure_seed_rules (insert/skip), _get_next_version (empty/existing).
- `test_orchestrator.py` — 20 tests: _get_active_tickers (DB/YAML fallback/inactive/empty), _job_ingest_and_extract (all tickers/cost ceiling/single error/empty watchlist), _job_run_predictions (all tickers/cost ceiling/single error/empty), _job_score_daily (success/error), _job_reflect_weekly (success/cost ceiling), create_scheduler (job count/job IDs), get_schedule_info format, run_orchestrator startup.
- `test_api.py` — 27 tests: auth (missing/wrong/unconfigured token, health no-auth), ticker validation (400 on digits), /stock/predict (latest with id tie-break/404/case-norm), /stock/on_demand (success/cost ceiling 503 + Retry-After/value error 400/missing body 422), /stock/report (default days=7/custom ?days=14/out-of-range 422), /stock/rules (reads current.md + DB row/empty when missing), /stock/watchlist (list empty/add inserts/add idempotent/add reactivates inactive/remove sets active=0/remove missing 404/bad action 422/add requires ticker 400), /stock/calibration (empty/buckets sorted with aggregates). Uses cross-thread `:memory:` DB fixture (check_same_thread=False) to accommodate FastAPI's threadpool dispatch.

## prompts/
- `feature.txt` — feature extraction prompt template: extracts sentiment, novelty, catalyst_type, time_sensitivity, summary from a news article as JSON.
- `predict.txt` — prediction prompt with [SYSTEM]/[USER] markers. System section has `{rules}` placeholder (F06). User section has `{ticker}`, `{horizon}`, `{feature_summary}`, `{price_count}`, `{price_history}`, `{retrieved_cases}` (F04).
- `reflect.txt` — weekly reflection prompt with [SYSTEM]/[USER] markers (F06). Placeholders: `{current_rules}`, `{stats_summary}`, `{prediction_outcomes}`. Instructs LLM to produce updated rules enclosed in `<rules>` XML tags.

## data/
- `feeds.yaml` — configurable RSS feed URLs for news ingestion.
- `stock.db` — SQLite database, schema defined in `src/stock/db.py`.
- `rules/vNNN.md` — append-only versioned rules documents produced by weekly reflection.
- `rules/current.md` — copy of the latest `vNNN.md`. Read by every prediction.
- `watchlist.yaml` — tickers to follow (empty list, format documented in file).

## openclaw_skill/
- `stock.skill.md` — skill manifest registering six tools (predict, on_demand, report, rules, watchlist, calibration) for the OpenClaw `main` agent. Installed into `~/.openclaw/agents/main/agent/skills/` via `scripts/install_skill.ps1`. Mandates the `Not financial advice.` disclaimer on user-facing replies.

## scripts/
- `install_service.ps1` — registers `stock serve` as a Windows Startup shortcut (F07).
- `install_skill.ps1` — copies `openclaw_skill/stock.skill.md` into the OpenClaw main agent skills folder; ensures the destination folder exists.

## SQL tables (in stock.db)
All defined in `src/stock/db.py` via `CREATE TABLE IF NOT EXISTS`:
- `news` — ingested news articles with optional embedding blob.
- `prices` — daily OHLCV bars, composite PK (ticker, ts).
- `features` — LLM-extracted feature JSON per news item.
- `predictions` — prediction records with direction, probability, rationale.
- `outcomes` — scored results: actual return, direction hit, Brier score.
- `rules` — versioned self-authored rules documents.
- `bandit_state` — Thompson sampling arm posteriors per strategy/ticker-bucket.
- `calibration` — serialized calibration regressor versions.
- `watchlist` — active tickers to follow.
- `llm_calls` — cost/token logging for every LLM call.
- `case_embeddings` — sqlite-vec vec0 virtual table, prediction_id as rowid, 384-dim float32 cosine distance.
- `action_queue` — F11 auto-queued follow-up topics with status (pending/running/done/failed/skipped) and link back to source + deep-dive research IDs.
- `holdings` — F12 tracked portfolio positions (`ticker, qty, cost_basis, opened_at, notes, active, updated_at`). Single source of truth for the per-recipient context anchor.
- `insider_filings` — F12 SEC EDGAR Form 4 cache, UNIQUE on accession_number.
- `price_anomalies` — F12 daily flagged volume/price moves, UNIQUE on (ticker, ts).
- `conversations` — F13 two-way WeChat memory (`run_id, recipient, direction, body, intent, intent_confidence, related_research_id, related_action_queue_id, rewrite_id, created_at, embedding_idx`).
- `prompt_rewrites` — F13 staged + applied rewrite proposals with full before/after text for byte-exact revert.
- `conversation_embeddings` — sqlite-vec vec0 virtual table, conversation_id as rowid, 384-dim cosine.

## Pydantic models
- `Settings` (`src/stock/config.py`) — `anthropic_api_key`, `minimax_api_key`, `stock_api_token`, `daily_cost_ceiling_usd`, `db_path`.
- `NewsItem` (`src/stock/ingest/__init__.py`) — single news article before DB insertion.
- `PriceBar` (`src/stock/ingest/__init__.py`) — single daily OHLCV bar.
- `FeedConfig` (`src/stock/ingest/__init__.py`) — RSS feed URL + metadata from feeds.yaml.
- `IngestResult` (`src/stock/ingest/__init__.py`) — summary of an ingestion run (fetched/inserted/skipped counts).
- `ChatMessage` (`src/stock/models.py`) — TypedDict for LLM message (`role`, `content`).
- `ChatResponse` (`src/stock/models.py`) — LLM response with content, token counts, model, cost.
- `NewsFeatures` (`src/stock/features.py`) — extracted feature set (sentiment, novelty, catalyst_type, time_sensitivity, summary).
- `FeatureResult` (`src/stock/features.py`) — wraps `news_id` + `NewsFeatures` for a single extraction.
- `PredictionOutput` (`src/stock/predict.py`) — raw LLM prediction fields (direction, prob_up, expected_return_bps, confidence, rationale, key_factors).
- `PredictionResult` (`src/stock/predict.py`) — stored prediction record returned to callers (prediction_id, ticker, direction, prob_up, prob_up_calibrated, confidence, rationale, created_at, due_at).
- `ArmConfig` (`src/stock/bandit.py`) — static configuration for a single bandit arm (name, provider, model).
- `BanditSelection` (`src/stock/bandit.py`) — result of bandit arm selection for a prediction cycle (strategy_arm, provider, model).
- `ScoreResult` (`src/stock/score.py`) — scoring run counts (scored, skipped, already_scored).
- `OutcomeDetail` (`src/stock/score.py`) — full outcome record with prediction context (prediction_id, ticker, direction, prob_up, actual_return, direction_hit, brier, created_at, due_at, rationale).
- `ReportSummary` (`src/stock/score.py`) — aggregated report (days, total_predictions, scored, pending, hit_rate, mean_brier, best_call, worst_call, total_return_bps, spend_usd).
- `RetrievedCase` (`src/stock/memory.py`) — retrieved past prediction case with full context and similarity score.
- `ReflectResult` (`src/stock/learn.py`) — result of a weekly reflection run (`version`, `provider`, `model`, `dry_run`, `rules_text`, `prediction_count`, `scored_count`).
- `ScheduleInfo` (`src/stock/orchestrator.py`) — next-run times for all scheduled jobs.
- `PredictResponse`, `OnDemandRequest`, `ReportResponse`, `RulesResponse`, `WatchlistAction`, `WatchlistEntry`, `WatchlistResponse`, `CalibrationBucket`, `CalibrationResponse`, `ErrorResponse` (`src/stock/api.py`) — wire models for FastAPI endpoints (requests, responses, error bodies).

## Custom exceptions
- `CostCeilingError` (`src/stock/models.py`) — raised when daily LLM spend reaches `Settings.daily_cost_ceiling_usd`.
- `StockHTTPException` (`src/stock/api.py`) — raised inside handlers to surface a typed HTTP status + message via the global exception handler.

## CLI commands
- `stock ingest news --ticker TICKER` — pull and deduplicate news for a ticker (yahoo + RSS).
- `stock ingest prices --ticker TICKER` — pull daily OHLCV via yfinance.
- `stock predict TICKER` — run a single-ticker prediction cycle.
- `stock score` — score all due predictions, write outcome rows. Idempotent on rerun.
- `stock report --days N` — print hit rate, mean Brier, best/worst call, total return (bps), LLM spend for the last N days.
- `stock reflect` — run weekly reflection: generate updated prediction rules from recent outcomes via LLM.
- `stock reflect --dry-run` — print proposed rules to stdout without writing files or DB rows.
- `stock serve` — run the orchestrator in the foreground with all scheduled jobs. Flags: `--api-only` (FastAPI only, no scheduler), `--scheduler-only` (scheduler only, no API). Default: both run together with the API on a daemon thread.
- `stock action-queue list` — print pending + last-24h completed action_queue rows (F11).
- `stock action-queue run [--max N]` — drain N pending action_queue rows now (F11).
- `stock action-queue clear [--status pending]` — delete rows by status (F11).
- `stock holding add TICKER QTY COST_BASIS [--notes "..."]` — insert/upsert tracked holding (F12).
- `stock holding remove TICKER` — mark a holding inactive (F12).
- `stock holding list` — list active holdings (F12).
- `stock holding note TICKER "free text"` — update notes column (F12).
- `stock anomaly-run` — recompute today's anomalies and print flagged rows (F12).
