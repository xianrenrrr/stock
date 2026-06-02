"""tests.test_daily_zh -- Chinese daily activity report."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from stock import daily_zh, db
from stock.daily_zh import generate_daily_zh_report


@pytest.fixture
def conn() -> sqlite3.Connection:
    return db.get_conn(":memory:")


@pytest.fixture
def chdir_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run tests in a tmp dir so daily_zh_*.md doesn't pollute pipeline/."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pipeline").mkdir()
    return tmp_path


def test_daily_zh_emits_report_with_no_activity(conn: sqlite3.Connection, chdir_tmp: Path) -> None:
    """Empty DB -> report still renders, with placeholders for empty sections."""
    with patch.object(daily_zh, "_git_commits_today", return_value=[]):
        path, body = generate_daily_zh_report(conn)
    assert "每日工作汇报" in body
    assert "no git commits today" in body or "无 git" in body or "no tech dives" in body
    assert Path(path).exists()


def test_daily_zh_includes_tech_dives(conn: sqlite3.Connection, chdir_tmp: Path) -> None:
    """Today's tech_dive_runs are surfaced."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    # Need a research_reports row for the FK
    conn.execute(
        "INSERT INTO research_reports (kind, topic, body, created_at)"
        " VALUES ('tech_dive', 'OCS test', 'body', ?)",
        (today,),
    )
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO tech_dive_runs (topic, sector, language, research_id, rounds, cost_usd, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("OCS vs CPO", "information", "zh-en", rid, 4, 0.0, today),
    )
    conn.commit()
    with patch.object(daily_zh, "_git_commits_today", return_value=[]):
        _, body = generate_daily_zh_report(conn)
    assert "OCS vs CPO" in body
    assert "[information]" in body
    assert "(4 rounds)" in body


def test_daily_zh_includes_research_kinds(conn: sqlite3.Connection, chdir_tmp: Path) -> None:
    """research_reports counts by kind appear in section 3."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    for k in ["daily", "daily", "alert", "deep_qa"]:
        conn.execute(
            "INSERT INTO research_reports (kind, topic, body, created_at)"
            " VALUES (?, '', '', ?)",
            (k, today),
        )
    conn.commit()
    with patch.object(daily_zh, "_git_commits_today", return_value=[]):
        _, body = generate_daily_zh_report(conn)
    assert "`daily`: 2" in body
    assert "`alert`: 1" in body
    assert "`deep_qa`: 1" in body


def test_daily_zh_handles_git_unavailable(conn: sqlite3.Connection, chdir_tmp: Path) -> None:
    """git log failure should not crash the report."""
    with patch.object(daily_zh, "_git_commits_today", side_effect=Exception("git not found")):
        # The internal helper catches; but if it propagates, this test ensures we don't crash
        try:
            _, body = generate_daily_zh_report(conn)
            assert "每日工作汇报" in body
        except Exception:
            pytest.fail("daily_zh should be resilient to git unavailability")
