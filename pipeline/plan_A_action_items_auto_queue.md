# Plan A — F11: Action-Items Auto-Queue

Goal: turn the daily note's "行动清单 / Action items" section from human homework
into autonomous deep-dives. The system parses items out of the just-generated
report, queues each as a deep-dive, runs the queue between cycles, and surfaces
the results in the next note as "前一轮跟进".

## File changes table

| File                                 | Change   | What                                                                   |
|--------------------------------------|----------|------------------------------------------------------------------------|
| `src/stock/db.py`                    | edit     | Add `action_queue` table + `idx_action_queue_status`                   |
| `src/stock/action_queue.py`          | new      | Queue model + CRUD + extractor + runner; no LLM, just SQL/regex glue   |
| `src/stock/research.py`              | edit     | Call `extract_and_enqueue_actions()` after `generate_daily_research`; build a `previous_followups_block` from completed queue rows; add `{previous_followups_block}` to template format-args |
| `prompts/research.txt`               | edit     | Rename "行动清单" → "AI 自动跟进 / Auto-queued follow-ups"; add new "前一轮跟进 / Last-cycle follow-ups" section pulling `{previous_followups_block}` |
| `src/stock/orchestrator.py`          | edit     | New `_job_run_action_queue()` cron'd between push cycles               |
| `src/stock/cli.py`                   | edit     | New `stock action-queue list/run/clear`                                |
| `src/stock/api.py`                   | edit     | `GET /stock/action_queue` (list pending+done) + `POST /stock/action_queue/run` |
| `openclaw_skill/stock.skill.md`      | edit     | Document the `stock.action_queue` tool                                 |
| `docs/code_structure.md`             | edit     | Append `action_queue.py` entry + `action_queue` table                  |
| `tests/test_action_queue.py`         | new      | Extractor regex tests, enqueue/dedup, runner with mocked deep_dive     |
| `tests/test_research.py`             | edit     | Add follow-ups block formatter test                                    |

## Schema additions (`src/stock/db.py`)

```sql
CREATE TABLE IF NOT EXISTS action_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_research_id INTEGER REFERENCES research_reports(id),
    raw_text TEXT NOT NULL,                  -- original bullet from the note
    topic TEXT NOT NULL,                     -- normalized topic for `stock deep-dive <topic>`
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed | skipped
    deep_dive_id INTEGER REFERENCES research_reports(id),  -- filled when run completes
    error TEXT,
    queued_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_action_queue_status ON action_queue (status, queued_at);
CREATE INDEX IF NOT EXISTS idx_action_queue_source ON action_queue (source_research_id);
```

No `case_embeddings` change — F11 stays in the relational world.

## `src/stock/action_queue.py` shape

Module docstring: `"""stock.action_queue -- parse research-note action items and run them as deep-dives."""`

Public surface:

- `class ActionItem(BaseModel)` — `id`, `source_research_id`, `raw_text`,
  `topic`, `status`, `deep_dive_id`, `error`, `queued_at`, `started_at`,
  `completed_at`.
- `extract_action_items(body: str) -> list[str]` — pulls bullets under the
  "行动清单" / "Action items" heading. Strategy:
  1. Find the heading (regex `(?im)^\s*\d?\.?\s*(?:行动清单|action items)`).
  2. Take the section until the next `^\d+\.` heading or "Not financial advice."
  3. Split on `^\s*[-*•]` bullets, trim. Drop empty strings.
- `normalize_topic(raw: str) -> str` — strip leading/trailing punctuation,
  cap to 80 chars, fall back to `raw` truncated. The deep-dive prompt is
  topic-agnostic so we don't have to guess at a ticker.
- `enqueue_actions(conn, *, source_research_id, raw_items) -> list[ActionItem]`
  — dedup against last 24h pending+done rows, insert, commit.
- `pending_items(conn) -> list[ActionItem]` and
  `recent_completed(conn, hours=18) -> list[ActionItem]`.
- `run_pending(conn, *, max_items: int = 4) -> list[ActionItem]` — for each
  pending row: mark running, call `generate_deep_dive(conn, topic=row.topic,
  extra_context=row.raw_text)`, store `deep_dive_id`, mark done. On failure
  set status=failed, save error, continue. Cost-ceiling errors mark the row
  as `pending` again and break out of the loop.
- `format_previous_followups(items) -> str` — render rows with their
  `deep_dive_id` body excerpt (first 280 chars) for prompt injection.

