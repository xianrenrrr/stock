# STOCK Coding Guidance

Last updated: 2026-05-25.

This file is for coding agents. For broader agent behavior, read
`docs/agent_guidance.md` first. For scheduler/runtime truth, read
`docs/runtime_source_of_truth.md`.

## Source Of Truth Order

When files conflict, trust:

1. Running code in `src/stock/`.
2. `docs/runtime_source_of_truth.md`.
3. `docs/agent_guidance.md`.
4. `WORKFLOW.md`.
5. Historical docs in `pipeline/`, `md/`, and old design files.

## Non-Negotiables

- Preserve user work in the dirty tree. Never revert unrelated changes.
- Keep edits scoped and surgical.
- Add or update tests for behavior changes.
- Use existing patterns before adding abstractions.
- Respect cost ceilings and log LLM calls through existing helpers.
- Do not silently swallow errors at entry points; log exceptions with context.
- Never remove the `Not financial advice.` requirement from user-facing investment text.

## Where To Change Things

| Change | Files |
|---|---|
| Scheduler cadence/job list | `src/stock/orchestrator.py`, `tests/test_orchestrator.py`, `docs/runtime_source_of_truth.md` |
| Prediction logic | `src/stock/predict.py`, `prompts/predict.txt`, `data/rules/current.md`, `tests/test_predict.py` |
| Model improvement loop | `src/stock/grading.py`, `src/stock/prompt_rewriter.py`, `prompts/grading.txt`, `tests/test_grading.py` |
| Daily research output | `src/stock/research.py`, `prompts/research.txt`, formatter modules |
| Deep-dive follow-ups | `src/stock/action_queue.py`, `src/stock/research.py`, tests |
| Options/UOA/ratios | `src/stock/options.py`, `src/stock/db.py`, `tests/test_options.py` |
| CLI | `src/stock/cli.py` |
| API/dashboard | `src/stock/api.py`, `src/stock/channel.py`, `src/stock/static/` |
| Operator docs | `README.md`, `WORKFLOW.md`, `docs/runtime_source_of_truth.md` |

## Coding Style

- Python 3.12.
- Prefer explicit, typed dataclasses/Pydantic models for structured records.
- Use parameterized SQL.
- Keep functions small enough to test directly.
- Comments should explain non-obvious reasoning, not restate code.
- Do not introduce broad refactors while fixing narrow behavior.
- For file searches use `rg`; for edits use the normal patch/edit path.

## Tests

Run focused tests for touched modules. Examples:

```powershell
pytest tests/test_grading.py tests/test_prompt_rewriter.py -q
pytest tests/test_options.py -q
pytest tests/test_orchestrator.py -q
python -m ruff check src/stock/grading.py tests/test_grading.py
```

If changing scheduler jobs, also verify:

```powershell
@'
from stock.orchestrator import create_scheduler
s = create_scheduler()
for job in s.get_jobs():
    print(job.id, job.trigger)
print("TOTAL", len(s.get_jobs()))
'@ | python -
```

## Database And Migrations

Schema lives in `src/stock/db.py`. This project still mostly uses
`CREATE TABLE IF NOT EXISTS` and does not have a mature migration framework.
When adding columns/tables:

- Update `db.py`.
- Update tests that initialize `:memory:` DBs.
- Document operational impact in `docs/runtime_source_of_truth.md` if runtime
  behavior changes.

## LLM Calls

- Use existing model client helpers.
- Log model/provider/tokens/cost/duration/caller to `llm_calls`.
- Check cost ceiling before discretionary calls.
- Prefer zero-metered `codex_cli`/`claude_cli` core backend when configured.
- Keep high-frequency utility calls cheap and resilient.

## Generated Artifacts

Do not edit generated artifacts during code cleanup:

- `pipeline/daily_review_*.md`
- `pipeline/companies/*.md`
- `pipeline/dd/*.md`
- `pipeline/pdf/*`
- `pipeline/logs/*`
- `pipeline/outputs/*`
- `logs/*`

Use docs/readmes to point around generated artifacts rather than rewriting them.
