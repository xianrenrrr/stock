"""tests.test_job_runs -- scheduled-job execution ledger."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from stock import job_runs


def test_ok_rows_are_replaced_not_appended(mem_db: sqlite3.Connection) -> None:
    job_runs.record_run(mem_db, "score_daily", job_runs.OK, duration_ms=100)
    job_runs.record_run(mem_db, "score_daily", job_runs.OK, duration_ms=200)
    job_runs.record_run(mem_db, "sync_to_render", job_runs.OK, duration_ms=5)

    rows = mem_db.execute(
        "SELECT job_id, duration_ms FROM job_runs WHERE status = 'ok'"
        " ORDER BY job_id",
    ).fetchall()
    assert rows == [("score_daily", 200), ("sync_to_render", 5)]


def test_error_rows_append_and_summarize(mem_db: sqlite3.Connection) -> None:
    job_runs.record_run(mem_db, "broker_positions_pull", job_runs.OK)
    job_runs.record_run(
        mem_db, "broker_positions_pull", job_runs.ERROR, error="pull skipped: MCP down",
    )
    job_runs.record_run(
        mem_db, "broker_positions_pull", job_runs.ERROR, error="pull skipped: MCP down",
    )

    summary = job_runs.summarize(mem_db)
    info = summary["broker_positions_pull"]
    assert info["failures_in_window"] == 2
    assert "MCP down" in info["last_error"]
    assert info["last_ok"] is not None

    err = job_runs.last_error(mem_db, "broker_positions_pull")
    assert err is not None
    assert "MCP down" in err[0]


def test_last_error_none_when_clean(mem_db: sqlite3.Connection) -> None:
    job_runs.record_run(mem_db, "score_daily", job_runs.OK)
    assert job_runs.last_error(mem_db, "score_daily") is None


def test_prune_drops_old_failures_keeps_ok(mem_db: sqlite3.Connection) -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    job_runs.record_run(mem_db, "a_job", job_runs.ERROR, error="old", finished_at=old)
    job_runs.record_run(mem_db, "a_job", job_runs.ERROR, error="fresh")
    job_runs.record_run(mem_db, "a_job", job_runs.OK, finished_at=old)

    removed = job_runs.prune(mem_db, keep_days=14)

    assert removed == 1
    statuses = [r[0] for r in mem_db.execute("SELECT status FROM job_runs")]
    assert sorted(statuses) == ["error", "ok"]


def test_error_text_is_capped(mem_db: sqlite3.Connection) -> None:
    job_runs.record_run(mem_db, "a_job", job_runs.ERROR, error="x" * 5000)
    (stored,) = mem_db.execute("SELECT error FROM job_runs").fetchone()
    assert len(stored) == 1000
