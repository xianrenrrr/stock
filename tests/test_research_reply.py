"""tests.test_research_reply -- direct reply grounding helpers."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from stock import db
from stock.research import (
    _build_accuracy_context_block,
    _build_live_quote_block,
    _detect_tickers_in_text,
    _known_reply_tickers,
)


def test_detect_tickers_accepts_lowercase_known_symbol() -> None:
    """Lowercase ticker mentions are valid when the ticker is known."""
    found = _detect_tickers_in_text(
        "check crdo after report, not the stale price",
        known_tickers={"CRDO"},
    )
    assert found == ["CRDO"]


def test_detect_tickers_does_not_promote_lowercase_words() -> None:
    """Known-ticker gate prevents ordinary words from becoming symbols."""
    found = _detect_tickers_in_text(
        "check price after report",
        known_tickers={"CRDO"},
    )
    assert found == []


def test_detect_tickers_accepts_lowercase_known_korean_suffix() -> None:
    """Known suffixed symbols can be matched case-insensitively."""
    found = _detect_tickers_in_text(
        "check 000660.ks not bare KS",
        known_tickers={"000660.KS"},
    )
    assert found == ["000660.KS"]


def test_live_quote_block_uses_known_lowercase_ticker() -> None:
    """Reply context includes quote-style data for lowercase known tickers."""
    conn: sqlite3.Connection = db.get_conn(":memory:")
    conn.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES ('CRDO', 'now', 1)"
    )
    conn.commit()

    out = _build_live_quote_block(
        conn,
        boss_reply="look at crdo live price today",
        provider=lambda ticker: (97.0, 114.0, -0.1491228),
    )

    assert "PRIMARY price grounding" in out
    assert "CRDO: last=$97.00" in out
    assert "change=-14.91%" in out


def test_known_reply_tickers_reads_watchlist_and_holdings() -> None:
    """Case-insensitive matching is limited to symbols already known locally."""
    conn: sqlite3.Connection = db.get_conn(":memory:")
    conn.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES ('CRDO', 'now', 1)"
    )
    conn.execute(
        "INSERT INTO holdings (ticker, qty, cost_basis, opened_at, active, updated_at)"
        " VALUES ('RKLB', 1, 10, 'now', 1, 'now')"
    )
    conn.commit()

    assert {"CRDO", "RKLB"}.issubset(_known_reply_tickers(conn))


def test_accuracy_context_block_answers_forecast_accuracy_question() -> None:
    """Forecast/hit-rate questions get local daily-vs-weekly scoreboard context."""
    conn: sqlite3.Connection = db.get_conn(":memory:")
    now = datetime.now(timezone.utc).isoformat()
    for ticker, horizon, hit in (
        ("AAPL", 390, 1),
        ("MSFT", 390, 0),
        ("NVDA", 1950, 1),
    ):
        cursor = conn.execute(
            "INSERT INTO predictions (ticker, horizon_minutes, direction, prob_up,"
            " confidence, rationale, key_factors_json, model_used, created_at, due_at)"
            " VALUES (?, ?, 'up', 0.6, 0.6, 'r', '[]', 'test', ?, ?)",
            (ticker, horizon, now, now),
        )
        conn.execute(
            "INSERT INTO outcomes (prediction_id, actual_return, direction_hit,"
            " brier, scored_at) VALUES (?, ?, ?, 0.2, ?)",
            (cursor.lastrowid, 0.01 if hit else -0.01, hit, now),
        )
    conn.commit()

    block = _build_accuracy_context_block(
        conn, boss_reply="how is daily and weekly forecast accuracy"
    )

    assert "Forecast accuracy context" in block
    assert "last 30d" in block
    assert "daily: n=2/2, hit=50.0%" in block
    assert "weekly: n=1/1, hit=100.0%" in block


def test_generate_deep_dive_injects_live_quotes(monkeypatch) -> None:
    """Deep dives prepend live-quote grounding into the prompt's extra context."""
    from stock import research
    from stock.models import ChatResponse

    conn: sqlite3.Connection = db.get_conn(":memory:")
    captured: dict[str, str] = {}

    def fake_core_chat(*, messages, max_tokens, conn, caller, cached_system=None):
        captured["prompt"] = messages[0]["content"]
        return ChatResponse(
            content="deep dive body. Not financial advice.",
            input_tokens=1, output_tokens=1, cost_usd=0.0, model="x",
        )

    monkeypatch.setattr(research, "_core_chat", fake_core_chat)
    monkeypatch.setattr(
        research, "_build_live_quote_block",
        lambda conn, *, boss_reply: "LIVEQUOTE: NVDA last=$123.45",
    )

    report = research.generate_deep_dive(conn, topic="NVDA outlook")

    assert report.kind == "deep_dive"
    # The live-quote grounding made it into the prompt sent to the model.
    assert "LIVEQUOTE: NVDA last=$123.45" in captured["prompt"]


def test_generate_deep_dive_runs_recursive_next_steps_followups(monkeypatch) -> None:
    """A DD report with Next Steps gets three local amendments before persistence."""
    from stock import research
    from stock.models import ChatResponse

    conn: sqlite3.Connection = db.get_conn(":memory:")
    calls: list[str] = []

    def fake_core_chat(*, messages, max_tokens, conn, caller, cached_system=None):
        calls.append(caller)
        if caller == "research.generate_deep_dive.followup":
            assert "Do not repeat the report" in messages[0]["content"]
            assert "pull customer checks" in messages[0]["content"]
            pass_number = len(calls) - 1
            assert f"pass {pass_number} of 3" in messages[0]["content"]
            return ChatResponse(
                content=(
                    f"Follow-up pass {pass_number}: customer checks support the "
                    "thesis. Remaining Next Steps: monitor backlog. "
                    "Not financial advice."
                ),
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.02,
                model="x",
            )
        return ChatResponse(
            content=(
                "Initial DD.\n\n"
                "## Next Steps\n"
                "- pull customer checks\n\n"
                "Not financial advice."
            ),
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.03,
            model="x",
        )

    monkeypatch.setattr(research, "_core_chat", fake_core_chat)
    monkeypatch.setattr(research, "_build_live_quote_block", lambda *args, **kwargs: "")

    report = research.generate_deep_dive(conn, topic="NVDA outlook")

    assert calls == [
        "research.generate_deep_dive",
        "research.generate_deep_dive.followup",
        "research.generate_deep_dive.followup",
        "research.generate_deep_dive.followup",
    ]
    assert "Local follow-up research pass 1 / Next-step amendment" in report.body
    assert "Local follow-up research pass 2 / Next-step amendment" in report.body
    assert "Local follow-up research pass 3 / Next-step amendment" in report.body
    assert "Remaining Next Steps: monitor backlog" in report.body
    assert abs(report.cost_usd - 0.09) < 0.000001

    stored = conn.execute(
        "SELECT body, cost_usd FROM research_reports WHERE id = ?",
        (report.research_id,),
    ).fetchone()
    assert stored is not None
    assert "Next-step amendment" in stored[0]
    assert abs(stored[1] - 0.09) < 0.000001
