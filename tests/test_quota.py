"""tests.test_quota -- 5h quota windows + leftover-job retry (plan I)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from stock import job_runs, quota


def _event(
    conn: sqlite3.Connection,
    caller: str,
    *,
    hours_ago: float,
    provider: str = "codex_cli",
    now: datetime,
) -> None:
    conn.execute(
        "INSERT INTO usage_limit_events (provider, caller, detail, detected_at)"
        " VALUES (?, ?, 'usage limit reached', ?)",
        (provider, caller, (now - timedelta(hours=hours_ago)).isoformat()),
    )
    conn.commit()


_NOW = datetime(2026, 6, 10, 20, 0, tzinfo=timezone.utc)


def test_record_and_map_caller(mem_db: sqlite3.Connection) -> None:
    quota.record_usage_limit_event(
        mem_db, "codex_cli", "predict.predict_ticker", detail="quota exceeded",
    )
    rows = mem_db.execute("SELECT provider, caller FROM usage_limit_events").fetchall()
    assert rows == [("codex_cli", "predict.predict_ticker")]

    morning = _NOW.replace(hour=2)
    evening = _NOW.replace(hour=14)
    assert quota.map_caller_to_job("predict.predict_ticker", _NOW) == "run_predictions"
    assert quota.map_caller_to_job("thesis.verify", _NOW) == "thesis_verify"
    assert quota.map_caller_to_job("thesis.extract", _NOW) == "run_predictions"
    assert (
        quota.map_caller_to_job("research.generate_daily", morning)
        == "research_push_morning"
    )
    assert (
        quota.map_caller_to_job("research.generate_daily", evening)
        == "research_push_evening"
    )
    assert quota.map_caller_to_job("unknown.caller", _NOW) is None


def test_leftover_due_after_window_refresh(mem_db: sqlite3.Connection) -> None:
    _event(mem_db, "predict.predict_ticker", hours_ago=6, now=_NOW)
    assert quota.leftover_jobs_due(mem_db, now=_NOW) == ["run_predictions"]


def test_leftover_not_due_inside_window(mem_db: sqlite3.Connection) -> None:
    _event(mem_db, "predict.predict_ticker", hours_ago=2, now=_NOW)
    assert quota.leftover_jobs_due(mem_db, now=_NOW) == []


def test_leftover_expires_after_24h(mem_db: sqlite3.Connection) -> None:
    _event(mem_db, "predict.predict_ticker", hours_ago=30, now=_NOW)
    assert quota.leftover_jobs_due(mem_db, now=_NOW) == []


def test_leftover_skipped_when_job_recovered(mem_db: sqlite3.Connection) -> None:
    _event(mem_db, "predict.predict_ticker", hours_ago=6, now=_NOW)
    job_runs.record_run(
        mem_db, "run_predictions", job_runs.OK,
        finished_at=(_NOW - timedelta(hours=1)).isoformat(),
    )

    assert quota.leftover_jobs_due(mem_db, now=_NOW) == []
    # And the event was consumed so it never re-triggers.
    (retried,) = mem_db.execute(
        "SELECT retried_at FROM usage_limit_events",
    ).fetchone()
    assert retried is not None and "recovered" in retried


def test_leftover_retry_cap(mem_db: sqlite3.Connection) -> None:
    _event(mem_db, "predict.predict_ticker", hours_ago=6, now=_NOW)
    for hours in (3, 2):
        mem_db.execute(
            "INSERT INTO job_runs (job_id, status, trigger, finished_at)"
            " VALUES ('run_predictions', 'error', 'quota_retry', ?)",
            ((_NOW - timedelta(hours=hours)).isoformat(),),
        )
    mem_db.commit()

    assert quota.leftover_jobs_due(mem_db, now=_NOW) == []


def test_leftover_from_credit_shaped_job_error(mem_db: sqlite3.Connection) -> None:
    job_runs.record_run(
        mem_db, "broker_positions_pull", job_runs.ERROR,
        error="pull skipped: codex hit usage limit, try again later",
        finished_at=(_NOW - timedelta(hours=6)).isoformat(),
    )
    # Non-credit errors do not become leftovers.
    job_runs.record_run(
        mem_db, "score_daily", job_runs.ERROR,
        error="KeyError: 'close'",
        finished_at=(_NOW - timedelta(hours=6)).isoformat(),
    )

    assert quota.leftover_jobs_due(mem_db, now=_NOW) == ["broker_positions_pull"]


def test_mark_job_events_retried(mem_db: sqlite3.Connection) -> None:
    _event(mem_db, "predict.predict_ticker", hours_ago=6, now=_NOW)
    _event(mem_db, "macro.digest", hours_ago=6, now=_NOW)

    quota.mark_job_events_retried(mem_db, "run_predictions", now=_NOW)

    rows = dict(mem_db.execute(
        "SELECT caller, retried_at FROM usage_limit_events",
    ).fetchall())
    assert rows["predict.predict_ticker"] is not None
    assert rows["macro.digest"] is None
    assert quota.leftover_jobs_due(mem_db, now=_NOW) == ["macro_digest"]


def test_usage_windows_bucketing(mem_db: sqlite3.Connection) -> None:
    base = _NOW.replace(hour=10, minute=1)  # 10:00 UTC -> window starting 10:00
    for offset_hours, provider in ((0, "codex_cli"), (1, "codex_cli"), (6, "claude_cli")):
        mem_db.execute(
            "INSERT INTO llm_calls (model, provider, input_tokens, output_tokens,"
            " cost_usd, duration_ms, caller, created_at)"
            " VALUES ('m', ?, 100, 10, 0, 1, 'c', ?)",
            (provider, (base + timedelta(hours=offset_hours)).isoformat()),
        )
    mem_db.commit()

    windows = quota.usage_windows(mem_db, days=30)

    codex = [w for w in windows if w["provider"] == "codex_cli"]
    assert len(codex) == 1 and codex[0]["calls"] == 2
    assert codex[0]["input_tokens"] == 200
    assert len([w for w in windows if w["provider"] == "claude_cli"]) == 1


def test_format_windows_report_shows_refresh_eta(
    mem_db: sqlite3.Connection,
) -> None:
    mem_db.execute(
        "INSERT INTO llm_calls (model, provider, input_tokens, output_tokens,"
        " cost_usd, duration_ms, caller, created_at)"
        " VALUES ('m', 'codex_cli', 100, 10, 0, 1, 'c', ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    quota.record_usage_limit_event(
        mem_db, "codex_cli", "predict.predict_ticker", detail="usage limit",
    )

    report = quota.format_windows_report(mem_db, days=2)

    assert "5h UTC window" in report
    assert "window refresh ~" in report
    assert "codex_cli" in report


def test_claude_cli_limit_detection_persists_event(
    mem_db, monkeypatch,
) -> None:
    """A claude -p usage-limit apology raises AND records a usage_limit_event."""
    from unittest.mock import MagicMock, patch

    import pytest as pytest_mod

    from stock.config import Settings, get_settings
    from stock.models import ClaudeCliClient, ClaudeCliUnavailable

    monkeypatch.setattr(
        "stock.models.get_settings", lambda: Settings(_env_file=None),
    )
    get_settings.cache_clear()

    proc = MagicMock(
        returncode=1, stdout="",
        stderr="You've reached your usage limit. Your limit will reset at 3am.",
    )
    with patch("subprocess.run", return_value=proc):
        client = ClaudeCliClient()
        with pytest_mod.raises(ClaudeCliUnavailable, match="usage limit"):
            client.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="claude-fable-5", max_tokens=10,
                conn=mem_db, caller="research.generate_daily",
            )

    rows = mem_db.execute(
        "SELECT provider, caller FROM usage_limit_events",
    ).fetchall()
    assert rows == [("claude_cli", "research.generate_daily")]
    get_settings.cache_clear()


def test_claude_cli_long_output_not_flagged_as_limit(mem_db, monkeypatch) -> None:
    """A long research note containing 'rate limit' is NOT a usage-limit event."""
    from unittest.mock import MagicMock, patch

    from stock.config import Settings, get_settings
    from stock.models import ClaudeCliClient

    monkeypatch.setattr(
        "stock.models.get_settings", lambda: Settings(_env_file=None),
    )
    get_settings.cache_clear()

    body = ("Fed policy and the rate limit debate... " * 40).strip()  # >500 chars
    proc = MagicMock(returncode=0, stdout=body, stderr="")
    with patch("subprocess.run", return_value=proc):
        client = ClaudeCliClient()
        resp = client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="claude-fable-5", max_tokens=10,
            conn=mem_db, caller="research.generate_daily",
        )

    assert resp.content == body
    assert mem_db.execute("SELECT COUNT(*) FROM usage_limit_events").fetchone() == (0,)
    get_settings.cache_clear()
