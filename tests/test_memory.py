"""tests.test_memory -- embedding and retrieval tests."""
from __future__ import annotations

import json
import sqlite3
import struct
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from stock.config import Settings
from stock.memory import (
    RetrievedCase,
    _extract_feature_text,
    _serialize_embedding,
    format_retrieved_cases,
    index_outcome,
    retrieve,
)

FAKE_DIM: int = 384


def _fake_embedding(seed: float = 0.1) -> list[float]:
    """Return a deterministic 384-dim fake embedding."""
    return [seed + i * 0.001 for i in range(FAKE_DIM)]


def _seed_prediction_with_outcome(
    conn: sqlite3.Connection,
    ticker: str,
    direction: str = "up",
    prob_up: float = 0.65,
    actual_return: float = 0.02,
    direction_hit: int = 1,
) -> int:
    """Insert a prediction + outcome pair, return prediction_id."""
    now = "2026-04-15T12:00:00+00:00"
    feature_json = json.dumps({
        "features": [
            {
                "title": "Test news",
                "sentiment": "bullish",
                "catalyst_type": "earnings",
                "time_sensitivity": "days",
                "summary": "Strong results.",
            }
        ],
        "prices": [],
    })

    cursor = conn.execute(
        "INSERT INTO predictions ("
        "  ticker, horizon_minutes, direction, prob_up, prob_up_calibrated,"
        "  expected_return_bps, confidence, rationale, key_factors_json,"
        "  model_used, strategy_arm, rules_version, retrieved_case_ids,"
        "  created_at, due_at, feature_context_json"
        ") VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)",
        (
            ticker, 390, direction, prob_up, 50, 0.7,
            "Test rationale.", '["factor1"]', "MiniMax-M1-80k",
            now, "2026-04-16T21:00:00+00:00", feature_json,
        ),
    )
    prediction_id = cursor.lastrowid or 0

    conn.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (prediction_id, actual_return, direction_hit, 0.12, now),
    )
    conn.commit()
    return prediction_id


@patch("stock.memory._get_model")
def test_embed_returns_correct_dimension(
    mock_model_fn: MagicMock, env_settings: Settings
) -> None:
    """embed() returns a list of 384 floats."""
    from stock.memory import embed

    mock_model = MagicMock()
    mock_model.encode.return_value = np.zeros(FAKE_DIM)
    mock_model_fn.return_value = mock_model

    result = embed("test text")

    assert isinstance(result, list)
    assert len(result) == FAKE_DIM


@patch("stock.memory._get_model")
def test_embed_normalizes_output(
    mock_model_fn: MagicMock, env_settings: Settings
) -> None:
    """embed() passes normalize_embeddings=True to the model."""
    from stock.memory import embed

    mock_model = MagicMock()
    mock_model.encode.return_value = np.zeros(FAKE_DIM)
    mock_model_fn.return_value = mock_model

    embed("test text")

    mock_model.encode.assert_called_once_with("test text", normalize_embeddings=True)


@patch("stock.memory._get_model")
def test_embed_empty_raises(mock_model_fn: MagicMock, env_settings: Settings) -> None:
    """embed('') raises ValueError."""
    from stock.memory import embed

    with pytest.raises(ValueError, match="Cannot embed empty text"):
        embed("")


def test_serialize_deserialize_roundtrip() -> None:
    """Serialized embedding can be deserialized back to original values."""
    original = _fake_embedding(0.5)
    blob = _serialize_embedding(original)

    assert isinstance(blob, bytes)
    assert len(blob) == FAKE_DIM * 4

    restored = list(struct.unpack(f"{FAKE_DIM}f", blob))
    for orig_val, rest_val in zip(original, restored):
        assert abs(orig_val - rest_val) < 1e-6


