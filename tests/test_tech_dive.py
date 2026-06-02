"""tests.test_tech_dive -- F43 4-round structured deep-dive."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from stock import db, tech_dive
from stock.tech_dive import (
    ROUND_PROMPTS,
    ChokepointScore,
    TechDive,
    TechDiveRound,
    _build_round_prompt,
    _parse_chokepoint_scores,
    format_chokepoint_leaderboard_block,
    persist,
    recent_dives,
    render_markdown,
    run_tech_dive,
    top_chokepoint_dives,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    return db.get_conn(":memory:")


def test_round_prompts_define_5_rounds() -> None:
    """Boss-spec: 5 rounds (tech / business / chain / synthesis / chokepoint_score)."""
    labels = [label for label, _ in ROUND_PROMPTS]
    assert labels == [
        "tech_loop", "business_loop", "company_chain", "synthesis", "chokepoint_score",
    ]


def test_run_tech_dive_executes_all_rounds(conn: sqlite3.Connection) -> None:
    """Each round consumes one LLM call; transcript accumulates; score parses."""
    responses = iter([
        "Round 1: tech loop content with pros and cons.",
        "Round 2: business loop with revenue flow.",
        "Round 3: 公司一 (300456.SZ), 公司二, 公司三.",
        "Round 4: falsification + synthesis. Not financial advice.",
        "Round 5: scoring.\nSCORES: trend=8 bottleneck=7 validation=6 valuation=7 risk=2 => composite=9.99\nNot financial advice.",
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
    assert len(dive.rounds) == 5
    assert dive.rounds[0].label == "tech_loop"
    assert dive.rounds[2].label == "company_chain"
    assert dive.rounds[4].label == "chokepoint_score"
    assert "300456.SZ" in dive.rounds[2].output
    assert "Not financial advice" in dive.rounds[3].output
    # Chokepoint score parsed; composite recomputed SERVER-SIDE (ignores the
    # model's bogus 9.99): 8*.25+7*.25+6*.25+7*.15-2*.15 = 5.25+0.75 = 6.0
    assert dive.chokepoint is not None
    assert dive.chokepoint.trend == 8
    assert dive.chokepoint.composite == 6.0


def test_run_tech_dive_stops_on_cost_ceiling(conn: sqlite3.Connection) -> None:
    """Ceiling mid-dive returns whatever rounds completed; no exception."""
    from stock.models import ChatResponse, CostCeilingError

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


def test_parse_chokepoint_scores_recomputes_composite() -> None:
    """Composite is recomputed from clamped dims; the model's number is ignored."""
    text = (
        "blah blah\n"
        "SCORES: trend=10 bottleneck=10 validation=10 valuation=10 risk=0 => composite=0.01\n"
        "Not financial advice."
    )
    score = _parse_chokepoint_scores(text)
    assert score is not None
    # 10*.25*3 + 10*.15 - 0 = 7.5 + 1.5 = 9.0  (NOT the bogus 0.01)
    assert score.composite == 9.0


def test_parse_chokepoint_scores_clamps_out_of_range() -> None:
    """Dimensions outside 0-10 are clamped before the composite is computed."""
    text = "SCORES: trend=15 bottleneck=-3 validation=5 valuation=5 risk=20 => composite=99"
    score = _parse_chokepoint_scores(text)
    assert score is not None
    assert score.trend == 10  # clamped from 15
    assert score.bottleneck == 0  # clamped from -3
    assert score.risk == 10  # clamped from 20
    # 10*.25 + 0*.25 + 5*.25 + 5*.15 - 10*.15 = 2.5+1.25+0.75-1.5 = 3.0
    assert score.composite == 3.0


def test_parse_chokepoint_scores_missing_returns_none() -> None:
    """No SCORES line -> None (the dive still persists with NULL score columns)."""
    assert _parse_chokepoint_scores("just prose, no score line here") is None


def test_persist_writes_chokepoint_columns_and_phase(conn: sqlite3.Connection) -> None:
    dive = TechDive(
        topic="scored topic", sector="ai_demand", language="zh",
        rounds=[TechDiveRound(round_num=1, label="chokepoint_score", output="x")],
        created_at="2026-06-01T22:00:00+00:00",
        phase="emerging",
        chokepoint=ChokepointScore(
            trend=8, bottleneck=7, validation=6, valuation=7, risk=2, composite=6.0,
        ),
    )
    rid = persist(conn, dive)
    row = conn.execute(
        "SELECT phase, score_trend, score_risk, score_composite"
        " FROM tech_dive_runs WHERE research_id = ?", (rid,),
    ).fetchone()
    assert row == ("emerging", 8, 2, 6.0)


def test_persist_without_score_leaves_columns_null(conn: sqlite3.Connection) -> None:
    dive = TechDive(
        topic="unscored", sector="information", language="zh",
        rounds=[TechDiveRound(round_num=1, label="tech_loop", output="x")],
        created_at="2026-06-01T22:00:00+00:00",
    )
    rid = persist(conn, dive)
    row = conn.execute(
        "SELECT phase, score_composite FROM tech_dive_runs WHERE research_id = ?",
        (rid,),
    ).fetchone()
    assert row == (None, None)


def test_leaderboard_orders_by_composite_desc(conn: sqlite3.Connection) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    for topic, composite in [("low", 3.0), ("high", 8.5), ("mid", 6.0)]:
        persist(conn, TechDive(
            topic=topic, sector="ai_demand", language="zh",
            rounds=[TechDiveRound(round_num=1, label="chokepoint_score", output="x")],
            created_at=now_iso, phase="emerging",
            chokepoint=ChokepointScore(
                trend=int(composite), bottleneck=5, validation=5,
                valuation=5, risk=1, composite=composite,
            ),
        ))
    rows = top_chokepoint_dives(conn, days=1, limit=10)
    assert [r["topic"] for r in rows] == ["high", "mid", "low"]
    block = format_chokepoint_leaderboard_block(conn, days=1)
    assert "Cross-field research-priority" in block
    assert block.index("high") < block.index("low")


def test_leaderboard_empty_returns_empty_string(conn: sqlite3.Connection) -> None:
    assert format_chokepoint_leaderboard_block(conn, days=1) == ""


def test_buyer_side_prompt_reinterprets_bottleneck_as_moat() -> None:
    """ai_demand sector -> dimension 2 is scored as moat/defensibility."""
    _, instructions = ROUND_PROMPTS[-1]
    prompt = _build_round_prompt(
        topic="t", sector="ai_demand", prior=[],
        label="chokepoint_score", instructions=instructions,
        language="zh", phase="emerging",
    )
    assert "moat" in prompt.lower()
    assert "BUYER side" in prompt


def test_early_phase_prompt_uses_option_value() -> None:
    """early/emerging phase -> validation+valuation scored on option-value basis."""
    _, instructions = ROUND_PROMPTS[-1]
    early = _build_round_prompt(
        topic="t", sector="space_tech", prior=[],
        label="chokepoint_score", instructions=instructions,
        language="zh", phase="early",
    )
    assert "OPTION-VALUE" in early
    assert "HIGH VARIANCE" in early
    # mature phase -> no early-phase guidance injected
    mature = _build_round_prompt(
        topic="t", sector="information", prior=[],
        label="chokepoint_score", instructions=instructions,
        language="zh", phase="mature",
    )
    assert "OPTION-VALUE" not in mature
