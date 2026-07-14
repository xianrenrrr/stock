"""stock.action_queue -- parse research-note action items and run them as deep-dives."""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from stock.models import CostCeilingError

logger = logging.getLogger(__name__)

DEFAULT_RUN_LIMIT: int = 4
DEFAULT_DEDUP_HOURS: int = 24
TOPIC_MAX_CHARS: int = 160
EXCERPT_MAX_CHARS: int = 280
PREVIOUS_FOLLOWUPS_MAX_ITEMS: int = 4

_HEADING_RE = re.compile(
    r"(?im)^\s*\d?\.?\s*\**\s*(?:行动清单|action items|ai\s*自动跟进|AI\s*自动跟进|AI助手自动跟进|Agent\s*auto-queued follow-ups|auto-queued follow-ups)"
)
_NEXT_HEADING_RE = re.compile(r"(?m)^\s*(?:\d+\.|#{1,3}\s)|^\s*Not financial advice\.")
_BULLET_RE = re.compile(r"(?m)^\s*[-*\u2022]\s+(.+?)\s*$")


class ActionItem(BaseModel):
    """One row of the action_queue table."""

    id: int | None = None
    source_research_id: int | None = None
    raw_text: str
    topic: str
    status: str = "pending"
    deep_dive_id: int | None = None
    error: str | None = None
    queued_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None


def extract_action_items(body: str) -> list[str]:
    """Pull bullet items out of the action-items / auto-queued section of a note.

    Tolerates the legacy '行动清单 / Action items' heading and the F11
    'AI 自动跟进 / Auto-queued follow-ups' rename. Returns the raw bullet text
    for each item; downstream callers normalize.
    """
    if not body:
        return []

    match = _HEADING_RE.search(body)
    if not match:
        return []

    section_start = match.end()

    # Find the next numbered heading, markdown header, or disclaimer
    rest = body[section_start:]
    end_match = _NEXT_HEADING_RE.search(rest)
    section = rest if end_match is None else rest[: end_match.start()]

    bullets = [m.group(1).strip() for m in _BULLET_RE.finditer(section)]
    # Drop empty / pure-punctuation rows
    return [b for b in bullets if b and any(c.isalnum() for c in b)]


def normalize_topic(raw: str) -> str:
    """Trim whitespace / leading bullet markers and cap length."""
    cleaned = raw.strip().lstrip("-*\u2022 ").strip()
    cleaned = cleaned.strip("\"' ")
    if len(cleaned) > TOPIC_MAX_CHARS:
        cleaned = cleaned[:TOPIC_MAX_CHARS].rstrip()
    return cleaned


def _row_to_item(row: tuple) -> ActionItem:
    """Convert a SELECT row into an ActionItem model."""
    return ActionItem(
        id=int(row[0]),
        source_research_id=row[1],
        raw_text=str(row[2]),
        topic=str(row[3]),
        status=str(row[4]),
        deep_dive_id=row[5],
        error=row[6],
        queued_at=str(row[7]),
        started_at=row[8],
        completed_at=row[9],
    )


