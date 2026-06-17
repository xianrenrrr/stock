"""tests.test_feedback_router -- feedback categorizer tests with mocked LLM."""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from stock.feedback_router import categorize_feedback
from stock.models import ChatResponse, CostCeilingError


def _stub_response(content: str) -> ChatResponse:
    """Build a fake ChatResponse with arbitrary content."""
    return ChatResponse(
        content=content, input_tokens=10, output_tokens=10,
        model="MiniMax-M2.5-highspeed", cost_usd=0.0,
    )


def test_categorize_deep_dive(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """A research ask is categorized as deep_dive."""
    json_payload = '{"category":"deep_dive","confidence":0.9,"summary":"AVGO dive"}'
    fake_client = MagicMock()
    fake_client.chat = MagicMock(return_value=_stub_response(json_payload))
    monkeypatch.setattr("stock.feedback_router.get_utility_client", lambda: fake_client)

    result = categorize_feedback("do a deep-dive on AVGO", recipient="boss", conn=mem_db)

    assert result.category == "deep_dive"
    assert result.confidence == 0.9


def test_categorize_feature_request(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """A system/product change is categorized as feature_request."""
    json_payload = (
        '{"category":"feature_request","confidence":0.85,"summary":"CN/US split"}'
    )
    fake_client = MagicMock()
    fake_client.chat = MagicMock(return_value=_stub_response(json_payload))
    monkeypatch.setattr("stock.feedback_router.get_utility_client", lambda: fake_client)

    result = categorize_feedback(
        "split the report into CN and US tracks", recipient="boss", conn=mem_db
    )

    assert result.category == "feature_request"
    assert result.confidence == 0.85


def test_categorize_invalid_label_defaults_to_deep_dive(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """An unrecognized category label fails open to deep_dive."""
    json_payload = '{"category":"banana","confidence":0.5}'
    fake_client = MagicMock()
    fake_client.chat = MagicMock(return_value=_stub_response(json_payload))
    monkeypatch.setattr("stock.feedback_router.get_utility_client", lambda: fake_client)

    result = categorize_feedback("???", recipient="boss", conn=mem_db)
    assert result.category == "deep_dive"


def test_categorize_bad_json_defaults_to_deep_dive(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """Non-JSON output degrades to the safe default instead of raising."""
    fake_client = MagicMock()
    fake_client.chat = MagicMock(return_value=_stub_response("definitely not json"))
    monkeypatch.setattr("stock.feedback_router.get_utility_client", lambda: fake_client)

    result = categorize_feedback("anything", recipient="boss", conn=mem_db)
    assert result.category == "deep_dive"
    assert result.confidence == 0.0


def test_categorize_empty_text(mem_db: sqlite3.Connection) -> None:
    """Empty text short-circuits to the safe default without an LLM call."""
    result = categorize_feedback("", recipient="boss", conn=mem_db)
    assert result.category == "deep_dive"


def test_categorize_cost_ceiling(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """CostCeilingError degrades to the safe default without raising."""
    def _raise(conn: sqlite3.Connection, settings: object) -> None:
        raise CostCeilingError("over")

    monkeypatch.setattr("stock.feedback_router.check_cost_ceiling", _raise)

    result = categorize_feedback("hi", recipient="boss", conn=mem_db)
    assert result.category == "deep_dive"
    assert result.confidence == 0.0
