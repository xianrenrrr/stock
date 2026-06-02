"""tests.test_features -- feature extraction tests."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock.config import Settings
from stock.features import (
    FeatureResult,
    NewsFeatures,
    extract_features,
    extract_single,
    get_unfeatured_news,
)
from stock.models import ChatResponse, CostCeilingError

VALID_FEATURE_JSON: str = json.dumps({
    "sentiment": "bullish",
    "novelty": "high",
    "catalyst_type": "earnings",
    "time_sensitivity": "days",
    "summary": "Strong earnings beat expectations.",
})


def _mock_chat_response(content: str = VALID_FEATURE_JSON) -> ChatResponse:
    return ChatResponse(
        content=content,
        input_tokens=50,
        output_tokens=30,
        model="MiniMax-M1-80k",
        cost_usd=0.001,
    )


def _insert_news(
    conn: sqlite3.Connection, url_suffix: str = "test"
) -> int:
    """Insert a test news row and return its id."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "AAPL", "test", f"https://example.com/{url_suffix}",
            "Test headline", "Test body content", now, now,
        ),
    )
    conn.commit()
    return cursor.lastrowid or 0


@patch("stock.features.load_feature_prompt", return_value="{ticker} {title} {body}")
def test_extract_single_parses_valid_json(
    _mock_prompt: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """Valid JSON response is parsed and stored in the features table."""
    news_id = _insert_news(mem_db)

    with patch("stock.features.get_utility_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.return_value = _mock_chat_response()

        result = extract_single(news_id, "Test headline", "Test body", "AAPL", mem_db)

    assert isinstance(result, FeatureResult)
    assert result.features.sentiment == "bullish"
    assert result.news_id == news_id

    row = mem_db.execute(
        "SELECT * FROM features WHERE news_id = ?", (news_id,)
    ).fetchone()
    assert row is not None


@patch("stock.features.load_feature_prompt", return_value="{ticker} {title} {body}")
def test_extract_single_handles_code_fences(
    _mock_prompt: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """JSON wrapped in code fences is parsed correctly."""
    news_id = _insert_news(mem_db)

    fenced = f"```json\n{VALID_FEATURE_JSON}\n```"
    with patch("stock.features.get_utility_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.return_value = _mock_chat_response(fenced)

        result = extract_single(news_id, "Test headline", "Test body", "AAPL", mem_db)

    assert result.features.sentiment == "bullish"


@patch("stock.features.load_feature_prompt", return_value="{ticker} {title} {body}")
def test_extract_single_rejects_invalid_json(
    _mock_prompt: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """Garbage LLM output raises an exception."""
    news_id = _insert_news(mem_db)

    with patch("stock.features.get_utility_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.return_value = _mock_chat_response("not valid json")

        with pytest.raises((ValueError, json.JSONDecodeError)):
            extract_single(news_id, "Test headline", "Test body", "AAPL", mem_db)


def test_extract_features_skips_already_featured(
    env_settings: Settings, mem_db: sqlite3.Connection
) -> None:
    """Already-featured news is not reprocessed."""
    news_id = _insert_news(mem_db)
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO features (news_id, json, model, ts) VALUES (?, ?, ?, ?)",
        (news_id, VALID_FEATURE_JSON, "MiniMax-M1-80k", now),
    )
    mem_db.commit()

    with patch("stock.features.get_utility_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client

        results = extract_features("AAPL", mem_db)

    assert len(results) == 0
    mock_client.chat.assert_not_called()


@patch("stock.features.load_feature_prompt", return_value="{ticker} {title} {body}")
def test_extract_features_processes_unfeatured(
    _mock_prompt: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """Only unfeatured news items trigger LLM calls."""
    now = datetime.now(timezone.utc).isoformat()

    # Insert featured news
    cursor = mem_db.execute(
        "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("AAPL", "test", "https://example.com/feat", "Featured", "body", now, now),
    )
    featured_id = cursor.lastrowid
    mem_db.execute(
        "INSERT INTO features (news_id, json, model, ts) VALUES (?, ?, ?, ?)",
        (featured_id, VALID_FEATURE_JSON, "MiniMax-M1-80k", now),
    )

    # Insert unfeatured news
    mem_db.execute(
        "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("AAPL", "test", "https://example.com/unfeat", "Unfeatured", "body", now, now),
    )
    mem_db.commit()

    with patch("stock.features.get_utility_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.return_value = _mock_chat_response()

        results = extract_features("AAPL", mem_db)

    assert len(results) == 1
    assert mock_client.chat.call_count == 1


@patch("stock.features.load_feature_prompt", return_value="{ticker} {title} {body}")
def test_extract_features_stops_on_cost_ceiling(
    _mock_prompt: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """Cost ceiling stops extraction mid-batch and returns partial results."""
    now = datetime.now(timezone.utc).isoformat()
    for idx in range(3):
        mem_db.execute(
            "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", "test", f"https://example.com/ceil-{idx}", f"News {idx}",
             "body", now, now),
        )
    mem_db.commit()

    with patch("stock.features.get_utility_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.side_effect = [
            _mock_chat_response(),
            CostCeilingError("ceiling"),
        ]

        results = extract_features("AAPL", mem_db)

    assert len(results) == 1


def test_get_unfeatured_news_returns_correct_rows(
    env_settings: Settings, mem_db: sqlite3.Connection
) -> None:
    """get_unfeatured_news returns only news without features."""
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("AAPL", "test", "https://example.com/a", "Has features", "body", now, now),
    )
    mem_db.execute(
        "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("AAPL", "test", "https://example.com/b", "No features", "body", now, now),
    )
    mem_db.execute(
        "INSERT INTO features (news_id, json, model, ts) VALUES (?, ?, ?, ?)",
        (1, VALID_FEATURE_JSON, "test", now),
    )
    mem_db.commit()

    rows = get_unfeatured_news("AAPL", mem_db)
    assert len(rows) == 1
    assert rows[0][1] == "No features"


def test_news_features_model_validates() -> None:
    """NewsFeatures accepts valid string-based fields."""
    feat = NewsFeatures(
        sentiment="bullish",
        novelty="high",
        catalyst_type="earnings",
        time_sensitivity="days",
        summary="Test summary.",
    )
    assert feat.sentiment == "bullish"
    assert feat.catalyst_type == "earnings"
