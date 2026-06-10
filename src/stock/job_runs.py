"""stock.job_runs -- queryable ledger of scheduled-job executions.

APScheduler only reports job failures to the console/log file, and on this
laptop the orchestrator often runs detached with stale log files -- a job that
starts failing every cycle (e.g. the Robinhood positions pull) can stay
invisible for days. This module records job executions in the `job_runs` table
so the CLI (`stock jobs`), the warning dashboard, and self-review can answer
"what ran, when, and did it fail" from SQL instead of log archaeology.

Storage policy: `ok` rows are kept ONE per (job_id, trigger) -- replaced on
every success so high-frequency jobs (sync_to_render fires every 5 seconds)
cannot bloat the table. `error` and `missed` rows are append-only history,
pruned after PRUNE_DAYS by the nightly backup job.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

PRUNE_DAYS: int = 14

OK = "ok"
ERROR = "error"
MISSED = "missed"


def record_run(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    *,
    trigger: str = "scheduled",
    error: str | None = None,
    duration_ms: int | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> None:
    """Record one job execution. `ok` replaces the prior ok row for the job."""
    finished = finished_at or datetime.now(timezone.utc).isoformat()
    if status == OK:
        conn.execute(
            "DELETE FROM job_runs WHERE job_id = ? AND status = ? AND trigger = ?",
            (job_id, OK, trigger),
        )
    conn.execute(
        "INSERT INTO job_runs"
        " (job_id, status, trigger, started_at, finished_at, duration_ms, error)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (job_id, status, trigger, started_at, finished, duration_ms,
         (error or "")[:1000] or None),
    )
    conn.commit()


def record_run_safe(job_id: str, status: str, **kwargs: Any) -> None:
    """record_run with its own connection; never raises (listener-safe)."""
    from stock.db import get_conn

    try:
        conn = get_conn()
        try:
            record_run(conn, job_id, status, **kwargs)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 -- observability must never break jobs
        logger.exception("job_runs: failed to record %s/%s", job_id, status)


def last_error(
    conn: sqlite3.Connection, job_id: str
) -> tuple[str, str] | None:
    """Return (error, finished_at) of the most recent error row, if any."""
    try:
        row = conn.execute(
            "SELECT error, finished_at FROM job_runs"
            " WHERE job_id = ? AND status = ?"
            " ORDER BY finished_at DESC, id DESC LIMIT 1",
            (job_id, ERROR),
        ).fetchone()
    except sqlite3.OperationalError:  # pre-migration DB without job_runs
        return None
    if row is None:
        return None
    return (str(row[0] or ""), str(row[1]))


def summarize(conn: sqlite3.Connection, *, days: int = 7) -> dict[str, dict[str, Any]]:
    """Per-job rollup: last ok, last error (+message), error count in window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out: dict[str, dict[str, Any]] = {}
    for job_id, finished_at, duration_ms in conn.execute(
        "SELECT job_id, MAX(finished_at), duration_ms FROM job_runs"
        " WHERE status = ? GROUP BY job_id",
        (OK,),
    ):
        out.setdefault(job_id, {})["last_ok"] = finished_at
        out[job_id]["last_ok_duration_ms"] = duration_ms
    for job_id, finished_at, error in conn.execute(
        "SELECT job_id, MAX(finished_at), error FROM job_runs"
        " WHERE status = ? GROUP BY job_id",
        (ERROR,),
    ):
        out.setdefault(job_id, {})["last_error_at"] = finished_at
        out[job_id]["last_error"] = error
    for job_id, count in conn.execute(
        "SELECT job_id, COUNT(*) FROM job_runs"
        " WHERE status != ? AND finished_at >= ? GROUP BY job_id",
        (OK, cutoff),
    ):
        out.setdefault(job_id, {})["failures_in_window"] = count
    return out


def prune(conn: sqlite3.Connection, *, keep_days: int = PRUNE_DAYS) -> int:
    """Delete non-ok rows older than keep_days. Returns rows removed."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    cursor = conn.execute(
        "DELETE FROM job_runs WHERE status != ? AND finished_at < ?",
        (OK, cutoff),
    )
    conn.commit()
    return cursor.rowcount
