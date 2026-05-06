"""tests.test_qa_deepdive -- F37 progressive Q&A deep-dive engine."""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from stock import db, qa_deepdive
from stock.qa_deepdive import (
    QADeepDive,
    QARound,
    _opening_question,
    _parse_answer_and_followup,
    persist,
    render_markdown,
    run_qa_deepdive,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    """In-memory DB with full schema."""
    return db.get_conn(":memory:")


def test_opening_question_includes_thesis_when_given() -> None:
    q = _opening_question("ACMR", "wet bench domestic monopoly + SAPS clean")
    assert "ACMR" in q
    assert "wet bench" in q
    assert "RIGHT NOW" in q


def test_opening_question_falls_back_when_no_thesis() -> None:
    q = _opening_question("ACMR", "")
    assert "ACMR" in q
    assert "RIGHT NOW" in q


def test_parse_followup_extracts_next_question() -> None:
    text = (
        "The thesis hinges on SMIC capex visibility. Order book is up 40% YoY.\n\n"
        "NEXT_QUESTION: What does ASML's most recent shipment disclosure tell us "
        "about whether SMIC can absorb that capex?"
    )
    answer, q = _parse_answer_and_followup(text)
    assert "thesis hinges" in answer
    assert "NEXT_QUESTION" not in answer
    assert q is not None
    assert "ASML" in q


def test_parse_followup_returns_none_when_missing() -> None:
    text = "This is just a plain answer with no follow-up directive."
    answer, q = _parse_answer_and_followup(text)
    assert answer == text
    assert q is None


def test_parse_followup_rejects_too_short() -> None:
    """Empty / very short follow-ups don't propagate."""
    text = "Some answer.\n\nNEXT_QUESTION: foo"
    _, q = _parse_answer_and_followup(text)
    assert q is None  # below MIN_QUESTION_LENGTH


def test_render_markdown_emits_clean_qa_format() -> None:
    dive = QADeepDive(
        ticker="ACMR", seed_thesis="wet bench monopoly",
        rounds=[
            QARound(round_num=1, question="why now", answer="because capex"),
            QARound(round_num=2, question="capex from whom", answer="SMIC + YMTC"),
        ],
        created_at="2026-05-05T22:00:00+00:00",
    )
    md = render_markdown(dive)
    assert "ACMR 深度问答" in md
    assert "**Seed thesis**: wet bench monopoly" in md
    assert "## Q1: why now" in md
    assert "because capex" in md
    assert "## Q2: capex from whom" in md


def test_run_qa_deepdive_chains_followups(conn: sqlite3.Connection) -> None:
    """Each round consumes the LLM answer + extracts the next question."""
    responses = iter([
        "Answer 1: SMIC capex up 40%.\n\nNEXT_QUESTION: What does ASML say about that?",
        "Answer 2: ASML shipment to SMIC up 60% YoY.\n\nNEXT_QUESTION: Margin impact?",
        "Answer 3: Final round answer about indicators.",
    ])

    def fake_core_chat(*, messages, max_tokens, conn, caller, cached_system=None):
        from stock.models import ChatResponse
        return ChatResponse(
            content=next(responses), input_tokens=10, output_tokens=20,
            cost_usd=0.001, model="claude-opus-4-7",
        )

    with patch.object(qa_deepdive, "_core_chat", side_effect=fake_core_chat), \
         patch.object(qa_deepdive, "check_cost_ceiling", return_value=None):
        dive = run_qa_deepdive(
            ticker="ACMR", seed_thesis="wet bench monopoly",
            conn=conn, rounds=3,
        )

    assert dive.ticker == "ACMR"
    assert len(dive.rounds) == 3
    # Round 2's question came from round 1's NEXT_QUESTION
    assert "ASML" in dive.rounds[1].question
    # Round 3's question came from round 2's NEXT_QUESTION
    assert "Margin impact" in dive.rounds[2].question
    # Answers don't contain the NEXT_QUESTION block
    assert "NEXT_QUESTION" not in dive.rounds[0].answer


def test_run_qa_deepdive_substitutes_when_no_followup(conn: sqlite3.Connection) -> None:
    """Missing NEXT_QUESTION line -> generic counter-arg drill-down inserted."""
    responses = iter([
        "Answer 1 with no follow-up directive.",
        "Answer 2 also no follow-up.",
        "Answer 3 final.",
    ])

    def fake_core_chat(*, messages, max_tokens, conn, caller, cached_system=None):
        from stock.models import ChatResponse
        return ChatResponse(
            content=next(responses), input_tokens=10, output_tokens=20,
            cost_usd=0.001, model="claude-opus-4-7",
        )

    with patch.object(qa_deepdive, "_core_chat", side_effect=fake_core_chat), \
         patch.object(qa_deepdive, "check_cost_ceiling", return_value=None):
        dive = run_qa_deepdive(
            ticker="X", seed_thesis="", conn=conn, rounds=3,
        )

    assert len(dive.rounds) == 3
    # Round 2 question should be the substituted counter-argument prompt
    assert "counter-argument" in dive.rounds[1].question
    # Round 3 (final) question should be the invalidation-criteria one
    assert "invalidate" in dive.rounds[2].question.lower()


def test_run_qa_deepdive_stops_on_cost_ceiling(conn: sqlite3.Connection) -> None:
    """Cost ceiling mid-chain -> return whatever rounds completed; no exception."""
    from stock.models import CostCeilingError, ChatResponse

    call_count = {"n": 0}

    def fake_check(_conn, _settings):
        call_count["n"] += 1
        if call_count["n"] >= 3:
            raise CostCeilingError("ceiling hit")

    def fake_core_chat(*, messages, max_tokens, conn, caller, cached_system=None):
        return ChatResponse(
            content="Round answer.\n\nNEXT_QUESTION: What about competition?",
            input_tokens=10, output_tokens=20, cost_usd=0.001,
            model="claude-opus-4-7",
        )

    with patch.object(qa_deepdive, "_core_chat", side_effect=fake_core_chat), \
         patch.object(qa_deepdive, "check_cost_ceiling", side_effect=fake_check):
        dive = run_qa_deepdive(
            ticker="X", seed_thesis="", conn=conn, rounds=5,
        )

    assert len(dive.rounds) == 2  # 2 succeed, 3rd hits ceiling


def test_persist_writes_research_reports_row(conn: sqlite3.Connection) -> None:
    dive = QADeepDive(
        ticker="ACMR", seed_thesis="x",
        rounds=[QARound(round_num=1, question="Q?", answer="A.")],
        created_at="2026-05-05T22:00:00+00:00",
    )
    rid = persist(conn, dive)
    assert isinstance(rid, int) and rid > 0
    row = conn.execute(
        "SELECT kind, topic, body FROM research_reports WHERE id = ?", (rid,)
    ).fetchone()
    assert row[0] == "deep_qa"
    assert "ACMR" in row[1]
    assert "Q1: Q?" in row[2]
