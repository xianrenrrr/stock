# STOCK — coding style guide

Python project. Every pipeline agent (planner, creator, validator, screener, writer) must follow this.

## Language and tooling
- Python 3.12. No f-strings with side effects. No wildcard imports. No mutable default args.
- Type hints on every function signature. Use `from __future__ import annotations` at the top of every module.
- `ruff` for lint + format (line length 100). `mypy --strict` for type checking. `pytest` for tests.
- Dependency manager: `pip` + `pyproject.toml` (no Poetry, no uv for now — keep it simple on Windows).

## File headers
Every source file starts with a one-line module docstring:
```python
"""stock.predict — run a single-ticker prediction cycle."""
from __future__ import annotations
```

## Naming
- `snake_case` for modules, files, functions, variables.
- `PascalCase` for classes and `TypedDict` / `pydantic.BaseModel` names.
- Constants `UPPER_SNAKE_CASE`.
- No single-letter names except `i`, `j`, `k` in tight loops, or `e` in `except`.

## Structure
- Functions read top-to-bottom as a sequence of "code paragraphs": 3–8 lines per paragraph, with a single-line `#` comment above each paragraph stating WHAT happens next (never WHY obvious things are obvious).
- No paragraph-level comments inside trivial three-line helpers.
- Early returns preferred over nested `if`.
- Result objects: return `pydantic` models or `TypedDict`s, not tuples with positional meaning.

## Errors
- Raise specific exceptions (`ValueError`, `RuntimeError`, custom `StockError` subclasses).
- At entry points (CLI commands, FastAPI endpoints, scheduled jobs): wrap in try/except, log full traceback, return a structured error object. Never swallow silently.
- No `except Exception: pass`. Ever.

## Imports
Grouped, blank line between groups, alphabetical within each:
```python
# stdlib
import json
from datetime import datetime, timezone

# third-party
import httpx
from pydantic import BaseModel

# internal
from stock.config import Settings
from stock.db import get_conn
```
Never import `*`. Never import from `src.stock.*` — use `stock.*`.

## LLM calls
- Always go through `stock.models.get_client(provider)` — never instantiate `anthropic.Anthropic()` or `openai.OpenAI()` directly in feature code.
- Always set prompt caching on the system prompt.
- Always log input tokens, output tokens, cost, model, duration to the `llm_calls` table.
- Respect the daily cost ceiling from `stock.config.Settings.daily_cost_ceiling_usd` — check before every call.

## Testing
- One `tests/test_<module>.py` per source module that has logic (not pure config).
- Use `pytest` fixtures for the test DB (`:memory:` SQLite). Never touch the real `data/stock.db` in tests.
- Mock all network I/O with `respx` (for httpx) or `unittest.mock`. No tests should call Claude/MiniMax/yfinance/RSS.

## Incremental changes
- Existing code is production. Never delete or rewrite broadly. Surgical edits only.
- When modifying a file: Read it first, understand current shape, then Edit.
- New functionality goes in new files where reasonable, or appended to existing files.
- Never rename existing public functions/classes without an explicit ticket for the rename.

## No noise
- Do not add comments that restate the code.
- Do not add README files per directory.
- Do not write migration scripts for schema changes that haven't shipped — edit `stock/db.py` directly until v1.
- No emojis in code, comments, or commit messages.

## Daily self-review
At the start of any session in this project, check `pipeline/daily_review_*.md`. If a packet from the last 48 hours exists, read the most recent one before proposing changes — it summarizes errors, boss feedback, drift, and pending items the operator may want addressed. Use the `/improve` slash command to drive a structured review.