def _exists_recent_topic(
    conn: sqlite3.Connection, topic: str, *, hours: int = DEFAULT_DEDUP_HOURS
) -> bool:
    """Return True if a row with the same topic was queued within the lookback."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    row = conn.execute(
        "SELECT 1 FROM action_queue"
        " WHERE topic = ? AND queued_at >= ?"
        " AND status IN ('pending', 'running', 'done')"
        " LIMIT 1",
        (topic, cutoff),
    ).fetchone()
    return row is not None


def enqueue_actions(
    conn: sqlite3.Connection,
    *,
    source_research_id: int | None,
    raw_items: list[str],
) -> list[ActionItem]:
    """Insert each raw item as a pending row, deduping recent identical topics."""
    if not raw_items:
        return []

    now = datetime.now(timezone.utc).isoformat()
    inserted: list[ActionItem] = []

    for raw in raw_items:
        if not raw or not raw.strip():
            continue
        topic = normalize_topic(raw)
        if not topic:
            continue
        if _exists_recent_topic(conn, topic):
            continue

        cursor = conn.execute(
            "INSERT INTO action_queue (source_research_id, raw_text, topic,"
            " status, queued_at) VALUES (?, ?, ?, 'pending', ?)",
            (source_research_id, raw.strip(), topic, now),
        )
        inserted.append(
            ActionItem(
                id=int(cursor.lastrowid or 0),
                source_research_id=source_research_id,
                raw_text=raw.strip(),
                topic=topic,
                status="pending",
                queued_at=now,
            )
        )
    conn.commit()
    return inserted


def pending_items(conn: sqlite3.Connection) -> list[ActionItem]:
    """Return all rows with status='pending', oldest first."""
    rows = conn.execute(
        "SELECT id, source_research_id, raw_text, topic, status, deep_dive_id,"
        " error, queued_at, started_at, completed_at"
        " FROM action_queue WHERE status = 'pending'"
        " ORDER BY queued_at ASC, id ASC"
    ).fetchall()
    return [_row_to_item(r) for r in rows]


def pending_user_initiated(conn: sqlite3.Connection) -> list[ActionItem]:
    """Pending rows that came from a user dashboard message (source_research_id IS
    NULL), oldest first. Auto-generated follow-ups (which carry a source_research_id)
    are excluded so the expedite drain only fast-tracks what the boss typed."""
    rows = conn.execute(
        "SELECT id, source_research_id, raw_text, topic, status, deep_dive_id,"
        " error, queued_at, started_at, completed_at"
        " FROM action_queue WHERE status = 'pending' AND source_research_id IS NULL"
        " ORDER BY queued_at ASC, id ASC"
    ).fetchall()
    return [_row_to_item(r) for r in rows]


def recent_completed(
    conn: sqlite3.Connection, *, hours: int = 18
) -> list[ActionItem]:
    """Return done rows from the last N hours, newest first."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        "SELECT id, source_research_id, raw_text, topic, status, deep_dive_id,"
        " error, queued_at, started_at, completed_at"
        " FROM action_queue WHERE status = 'done' AND completed_at >= ?"
        " ORDER BY completed_at DESC, id DESC",
        (cutoff,),
    ).fetchall()
    return [_row_to_item(r) for r in rows]


def _mark_running(conn: sqlite3.Connection, item_id: int) -> None:
    """Stamp started_at, count the attempt, and flip status -> running."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE action_queue SET status = 'running', started_at = ?,"
        " attempts = COALESCE(attempts, 0) + 1"
        " WHERE id = ?",
        (now, item_id),
    )
    conn.commit()


def _mark_done(conn: sqlite3.Connection, item_id: int, deep_dive_id: int) -> None:
    """Stamp completed_at, status, and deep_dive_id once a run finishes."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE action_queue SET status = 'done', completed_at = ?,"
        " deep_dive_id = ? WHERE id = ?",
        (now, deep_dive_id, item_id),
    )
    conn.commit()


