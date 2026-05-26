# Pipeline Directory

This directory is mostly historical plans and generated artifacts.

Do not use this directory as the source of truth for what runs automatically.
Use:

- `../docs/runtime_source_of_truth.md`
- `../docs/agent_guidance.md`
- `../WORKFLOW.md`

## Contents

| Path | Meaning |
|---|---|
| `daily_review_*.md` | Generated operational self-review packets. |
| `daily_zh_*.md` | Generated Chinese activity reports. |
| `companies/*.md` | Generated per-company dense context files. |
| `dd/*.md` | Generated company due-diligence files. |
| `pdf/*` | Generated PDF/HTML exports. |
| `logs/*` | Historical agent/orchestrator logs. |
| `outputs/*` | Historical multi-agent development outputs. |
| `plan_*.md`, `MASTER_PLAN.md` | Historical implementation plans. |
| `tech_dive_*.md`, `research_*.md`, `qa_*.md` | Generated or historical research artifacts. |

## Editing Rule

Only edit generated artifacts when the user explicitly asks to correct that
artifact. For code/runtime changes, edit `src/stock/`, `prompts/`, `data/`,
`tests/`, and canonical docs instead.

