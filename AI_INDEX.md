# STOCK AI Index

Last updated: 2026-05-25.

This is now a lightweight pointer file. The old auto-generated index became
stale and conflicted with the real scheduler. Do not use this file as a module
catalog or schedule source.

## Read First

1. `docs/README.md` - docs map and source-of-truth order.
2. `docs/runtime_source_of_truth.md` - active scheduled jobs and manual-only features.
3. `docs/agent_guidance.md` - guidance for coding and non-coding agents.
4. `CLAUDE.md` - coding rules.
5. `WORKFLOW.md` - short operational summary.

## Where To Edit

| Task | Start here |
|---|---|
| Scheduler/job behavior | `src/stock/orchestrator.py` |
| Prediction behavior | `src/stock/predict.py`, `data/rules/current.md`, `prompts/predict.txt` |
| Model improvement loop | `src/stock/grading.py`, `src/stock/prompt_rewriter.py` |
| Daily research note | `src/stock/research.py`, `prompts/research.txt` |
| Deep-dive/action queue | `src/stock/action_queue.py`, `src/stock/research.py` |
| Options/UOA/ratios | `src/stock/options.py`, `src/stock/db.py` |
| CLI commands | `src/stock/cli.py` |
| API/dashboard | `src/stock/api.py`, `src/stock/channel.py`, `src/stock/static/` |
| Runtime docs | `docs/runtime_source_of_truth.md`, `WORKFLOW.md`, `README.md` |

## Current Runtime Summary

- Local mode has 29 active scheduler jobs.
- F43 tech dive runs weekly on Sunday 04:30 UTC and remains manually runnable.
- Weekly Q&A deep dive is active on Saturdays at 07:00 UTC.
- Company DD is active weekly on Wednesdays at 09:15 UTC.
- Action-queue deep dives run at 00:00 and 12:00 UTC only when pending items exist.
- Daily research scans and action-report emails run Monday-Friday only.
- Grading model-improvement directions now feed automatic rules/prompt improvement,
  with an append-to-rules fallback when byte-exact rewriting does not apply.

For details, use `docs/runtime_source_of_truth.md`.
