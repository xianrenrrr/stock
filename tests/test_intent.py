"""tests.test_intent -- intent classifier tests with mocked LLM."""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from stock import intent
from stock.intent import IntentResult, classify
from stock.models import ChatResponse, CostCeilingError


def _stub_response(content: str) -> ChatResponse:
    """Build a fake ChatResponse with arbitrary content."""
    return ChatResponse(
        content=content, input_tokens=10, output_tokens=10,
        model="MiniMax-M2.5-highspeed", cost_usd=0.0,
    )


def test_classify_question(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """Question intent JSON yields IntentResult with intent='question'."""
    json_payload = '{"intent":"question","confidence":0.92,"summary":"asks","suggested_topic":null}'

    fake_client = MagicMock()
    fake_client.chat = MagicMock(return_value=_stub_response(json_payload))
    monkeypatch.setattr("stock.intent.get_client", lambda provider: fake_client)

    result = classify("What's TER doing?", recipient="boss", conn=mem_db)

    assert result.intent == "question"
    assert result.confidence == 0.92


def test_classify_instruction(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """Instruction intent JSON returns suggested_topic when present."""
    json_payload = (
        '{"intent":"instruction","confidence":0.88,"summary":"shorter notes",'
        '"suggested_topic":"shorter weekly summary"}'
    )

    fake_client = MagicMock()
    fake_client.chat = MagicMock(return_value=_stub_response(json_payload))
    monkeypatch.setattr("stock.intent.get_client", lambda provider: fake_client)

    result = classify("shorter notes please", recipient="boss", conn=mem_db)

    assert result.intent == "instruction"
    assert result.suggested_topic == "shorter weekly summary"


def test_classify_ack(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """Ack intent yields confidence + summary; no suggested_topic."""
    json_payload = '{"intent":"ack","confidence":0.95,"summary":"thumbs"}'

    fake_client = MagicMock()
    fake_client.chat = MagicMock(return_value=_stub_response(json_payload))
    monkeypatch.setattr("stock.intent.get_client", lambda provider: fake_client)

    result = classify("good", recipient="boss", conn=mem_db)

    assert result.intent == "ack"


def test_classify_unknown_on_bad_json(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """Non-JSON output collapses to intent='unknown' instead of raising."""
    fake_client = MagicMock()
    fake_client.chat = MagicMock(return_value=_stub_response("definitely not json"))
    monkeypatch.setattr("stock.intent.get_client", lambda provider: fake_client)

    result = classify("???", recipient="boss", conn=mem_db)

    assert result.intent == "unknown"
    assert result.confidence == 0.0


def test_classify_empty_text(mem_db: sqlite3.Connection) -> None:
    """Empty inbound text short-circuits to unknown."""
    result = classify("", recipient="boss", conn=mem_db)
    assert result.intent == "unknown"


def test_classify_cost_ceiling(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """CostCeilingError downgrades to unknown without raising."""
    def _raise(conn: sqlite3.Connection, settings: object) -> None:
        raise CostCeilingError("over")

    monkeypatch.setattr("stock.intent.check_cost_ceiling", _raise)

    result = classify("hi", recipient="boss", conn=mem_db)
    assert result.intent == "unknown"


def test_classify_invalid_intent_label(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """An unknown label string is coerced to 'unknown'."""
    json_payload = '{"intent":"banana","confidence":0.5}'

    fake_client = MagicMock()
    fake_client.chat = MagicMock(return_value=_stub_response(json_payload))
    monkeypatch.setattr("stock.intent.get_client", lambda provider: fake_client)

    result = classify("???", recipient="boss", conn=mem_db)
    assert result.intent == "unknown"
