# STOCK Workflow Overview

Last updated: 2026-05-25.

The canonical runtime schedule is now:

- [docs/runtime_source_of_truth.md](docs/runtime_source_of_truth.md)

Use that file when deciding what actually runs automatically. Older roadmap
files in `pipeline/` describe design history and may not match current code.

## One-Line Summary

STOCK is a local-first equity research pipeline:

1. Ingest prices/news/web context.
2. Generate predictions and research notes.
3. Score outcomes and verify theses/events.
4. Queue and run follow-up deep dives.
5. Push notes to the dashboard/APK.
6. Improve rules/prompts when grading evidence supports a safe rewrite.

## Current Automatic Loop

In local mode (`STOCK_MODE=local`) the scheduler has 29 active jobs. The main
daily loop is:

| UTC time | Job |
|---:|---|
| 02:00, 14:00 Mon-Fri | ingest + feature extraction |
| 02:15, 14:15 Mon-Fri | prediction runs |
| 02:30, 14:30 Mon-Fri | research note generation/push |
| 14:45 Mon-Fri | email latest daily action report |
| 20:05 Mon-Fri | post-close price/volume snapshot |
| 21:30-21:55 Mon-Fri | score, anomaly, thesis, grading, events, options |
| 22:15-23:30 Mon-Fri/daily | smallcap, discovery, backup |
| 00:00, 12:00 | action-queue deep-dive runner |
| 06:00 | self-review packet/autopilot |

Weekly jobs include rules reflection, holdings health check, Q&A deep dive,
SEC Form 4 pull, entry-zone scan, AI-loop measurement, and company DD.

## Deep-Dive Reality

There are multiple deep-dive mechanisms:

| Mechanism | Automatic? | Current cadence |
|---|---:|---|
| Action-queue deep dives | Yes, if queue has pending topics | 00:00 and 12:00 UTC daily |
| Weekly Q&A deep dive | Yes | Saturday 07:00 UTC |
| F43 tech-dive | Yes | Sunday 04:30 UTC |
| Company DD checklist | Yes | Wednesday 09:15 UTC, one company |
| Health-check deep dive | Yes | Saturday 07:00 UTC for holdings |
| On-demand deep dive | No | Manual via `stock deep-dive <topic>` |

The most common reason action-queue deep dives do not run is that no queued
items exist. F43 tech-dive now runs weekly, not daily.

## Auto-Improvement Reality

`模型改进方向 / Model Improvement Directions` now feeds the automatic prompt/rule
rewrite path:

- grading note generated from scored outcomes
- Model Improvement section extracted
- existing prompt rewriter proposes byte-exact edits
- grading-driven byte-exact edits apply automatically
- unsafe/mismatched edits are staged in `prompt_rewrites`
- if no safe edit applies, the section is appended to `data/rules/current.md`
  so the next prediction sees it anyway
- unexpected failures send a best-effort email alert

No scored predictions means no model-improvement action.

## Operator Commands

```powershell
python -m stock.cli action-queue list
python -m stock.cli action-queue run --max-items 4
python -m stock.cli grade
python -m stock.cli self-review compile --print
python -m stock.cli entry-scan
python -m stock.cli weekly-qa-dive
python -m stock.cli tech-dive "<topic>"
python -m stock.cli uoa-scan
```

Not financial advice.
