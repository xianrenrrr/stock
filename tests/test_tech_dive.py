"""tests.test_tech_dive -- F43 4-round structured deep-dive."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from stock import db, tech_dive
from stock.tech_dive import (
    ROUND_PROMPTS,
    TechDive,
    TechDiveRound,
    persist,
    recent_dives,
    render_markdown,
    run_tech_dive,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    return db.get_conn(":memory:")


def test_round_prompts_define_4_rounds() -> None:
    """Boss-spec: 4 rounds (tech / business / chain / synthesis)."""
    labels = [label for label, _ in ROUND_PROMPTS]
    assert labels == ["tech_loop", "business_loop", "company_chain", "synthesis"]


def test_run_tech_dive_executes_all_rounds(conn: sqlite3.Connection) -> None:
    """Each round consumes one LLM call; transcript accumulates."""
    responses = iter([
        "Round 1: tech loop content with pros and cons.",
        "Round 2: business loop with revenue flow.",
        "Round 3: 公司一 (300456.SZ), 公司二, 公司三.",
        "Round 4: falsification + synthesis. Not financial advice.",
    ])

    def fake_core_chat(*, messages, max_tokens, conn, caller, cached_system=None):
        from stock.models import ChatResponse
        return ChatResponse(
            content=next(responses), input_tokens=10, output_tokens=200,
            cost_usd=0.0, model="claude-opus-4-7",
        )

    with patch.object(tech_dive, "_core_chat", side_effect=fake_core_chat), \
         patch.object(tech_dive, "check_cost_ceiling", return_value=None):
        dive = run_tech_dive(
            topic="OCS vs CPO", sector="information", conn=conn,
        )

    assert dive.topic == "OCS vs CPO"
    assert dive.sector == "information"
    assert len(dive.rounds) == 4
    assert dive.rounds[0].label == "tech_loop"
    assert dive.rounds[2].label == "company_chain"
    assert "300456.SZ" in dive.rounds[2].output
    assert "Not financial advice" in dive.rounds[3].output


def test_run_tech_dive_stops_on_cost_ceiling(conn: sqlite3.Connection) -> None:
    """Ceiling mid-dive returns whatever rounds completed; no exception."""
    from stock.models import CostCeilingError, ChatResponse

    call_count = {"n": 0}

    def fake_check(_conn, _settings):
        call_count["n"] += 1
        if call_count["n"] >= 3:
            raise CostCeilingError("ceiling")

    def fake_core_chat(*, messages, max_tokens, conn, caller, cached_system=None):
        return ChatResponse(
            content="round content", input_tokens=10, output_tokens=200,
            cost_usd=0.0, model="claude-opus-4-7",
        )

    with patch.object(tech_dive, "_core_chat", side_effect=fake_core_chat), \
         patch.object(tech_dive, "check_cost_ceiling", side_effect=fake_check):
        dive = run_tech_dive(topic="x", sector="energy", conn=conn)

    assert len(dive.rounds) == 2  # 2 succeed, 3rd hits ceiling


def test_run_tech_dive_handles_empty_response(conn: sqlite3.Connection) -> None:
    """Empty round output -> stop early, return what we have."""
    responses = iter(["good content", "", "should not be reached"])

    def fake_core_chat(*, messages, max_tokens, conn, caller, cached_system=None):
        from stock.models import ChatResponse
        return ChatResponse(
            content=next(responses), input_tokens=10, output_tokens=10,
            cost_usd=0.0, model="claude-opus-4-7",
        )

    with patch.object(tech_dive, "_core_chat", side_effect=fake_core_chat), \
         patch.object(tech_dive, "check_cost_ceiling", return_value=None):
        dive = run_tech_dive(topic="x", sector="information", conn=conn)

    assert len(dive.rounds) == 1


def test_render_markdown_emits_structured_report() -> None:
    dive = TechDive(
        topic="OCS vs CPO", sector="information", language="zh-en",
        rounds=[
            TechDiveRound(round_num=1, label="tech_loop", output="tech content"),
            TechDiveRound(round_num=2, label="business_loop", output="biz content"),
        ],
        created_at="2026-05-06T22:00:00+00:00",
    )
    md = render_markdown(dive)
    assert "技术深挖" in md
    assert "OCS vs CPO" in md
    assert "tech content" in md
    assert "biz content" in md
    assert "Sector: information" in md


def test_persist_writes_both_tables(conn: sqlite3.Connection) -> None:
    dive = TechDive(
        topic="OCS test", sector="information", language="zh-en",
        rounds=[TechDiveRound(round_num=1, label="tech_loop", output="x")],
        created_at="2026-05-06T22:00:00+00:00",
    )
    rid = persist(conn, dive)
    assert rid > 0
    rr = conn.execute("SELECT kind, topic FROM research_reports WHERE id = ?", (rid,)).fetchone()
    assert rr == ("tech_dive", "技术深挖: OCS test")
    tdr = conn.execute("SELECT topic, sector, rounds FROM tech_dive_runs WHERE research_id = ?", (rid,)).fetchone()
    assert tdr == ("OCS test", "information", 1)


def test_recent_dives_returns_within_window(conn: sqlite3.Connection) -> None:
    # Use a live timestamp so the SQL `datetime('now', '-N days')` window
    # in recent_dives() always includes this row. A hard-coded date drifts
    # out of the window once wall-clock time moves past it.
    now_iso = datetime.now(timezone.utc).isoformat()
    dive = TechDive(
        topic="t", sector="energy", language="zh-en",
        rounds=[TechDiveRound(round_num=1, label="x", output="x")],
        created_at=now_iso,
    )
    persist(conn, dive)
    rows = recent_dives(conn, days=1, limit=5)
    assert len(rows) == 1
    assert rows[0]["topic"] == "t"
    assert rows[0]["sector"] == "energy"