def _mark_failed(conn: sqlite3.Connection, item_id: int, error: str) -> None:
    """Mark a run as failed and persist the error text for audit."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE action_queue SET status = 'failed', completed_at = ?, error = ?"
        " WHERE id = ?",
        (now, error[:1000], item_id),
    )
    conn.commit()


def _mark_pending_again(conn: sqlite3.Connection, item_id: int) -> None:
    """Revert a row back to pending (cost-ceiling re-queue)."""
    conn.execute(
        "UPDATE action_queue SET status = 'pending', started_at = NULL"
        " WHERE id = ?",
        (item_id,),
    )
    conn.commit()


RETRY_MAX_ATTEMPTS: int = 3
RETRY_MAX_AGE_HOURS: int = 48
_TRANSIENT_CLI_ERROR_MARKERS: tuple[str, ...] = (
    "ClaudeCliUnavailable",
    "CodexCliUnavailable",
    "`claude -p`",
    "codex exec",
)


def requeue_failed(
    conn: sqlite3.Connection,
    *,
    max_age_hours: int = RETRY_MAX_AGE_HOURS,
    max_attempts: int = RETRY_MAX_ATTEMPTS,
) -> int:
    """Flip recent failed rows back to pending so the next drain retries them.

    A deep dive killed by a transient CLI failure (timeout, 5h usage-window
    exhaustion, flaky subprocess) must not be lost forever -- this is the
    queue-item mirror of the plan-I scheduler-job retry. Non-CLI failures older
    than max_age_hours or rows already tried max_attempts times stay failed
    (legacy rows with NULL attempts count as one attempt).
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    ).isoformat()
    cli_error_clause = " OR ".join(
        "error LIKE ?" for _ in _TRANSIENT_CLI_ERROR_MARKERS
    )
    cursor = conn.execute(
        "UPDATE action_queue SET status = 'pending', started_at = NULL,"
        " completed_at = NULL"
        " WHERE status = 'failed' AND (queued_at >= ? OR " + cli_error_clause + ")"
        " AND COALESCE(attempts, 1) < ?",
        (
            cutoff,
            *(f"%{marker}%" for marker in _TRANSIENT_CLI_ERROR_MARKERS),
            max_attempts,
        ),
    )
    conn.commit()
    requeued = int(cursor.rowcount or 0)
    if requeued:
        logger.info("action_queue: re-queued %d failed item(s) for retry", requeued)
    return requeued


def run_pending(
    conn: sqlite3.Connection,
    *,
    max_items: int = DEFAULT_RUN_LIMIT,
    items: list[ActionItem] | None = None,
) -> list[ActionItem]:
    """Drain up to max_items pending rows by running them as deep-dives.

    If `items` is given, drain exactly those (already selected/capped by the
    caller, e.g. the user-initiated expedite drain); otherwise use the oldest
    pending rows up to max_items. Imports `generate_deep_dive` lazily to avoid
    an import cycle with `stock.research`.
    """
    # Lazy import: action_queue is consumed by research.py's persist path
    from stock.research import generate_deep_dive

    completed: list[ActionItem] = []
    items = items if items is not None else pending_items(conn)[:max_items]

    for item in items:
        if item.id is None:
            continue
        _mark_running(conn, item.id)
        try:
            report = generate_deep_dive(
                conn, topic=item.topic, extra_context=item.raw_text
            )
            _mark_done(conn, item.id, report.research_id)
            item.status = "done"
            item.deep_dive_id = report.research_id
            completed.append(item)
        except CostCeilingError:
            # Cost ceiling: re-queue this row and stop the loop
            _mark_pending_again(conn, item.id)
            logger.warning("action_queue: cost ceiling reached, re-queuing %s", item.topic)
            raise
        except Exception as exc:  # noqa: BLE001 -- surface but keep draining
            logger.exception("action_queue run failed for topic=%s", item.topic)
            _mark_failed(conn, item.id, repr(exc))
            item.status = "failed"
            item.error = repr(exc)
            completed.append(item)
    return completed


def format_previous_followups(items: list[ActionItem], conn: sqlite3.Connection) -> str:
    """Render completed action_queue rows as the 'last cycle' prompt block."""
    if not items:
        return "(no completed AI follow-ups since last push)"

    capped = items[:PREVIOUS_FOLLOWUPS_MAX_ITEMS]
    lines: list[str] = []
    for item in capped:
        excerpt = ""
        if item.deep_dive_id is not None:
            row = conn.execute(
                "SELECT body FROM research_reports WHERE id = ?",
                (item.deep_dive_id,),
            ).fetchone()
            if row and row[0]:
                excerpt = str(row[0]).strip().replace("\n", " ")[:EXCERPT_MAX_CHARS]
        lines.append(
            f"- topic: {item.topic}\n"
            f"    summary: {excerpt or '(no body recorded)'}"
        )
    return "\n".join(lines)


def clear(conn: sqlite3.Connection, *, status: str | None = None) -> int:
    """Delete rows by status (or all rows if status is None). Returns deleted count."""
    if status is None:
        cursor = conn.execute("DELETE FROM action_queue")
    else:
        cursor = conn.execute(
            "DELETE FROM action_queue WHERE status = ?", (status,)
        )
    conn.commit()
    return int(cursor.rowcount or 0)

