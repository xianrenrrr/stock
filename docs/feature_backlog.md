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
