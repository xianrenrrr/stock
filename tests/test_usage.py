"""tests.test_usage -- LLM usage reporting over llm_calls."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from stock.usage import (
    format_usage_report,
    usage_by_caller,
    usage_by_day,
    usage_by_provider,
)


def _log_call(
    conn: sqlite3.Connection,
    *,
    provider: str,
    caller: str,
    input_tokens: int = 1000,
    output_tokens: int = 100,
    cost: float = 0.0,
    days_ago: int = 0,
) -> None:
    created = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    conn.execute(
        "INSERT INTO llm_calls"
        " (model, provider, input_tokens, output_tokens, cost_usd, duration_ms,"
        " caller, created_at)"
        " VALUES (?, ?, ?, ?, ?, 1500, ?, ?)",
        (f"{provider}-session", provider, input_tokens, output_tokens, cost,
         caller, created),
    )
    conn.commit()


def test_usage_by_provider_aggregates(mem_db: sqlite3.Connection) -> None:
    _log_call(mem_db, provider="codex_cli", caller="predict.predict_ticker")
    _log_call(mem_db, provider="codex_cli", caller="features.extract")
    _log_call(mem_db, provider="claude_cli", caller="predict.predict_ticker")

    rows = usage_by_provider(mem_db, days=7)

    by_provider = {r["provider"]: r for r in rows}
    assert by_provider["codex_cli"]["calls"] == 2
    assert by_provider["codex_cli"]["input_tokens"] == 2000
    assert by_provider["claude_cli"]["calls"] == 1


def test_usage_window_excludes_old_calls(mem_db: sqlite3.Connection) -> None:
    _log_call(mem_db, provider="codex_cli", caller="a", days_ago=10)
    _log_call(mem_db, provider="codex_cli", caller="a", days_ago=0)

    assert usage_by_provider(mem_db, days=7)[0]["calls"] == 1
    assert len(usage_by_day(mem_db, days=7)) == 1


def test_usage_by_caller_orders_by_tokens(mem_db: sqlite3.Connection) -> None:
    _log_call(mem_db, provider="codex_cli", caller="small", input_tokens=10)
    _log_call(mem_db, provider="codex_cli", caller="big", input_tokens=99_000)

    rows = usage_by_caller(mem_db, days=7)
    assert rows[0]["caller"] == "big"


def test_format_usage_report_mentions_fallback_share(
    mem_db: sqlite3.Connection,
) -> None:
    _log_call(mem_db, provider="codex_cli", caller="a")
    _log_call(mem_db, provider="codex_cli", caller="a")
    _log_call(mem_db, provider="codex_cli", caller="a")
    _log_call(mem_db, provider="claude_cli", caller="a")

    report = format_usage_report(mem_db, days=7)

    assert "fallback share: 25%" in report
    assert "codex_cli" in report
    assert "Top callers" in report


def test_format_usage_report_empty_db(mem_db: sqlite3.Connection) -> None:
    assert "No LLM calls" in format_usage_report(mem_db, days=7)