@patch("stock.memory.embed", return_value=_fake_embedding(0.1))
def test_index_outcome_stores_embedding(
    _mock_embed: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """index_outcome inserts a row into case_embeddings."""
    pred_id = _seed_prediction_with_outcome(mem_db, "AAPL")

    index_outcome(pred_id, mem_db)

    row = mem_db.execute(
        "SELECT prediction_id FROM case_embeddings WHERE prediction_id = ?",
        (pred_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == pred_id


@patch("stock.memory.embed", return_value=_fake_embedding(0.1))
def test_index_outcome_idempotent(
    _mock_embed: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """Calling index_outcome twice for the same prediction does not raise or duplicate."""
    pred_id = _seed_prediction_with_outcome(mem_db, "AAPL")

    index_outcome(pred_id, mem_db)
    index_outcome(pred_id, mem_db)

    count = mem_db.execute(
        "SELECT COUNT(*) FROM case_embeddings WHERE prediction_id = ?",
        (pred_id,),
    ).fetchone()[0]
    assert count == 1


def test_index_outcome_raises_missing_prediction(
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """ValueError raised when prediction does not exist."""
    with pytest.raises(ValueError, match="Prediction 999 not found"):
        index_outcome(999, mem_db)


@patch("stock.memory.embed", return_value=_fake_embedding(0.1))
def test_index_outcome_raises_missing_outcome(
    _mock_embed: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """ValueError raised when outcome does not exist for prediction."""
    now = "2026-04-15T12:00:00+00:00"
    cursor = mem_db.execute(
        "INSERT INTO predictions ("
        "  ticker, horizon_minutes, direction, prob_up, prob_up_calibrated,"
        "  expected_return_bps, confidence, rationale, key_factors_json,"
        "  model_used, strategy_arm, rules_version, retrieved_case_ids,"
        "  created_at, due_at, feature_context_json"
        ") VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)",
        (
            "AAPL", 390, "up", 0.65, 50, 0.7,
            "Test.", '["f"]', "MiniMax-M1-80k",
            now, "2026-04-16T21:00:00+00:00", None,
        ),
    )
    mem_db.commit()
    pred_id = cursor.lastrowid or 0

    with pytest.raises(ValueError, match=f"Outcome for prediction {pred_id} not found"):
        index_outcome(pred_id, mem_db)


@patch("stock.memory.embed")
def test_retrieve_returns_k_cases(
    mock_embed: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """retrieve returns at most k cases for a ticker."""
    # Insert 7 predictions with outcomes and index them
    pred_ids: list[int] = []
    for idx in range(7):
        mock_embed.return_value = _fake_embedding(0.1 + idx * 0.01)
        pid = _seed_prediction_with_outcome(mem_db, "AAPL", prob_up=0.5 + idx * 0.05)
        index_outcome(pid, mem_db)
        pred_ids.append(pid)

    # Retrieve with a query embedding
    query = _fake_embedding(0.15)
    results = retrieve("AAPL", query, mem_db, k=5)

    assert len(results) == 5
    for case in results:
        assert isinstance(case, RetrievedCase)
        assert case.ticker == "AAPL"


@patch("stock.memory.embed")
def test_retrieve_filters_by_ticker(
    mock_embed: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """retrieve only returns cases matching the requested ticker."""
    # Insert 3 AAPL and 3 NVDA cases
    for idx in range(3):
        mock_embed.return_value = _fake_embedding(0.1 + idx * 0.01)
        pid = _seed_prediction_with_outcome(mem_db, "AAPL")
        index_outcome(pid, mem_db)

    for idx in range(3):
        mock_embed.return_value = _fake_embedding(0.5 + idx * 0.01)
        pid = _seed_prediction_with_outcome(mem_db, "NVDA")
        index_outcome(pid, mem_db)

    query = _fake_embedding(0.12)
    results = retrieve("AAPL", query, mem_db, k=5)

    assert all(c.ticker == "AAPL" for c in results)


def test_retrieve_returns_empty_when_no_cases(
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """retrieve returns empty list when no cases are indexed."""
    query = _fake_embedding(0.1)
    results = retrieve("AAPL", query, mem_db)
    assert results == []


@patch("stock.memory.embed")
def test_retrieve_returns_fewer_than_k_when_insufficient(
    mock_embed: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """retrieve returns fewer than k when not enough cases exist."""
    for idx in range(2):
        mock_embed.return_value = _fake_embedding(0.1 + idx * 0.01)
        pid = _seed_prediction_with_outcome(mem_db, "AAPL")
        index_outcome(pid, mem_db)

    query = _fake_embedding(0.12)
    results = retrieve("AAPL", query, mem_db, k=5)

    assert len(results) == 2


def test_format_retrieved_cases_empty() -> None:
    """Empty case list returns the placeholder message."""
    result = format_retrieved_cases([])
    assert result == "No historical cases available yet."


def test_format_retrieved_cases_formats_correctly() -> None:
    """Retrieved cases are formatted with numbered blocks."""
    cases = [
        RetrievedCase(
            prediction_id=1,
            ticker="AAPL",
            direction="up",
            prob_up=0.7,
            confidence=0.8,
            rationale="Strong momentum.",
            actual_return=0.03,
            direction_hit=True,
            brier=0.09,
            feature_summary="Earnings beat expectations.",
            similarity=0.92,
        ),
    ]

    result = format_retrieved_cases(cases)

    assert "Case 1" in result
    assert "0.92" in result
    assert "up" in result
    assert "correct" in result


def test_extract_feature_text_handles_none() -> None:
    """None feature_json returns fallback string."""
    result = _extract_feature_text(None)
    assert result == "No feature context available."


def test_extract_feature_text_handles_invalid_json() -> None:
    """Invalid JSON returns fallback string."""
    result = _extract_feature_text("not json at all")
    assert result == "Invalid feature context."


def test_extract_feature_text_formats_features() -> None:
    """Valid feature JSON is formatted into a readable summary."""
    data = json.dumps({
        "features": [
            {
                "title": "AAPL earnings",
                "sentiment": "bullish",
                "catalyst_type": "earnings",
                "summary": "Beat expectations.",
            }
        ],
        "prices": [],
    })

    result = _extract_feature_text(data)

    assert "AAPL earnings" in result
    assert "bullish" in result
    assert "earnings" in result


def test_extract_feature_text_handles_empty_features() -> None:
    """Feature JSON with empty features list returns fallback."""
    data = json.dumps({"features": [], "prices": []})
    result = _extract_feature_text(data)
    assert result == "No features available."
