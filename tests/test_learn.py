"""tests.test_learn -- post-outcome learning tests."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock.learn import refit_calibration, update_bandit


def _insert_prediction_with_arm(
    conn: sqlite3.Connection,
    ticker: str = "AAPL",
    strategy_arm: str | None = "minimax/default",
) -> int:
    """Insert a prediction row with optional strategy arm, return id."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO predictions ("
        "  ticker, horizon_minutes, direction, prob_up, confidence,"
        "  rationale, key_factors_json, model_used, strategy_arm, created_at, due_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticker, 390, "up", 0.7, 0.6, "test", "[]", "test-model",
         strategy_arm, now, now),
    )
    conn.commit()
    return cursor.lastrowid or 0


def _insert_outcome(
    conn: sqlite3.Connection,
    prediction_id: int,
    direction_hit: int,
) -> None:
    """Insert an outcome row for a prediction."""
    conn.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (prediction_id, 0.01, direction_hit, 0.0,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def _insert_bandit_state(
    conn: sqlite3.Connection,
    arm: str = "minimax/default",
    bucket: str = "AAPL",
) -> None:
    """Insert a uniform-prior bandit_state row."""
    conn.execute(
        "INSERT OR IGNORE INTO bandit_state"
        " (strategy_arm, ticker_bucket, alpha, beta, pulls, reward_sum, updated_at)"
        " VALUES (?, ?, 1.0, 1.0, 0, 0.0, ?)",
        (arm, bucket, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def test_update_bandit_hit(mem_db: sqlite3.Connection) -> None:
    """Direction hit increments alpha by 1."""
    pred_id = _insert_prediction_with_arm(mem_db)
    _insert_outcome(mem_db, pred_id, direction_hit=1)
    _insert_bandit_state(mem_db)

    update_bandit(pred_id, mem_db)

    row = mem_db.execute(
        "SELECT alpha, beta FROM bandit_state"
        " WHERE strategy_arm = ? AND ticker_bucket = ?",
        ("minimax/default", "AAPL"),
    ).fetchone()
    assert row[0] == pytest.approx(2.0)
    assert row[1] == pytest.approx(1.0)


def test_update_bandit_miss(mem_db: sqlite3.Connection) -> None:
    """Direction miss increments beta by 1."""
    pred_id = _insert_prediction_with_arm(mem_db)
    _insert_outcome(mem_db, pred_id, direction_hit=0)
    _insert_bandit_state(mem_db)

    update_bandit(pred_id, mem_db)

    row = mem_db.execute(
        "SELECT alpha, beta FROM bandit_state"
        " WHERE strategy_arm = ? AND ticker_bucket = ?",
        ("minimax/default", "AAPL"),
    ).fetchone()
    assert row[0] == pytest.approx(1.0)
    assert row[1] == pytest.approx(2.0)


def test_update_bandit_no_strategy_arm(mem_db: sqlite3.Connection) -> None:
    """Prediction with NULL strategy_arm -- returns without error."""
    pred_id = _insert_prediction_with_arm(mem_db, strategy_arm=None)
    _insert_outcome(mem_db, pred_id, direction_hit=1)

    update_bandit(pred_id, mem_db)


def test_update_bandit_missing_prediction(mem_db: sqlite3.Connection) -> None:
    """Non-existent prediction raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        update_bandit(999, mem_db)


def test_update_bandit_missing_outcome(mem_db: sqlite3.Connection) -> None:
    """Prediction exists but no outcome -- raises ValueError."""
    pred_id = _insert_prediction_with_arm(mem_db)

    with pytest.raises(ValueError, match="not found"):
        update_bandit(pred_id, mem_db)


@patch("stock.learn.fit_calibration")
def test_refit_calibration_delegates(mock_fit: MagicMock, mem_db: sqlite3.Connection) -> None:
    """refit_calibration delegates to fit_calibration."""
    mock_fit.return_value = 5

    result = refit_calibration(mem_db)

    mock_fit.assert_called_once_with(mem_db)
    assert result == 5
