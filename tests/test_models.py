"""tests.test_models -- LLM client wrapper tests."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock.config import Settings
from stock.models import (
    ChatMessage,
    ChatResponse,
    CostCeilingError,
    LLMClient,
    check_cost_ceiling,
    get_client,
    parse_llm_json,
)


def test_get_client_minimax(env_settings: Settings) -> None:
    """get_client('minimax') returns a minimax-backed client."""
    with patch("stock.models.openai.OpenAI"):
        client = get_client("minimax")
    assert client.provider == "minimax"


def test_get_client_claude(env_settings: Settings) -> None:
    """get_client('claude') returns a claude-backed client."""
    with patch("stock.models.anthropic.Anthropic"):
        client = get_client("claude")
    assert client.provider == "claude"


def test_get_client_unknown_raises(env_settings: Settings) -> None:
    """Unknown provider raises ValueError."""
    with pytest.raises(ValueError, match="Unknown provider"):
        get_client("unknown")


def test_empty_api_key_raises() -> None:
    """Empty API key raises ValueError."""
    with pytest.raises(ValueError, match="API key.*empty"):
        LLMClient("minimax", "")


def test_chat_minimax_logs_call(
    env_settings: Settings, mem_db: sqlite3.Connection
) -> None:
    """MiniMax chat call creates a row in llm_calls."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"test": "data"}'
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50

    with patch("stock.models.openai.OpenAI") as mock_openai:
        mock_oa_client = MagicMock()
        mock_openai.return_value = mock_oa_client
        mock_oa_client.chat.completions.create.return_value = mock_response

        client = LLMClient("minimax", "test-key")
        messages: list[ChatMessage] = [{"role": "user", "content": "test"}]
        client.chat(messages, "MiniMax-M1-80k", 100, mem_db, "test_caller")

    row = mem_db.execute("SELECT * FROM llm_calls").fetchone()
    assert row is not None
    assert row[1] == "MiniMax-M1-80k"
    assert row[2] == "minimax"
    assert row[7] == "test_caller"


def test_chat_returns_chat_response(
    env_settings: Settings, mem_db: sqlite3.Connection
) -> None:
    """chat() returns a properly populated ChatResponse."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"result": "ok"}'
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50

    with patch("stock.models.openai.OpenAI") as mock_openai:
        mock_oa_client = MagicMock()
        mock_openai.return_value = mock_oa_client
        mock_oa_client.chat.completions.create.return_value = mock_response

        client = LLMClient("minimax", "test-key")
        messages: list[ChatMessage] = [{"role": "user", "content": "test"}]
        result = client.chat(messages, "MiniMax-M1-80k", 100, mem_db, "test")

    assert isinstance(result, ChatResponse)
    assert result.content == '{"result": "ok"}'
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.model == "MiniMax-M1-80k"
    assert result.cost_usd > 0


def test_cost_ceiling_blocks_when_exceeded(
    env_settings: Settings, mem_db: sqlite3.Connection
) -> None:
    """CostCeilingError raised when today's spend meets the ceiling."""
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO llm_calls (model, provider, input_tokens, output_tokens,"
        " cost_usd, duration_ms, caller, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("test", "test", 0, 0, 1.50, 0, "test", now),
    )
    mem_db.commit()

    with pytest.raises(CostCeilingError):
        check_cost_ceiling(mem_db, env_settings)


def test_cost_ceiling_allows_when_under(
    env_settings: Settings, mem_db: sqlite3.Connection
) -> None:
    """No error when today's spend is below the ceiling."""
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO llm_calls (model, provider, input_tokens, output_tokens,"
        " cost_usd, duration_ms, caller, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("test", "test", 0, 0, 0.10, 0, "test", now),
    )
    mem_db.commit()

    total = check_cost_ceiling(mem_db, env_settings)
    assert total == pytest.approx(0.10)


def test_cost_ceiling_only_counts_today(
    env_settings: Settings, mem_db: sqlite3.Connection
) -> None:
    """Yesterday's spend does not count against today's ceiling."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    mem_db.execute(
        "INSERT INTO llm_calls (model, provider, input_tokens, output_tokens,"
        " cost_usd, duration_ms, caller, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("test", "test", 0, 0, 5.00, 0, "test", yesterday),
    )
    mem_db.commit()

    total = check_cost_ceiling(mem_db, env_settings)
    assert total == pytest.approx(0.0)


def test_parse_llm_json_plain() -> None:
    """Plain JSON string parses correctly."""
    result = parse_llm_json('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_llm_json_code_fences() -> None:
    """JSON wrapped in markdown code fences parses correctly."""
    raw = '```json\n{"key": "value"}\n```'
    result = parse_llm_json(raw)
    assert result == {"key": "value"}


def test_parse_llm_json_bare_fences() -> None:
    """JSON wrapped in bare code fences (no language tag) parses correctly."""
    raw = '```\n{"key": "value"}\n```'
    result = parse_llm_json(raw)
    assert result == {"key": "value"}


def test_parse_llm_json_invalid() -> None:
    """Non-JSON input raises an exception."""
    with pytest.raises(Exception):
        parse_llm_json("not json at all")
