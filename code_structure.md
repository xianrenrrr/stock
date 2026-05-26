# STOCK Code Structure

Last updated: 2026-05-25.

This top-level file is intentionally short. Use `docs/agent_guidance.md` for
where to edit, and `docs/runtime_source_of_truth.md` for what runs.

## Main Directories

| Path | Purpose |
|---|---|
| `src/stock/` | Application code. |
| `tests/` | Pytest suite. |
| `prompts/` | LLM prompt templates. |
| `data/` | Editable YAML config plus runtime DB/cache files. |
| `docs/` | Canonical docs and research notes. |
| `pipeline/` | Generated outputs and historical implementation plans. |
| `mobile/` | Android client. |
| `scripts/` | Utility scripts. |
| `openclaw_skill/` | Legacy/OpenClaw skill manifest. |

## Key Modules

| Module | Responsibility |
|---|---|
| `config.py` | Environment settings. |
| `db.py` | SQLite schema and connection factory. |
| `orchestrator.py` | APScheduler jobs. Runtime truth starts here. |
| `cli.py` | Typer CLI. |
| `api.py`, `channel.py` | FastAPI/dashboard surfaces. |
| `ingest/` | Prices, news, RSS, EDGAR ingestion. |
| `features.py` | LLM feature extraction for news. |
| `predict.py` | Per-ticker prediction cycle and guardrails. |
| `score.py` | Outcome scoring. |
| `grading.py` | Daily grading note, follow-up queueing, model-improvement auto-apply. |
| `prompt_rewriter.py` | Byte-exact prompt/rule rewrite engine. |
| `research.py` | Daily research note, deep-dive, reply generation. |
| `action_queue.py` | Auto-queued deep-dive topics. |
| `options.py` | Unusual options activity and call/put ratio snapshots. |
| `discovery_engine.py`, `leading.py` | Forward-looking candidate scoring. |
| `tech_dive.py`, `qa_deepdive.py`, `analyst_skills.py` | Deep-dive engines. |
| `stops.py`, `entry_signals.py`, `holdings.py` | Portfolio/action helpers. |
| `self_review.py` | Operational daily packet and autopilot runner. |

## Canonical References

- Runtime schedule: `docs/runtime_source_of_truth.md`
- Agent guidance: `docs/agent_guidance.md`
- Coding guidance: `CLAUDE.md`
- Docs index: `docs/README.md`

