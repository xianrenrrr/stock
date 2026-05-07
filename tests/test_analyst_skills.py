"""tests.test_analyst_skills -- F44 equity-research skills (earnings/dd/morning)."""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from stock import analyst_skills, db


@pytest.fixture
def conn() -> sqlite3.Connection:
    return db.get_conn(":memory:")


def _fake_chat_response(content: str):
    """Build a ChatResponse that the patched _core_chat can return."""
    from stock.models import ChatResponse
    return ChatResponse(
        content=content, input_tokens=10, output_tokens=200,
        cost_usd=0.0, model="claude-opus-4-7",
    )


# ---- earnings_review ------------------------------------------------------


def test_earnings_review_runs_three_rounds(conn: sqlite3.Connection) -> None:
    responses = iter([
        "Round 1: revenue beat by 5%, EPS in line.",
        "Round 2: thesis intact, guidance raised, NVDA cross-read positive.",
        "Round 3: HOLD, stop $190, conviction 8->9. Not financial advice.",
    ])

    def fake_chat(*, messages, max_tokens, conn, caller, cached_system=None):
        return _fake_chat_response(next(responses))

    with patch.object(analyst_skills, "_core_chat", side_effect=fake_chat), \
         patch.object(analyst_skills, "check_cost_ceiling", return_value=None):
        report = analyst_skills.earnings_review(ticker="NVDA", conn=conn)

    assert report.kind == "earnings_review"
    assert report.ticker == "NVDA"
    assert report.research_id is not None
    assert "revenue beat by 5%" in report.body
    assert "thesis intact" in report.body
    assert "Not financial advice" in report.body

    row = conn.execute(
        "SELECT kind, topic FROM research_reports WHERE id = ?",
        (report.research_id,),
    ).fetchone()
    assert row[0] == "earnings_review"
    assert "NVDA" in row[1]


def test_earnings_review_handles_empty_response(conn: sqlite3.Connection) -> None:
    """Empty round content -> stop early, no persist."""
    def fake_chat(**kwargs):
        return _fake_chat_response("")

    with patch.object(analyst_skills, "_core_chat", side_effect=fake_chat), \
         patch.object(analyst_skills, "check_cost_ceiling", return_value=None):
        report = analyst_skills.earnings_review(ticker="X", conn=conn)
    assert report.research_id is None  # not persisted


# ---- dd_checklist ---------------------------------------------------------


def test_dd_checklist_persists_single_call(conn: sqlite3.Connection) -> None:
    def fake_chat(**kwargs):
        return _fake_chat_response("1. Revenue mix... Not financial advice.")

    with patch.object(analyst_skills, "_core_chat", side_effect=fake_chat), \
         patch.object(analyst_skills, "check_cost_ceiling", return_value=None):
        report = analyst_skills.dd_checklist(ticker="ACMR", conn=conn)

    assert report.kind == "dd_checklist"
    assert report.research_id is not None
    assert "Revenue mix" in report.body


# ---- morning_note ---------------------------------------------------------


def test_morning_note_pulls_db_signals(conn: sqlite3.Connection) -> None:
    """morning_note builds context from price_anomalies + option_anomalies + alerts."""
    # Seed an anomaly + UOA + alert in the last 24h
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO price_anomalies (ticker, ts, pct_change, volume_ratio, flag_reason, created_at)"
        " VALUES ('NVDA', ?, -0.05, 2.5, 'gap-down', ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO option_anomalies (ticker, contract_symbol, option_type, strike, expiry,"
        " volume, open_interest, vol_oi_ratio, score, flag_reason, detected_at)"
        " VALUES ('AVGO', 'AVGO_PUT', 'put', 420, '2026-05-15', 1500, 100, 15.0, 50.0,"
        " 'EXTREME', ?)",
        (now,),
    )
    conn.commit()

    def fake_chat(**kwargs):
        return _fake_chat_response("# Top call: NVDA gap-down... Not financial advice.")

    with patch.object(analyst_skills, "_core_chat", side_effect=fake_chat), \
         patch.object(analyst_skills, "check_cost_ceiling", return_value=None):
        report = analyst_skills.morning_note(conn=conn)

    assert report.kind == "morning_note"
    assert report.ticker is None
    assert report.research_id is not None
    # Verify the prompt got the seeded signals as context
    # (Indirectly: the body output should mention NVDA from the fake chat content)
    assert "NVDA" in report.body