## Wiring into `research.py`

Two surgical edits inside `generate_daily_research`:

1. Before the LLM call, build `previous_followups_block` from
   `action_queue.recent_completed(conn, hours=18)` joined to
   `research_reports.body` (deep-dive). Add `{previous_followups_block}` to
   `user_template.format(...)`.
2. After `_persist_research(...)`, call
   `action_queue.extract_action_items(body)` → `enqueue_actions(...)` so the
   *current* note's auto-queued items become the *next* note's follow-ups.
   Wrap in try/except — a parse failure must not poison the push.

## CLI / API / skill exposure

- `stock action-queue list` — print pending + last-24h completed rows.
- `stock action-queue run [--max N]` — drain N pending rows now.
- `stock action-queue clear --status pending` — hard reset for ops.
- `GET /stock/action_queue?status=pending|done|all` — list rows.
- `POST /stock/action_queue/run` body `{"max": 4}` — trigger drain.
- Skill manifest gets:
  ```
  Tool: stock.action_queue(action="list"|"run", max=N)
    → list pending or run them; returns counts + recent topics.
  ```

## Scheduler change

Add to `orchestrator.create_scheduler()`:

```python
scheduler.add_job(
    _job_run_action_queue,
    CronTrigger(
        hour=f"{RESEARCH_MORNING_HOUR-1},{RESEARCH_EVENING_HOUR-1}",
        minute=45,  # 01:45 / 13:45 UTC, ~45 min before each push
        timezone="UTC",
    ),
    id="action_queue_runner",
    name="Run pending auto-queued action items",
)
```

So each push cycle is: discovery (T-30m) → action-queue runner (T-45m, but
note: queue runner should fire *before* discovery so its deep-dives can be
referenced; revise to T-90m) → discovery (T-30m) → research push (T).

## Prompt rewrite (`prompts/research.txt`)

Section 6 changes from:

> 6. **行动清单 / Action items** — 2-4 concrete next steps for the analyst
>    (data to pull, filings to read, prices to watch).

to:

> 6. **AI 自动跟进 / Auto-queued follow-ups** — 2-4 concrete deep-dive topics
>    you want the system to research before the next push. Phrase each as a
>    standalone topic (e.g. "TER WFE bookings vs Q3 guidance",
>    "300308.SZ HBM capacity ramp"). The system will run each as a deep-dive
>    and feed the result back into the next note.

A new section 0 (or 1.5) is inserted:

> **前一轮跟进 / Last-cycle follow-ups** — what we already learned since the
> last push. Use the bullets below to update or close out earlier theses;
> do not repeat their full content.
> {previous_followups_block}

Order matters: keep "今日主线" as section 1 and put "前一轮跟进" between
section 1 and section 2 — the "Theme of the day" stays the lead.

## Time estimate

- Session 1 (~3h): schema + `action_queue.py` + extractor regex + tests.
- Session 2 (~2h): research.py wiring + prompt edits + scheduler + CLI/API.

Total: ~5h, conservatively 2 sessions per the existing F-series cadence.

## Test plan

- `test_action_queue.py`:
  - `extract_action_items` against three real `research_reports.body`
    samples (zh, en, mixed bullets `-` `*` `•`).
  - Dedup logic: re-enqueue same topic within 24h yields no new row.
  - `run_pending` with mocked `generate_deep_dive` returning a fake
    `ResearchReport`; assert deep_dive_id stamped + status=done.
  - Cost-ceiling-during-run leaves remaining rows `pending` and re-raises
    so the orchestrator-level handler logs it.
- `test_research.py` extension: monkeypatch
  `action_queue.recent_completed` to return two synthetic rows; assert
  the rendered prompt contains the expected `前一轮跟进` block.
- Smoke: `stock research`, then `stock action-queue list` shows new
  pending rows; `stock action-queue run --max 1` drains one.

## Risks / mitigations

- **Bad parsing** → `enqueue_actions` only fires inside try/except in
  `research.py`; failure logged, no DB write.
- **Runaway queue** → `run_pending(max_items=4)` cap; daily cost ceiling
  still enforced inside `generate_deep_dive`.
- **Topic dedup false positives** → dedup is exact-match on normalized
  topic; analyst can `stock action-queue clear` if needed.
- **Prompt budget overflow** → `format_previous_followups` truncates
  per-item body excerpt to 280 chars and caps at 4 items.
