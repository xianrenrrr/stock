"""tests.test_score -- tests for outcome scoring and daily report."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock.score import (
    OutcomeDetail,
    ReportSummary,
    build_report,
    format_report,
    score_due,
)


def _insert_prediction(
    conn: sqlite3.Connection,
    *,
    ticker: str = "AAPL",
    direction: str = "up",
    prob_up: float = 0.8,
    created_at: str = "2025-01-10T14:00:00+00:00",
    due_at: str = "2025-01-13T21:00:00+00:00",
    rationale: str = "Test rationale",
) -> int:
    """Insert a prediction row with sensible defaults, return its id."""
    cursor = conn.execute(
        "INSERT INTO predictions ("
        "  ticker, horizon_minutes, direction, prob_up, confidence,"
        "  rationale, key_factors_json, model_used, created_at, due_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticker, 390, direction, prob_up, 0.7, rationale, "[]", "test-model",
         created_at, due_at),
    )
    conn.commit()
    return cursor.lastrowid or 0


def _insert_price(
    conn: sqlite3.Connection,
    ticker: str,
    ts: str,
    close: float,
) -> None:
    """Insert a price bar with the given close price."""
    conn.execute(
        "INSERT OR IGNORE INTO prices (ticker, ts, o, h, l, c, v)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticker, ts, close, close, close, close, 1000),
    )
    conn.commit()


# -- score_due tests --


@patch("stock.score.refit_calibration")
@patch("stock.score.update_bandit")
@patch("stock.score.index_outcome")
def test_score_due_basic_up(
    _mock_index: MagicMock,
    _mock_bandit: MagicMock,
    _mock_calibrate: MagicMock,
    mem_db: sqlite3.Connection,
) -> None:
    """Stock went up, predicted up -- direction_hit=1, correct brier."""
    _insert_prediction(mem_db, direction="up", prob_up=0.8,
                       created_at="2025-01-10T14:00:00+00:00",
                       due_at="2025-01-13T21:00:00+00:00")
    _insert_price(mem_db, "AAPL", "2025-01-10", 100.0)
    _insert_price(mem_db, "AAPL", "2025-01-13", 105.0)

    result = score_due(mem_db)

    assert result.scored == 1
    assert result.skipped == 0

    row = mem_db.execute(
        "SELECT actual_return, direction_hit, brier FROM outcomes"
    ).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(0.05)
    assert row[1] == 1
    assert row[2] == pytest.approx((0.8 - 1.0) ** 2)


@patch("stock.score.refit_calibration")
@patch("stock.score.update_bandit")
@patch("stock.score.index_outcome")
def test_score_due_basic_down(
    _mock_index: MagicMock,
    _mock_bandit: MagicMock,
    _mock_calibrate: MagicMock,
    mem_db: sqlite3.Connection,
) -> None:
    """Stock went down, predicted down -- direction_hit=1, correct brier."""
    _insert_prediction(mem_db, direction="down", prob_up=0.2,
                       created_at="2025-01-10T14:00:00+00:00",
                       due_at="2025-01-13T21:00:00+00:00")
    _insert_price(mem_db, "AAPL", "2025-01-10", 100.0)
    _insert_price(mem_db, "AAPL", "2025-01-13", 95.0)

    result = score_due(mem_db)

    assert result.scored == 1
    row = mem_db.execute(
        "SELECT actual_return, direction_hit, brier FROM outcomes"
    ).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(-0.05)
    assert row[1] == 1
    assert row[2] == pytest.approx((0.2 - 0.0) ** 2)


@patch("stock.score.refit_calibration")
@patch("stock.score.update_bandit")
@patch("stock.score.index_outcome")
def test_score_due_wrong_direction(
    _mock_index: MagicMock,
    _mock_bandit: MagicMock,
    _mock_calibrate: MagicMock,
    mem_db: sqlite3.Connection,
) -> None:
    """Predicted up but stock went down -- direction_hit=0."""
    _insert_prediction(mem_db, direction="up", prob_up=0.9,
                       created_at="2025-01-10T14:00:00+00:00",
                       due_at="2025-01-13T21:00:00+00:00")
    _insert_price(mem_db, "AAPL", "2025-01-10", 100.0)
    _insert_price(mem_db, "AAPL", "2025-01-13", 90.0)

    result = score_due(mem_db)

    assert result.scored == 1
    row = mem_db.execute(
        "SELECT direction_hit, brier FROM outcomes"
    ).fetchone()
    assert row[0] == 0
    assert row[1] == pytest.approx((0.9 - 0.0) ** 2)


@patch("stock.score.refit_calibration")
@patch("stock.score.update_bandit")
@patch("stock.score.index_outcome")
def test_score_due_idempotent(
    _mock_index: MagicMock,
    _mock_bandit: MagicMock,
    _mock_calibrate: MagicMock,
    mem_db: sqlite3.Connection,
) -> None:
    """Second score_due run scores nothing; outcomes table unchanged."""
    _insert_prediction(mem_db, created_at="2025-01-10T14:00:00+00:00",
                       due_at="2025-01-13T21:00:00+00:00")
    _insert_price(mem_db, "AAPL", "2025-01-10", 100.0)
    _insert_price(mem_db, "AAPL", "2025-01-13", 110.0)

    first = score_due(mem_db)
    assert first.scored == 1

    second = score_due(mem_db)
    assert second.scored == 0
    assert second.already_scored >= 1

    count = mem_db.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
    assert count == 1


@patch("stock.score.refit_calibration")
@patch("stock.score.update_bandit")
@patch("stock.score.index_outcome")
def test_score_due_skips_no_exit_price(
    _mock_index: MagicMock,
    _mock_bandit: MagicMock,
    _mock_calibrate: MagicMock,
    mem_db: sqlite3.Connection,
) -> None:
    """No exit price available -- prediction is skipped."""
    _insert_prediction(mem_db, created_at="2025-01-10T14:00:00+00:00",
                       due_at="2025-01-13T21:00:00+00:00")
    _insert_price(mem_db, "AAPL", "2025-01-10", 100.0)

    result = score_due(mem_db)
    assert result.skipped == 1
    assert result.scored == 0


@patch("stock.score.refit_calibration")
@patch("stock.score.update_bandit")
@patch("stock.score.index_outcome")
def test_score_due_skips_no_entry_price(
    _mock_index: MagicMock,
    _mock_bandit: MagicMock,
    _mock_calibrate: MagicMock,
    mem_db: sqlite3.Connection,
) -> None:
    """No entry price available -- prediction is skipped."""
    _insert_prediction(mem_db, created_at="2025-01-10T14:00:00+00:00",
                       due_at="2025-01-13T21:00:00+00:00")
    _insert_price(mem_db, "AAPL", "2025-01-13", 105.0)

    result = score_due(mem_db)
    assert result.skipped == 1
    assert result.scored == 0


@patch("stock.score.refit_calibration")
@patch("stock.score.update_bandit")
@patch("stock.score.index_outcome")
def test_score_due_zero_return(
    _mock_index: MagicMock,
    _mock_bandit: MagicMock,
    _mock_calibrate: MagicMock,
    mem_db: sqlite3.Connection,
) -> None:
    """Flat return -- treated as not-up, so 'up' prediction is a miss."""
    _insert_prediction(mem_db, direction="up", prob_up=0.7,
                       created_at="2025-01-10T14:00:00+00:00",
                       due_at="2025-01-13T21:00:00+00:00")
    _insert_price(mem_db, "AAPL", "2025-01-10", 100.0)
    _insert_price(mem_db, "AAPL", "2025-01-13", 100.0)

    result = score_due(mem_db)

    assert result.scored == 1
    row = mem_db.execute(
        "SELECT direction_hit, brier FROM outcomes"
    ).fetchone()
    assert row[0] == 0
    assert row[1] == pytest.approx((0.7 - 0.0) ** 2)


# -- build_report tests --


def test_build_report_empty(mem_db: sqlite3.Connection) -> None:
    """No predictions in range -- returns empty report with None aggregates."""
    report = build_report(mem_db, days=7)

    assert report.total_predictions == 0
    assert report.scored == 0
    assert report.pending == 0
    assert report.hit_rate is None
    assert report.mean_brier is None
    assert report.best_call is None
    assert report.worst_call is None
    assert report.total_return_bps == 0.0
    assert report.spend_usd == 0.0


def test_build_report_with_data(mem_db: sqlite3.Connection) -> None:
    """Three predictions (2 hits, 1 miss) produce correct aggregates."""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    past_due = (now - timedelta(hours=6)).isoformat()

    # Prediction 1: correct up call, +5%
    pid1 = _insert_prediction(mem_db, ticker="AAPL", direction="up", prob_up=0.8,
                              created_at=recent, due_at=past_due, rationale="Bullish AAPL")
    mem_db.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (pid1, 0.05, 1, (0.8 - 1.0) ** 2, now.isoformat()),
    )

    # Prediction 2: correct down call, -3%
    pid2 = _insert_prediction(mem_db, ticker="MSFT", direction="down", prob_up=0.2,
                              created_at=recent, due_at=past_due, rationale="Bearish MSFT")
    mem_db.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (pid2, -0.03, 1, (0.2 - 0.0) ** 2, now.isoformat()),
    )

    # Prediction 3: wrong up call, -2%
    pid3 = _insert_prediction(mem_db, ticker="TSLA", direction="up", prob_up=0.9,
                              created_at=recent, due_at=past_due, rationale="Wrong on TSLA")
    mem_db.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (pid3, -0.02, 0, (0.9 - 0.0) ** 2, now.isoformat()),
    )
    mem_db.commit()

    report = build_report(mem_db, days=7)

    assert report.total_predictions == 3
    assert report.scored == 3
    assert report.pending == 0
    assert report.hit_rate == pytest.approx(2 / 3, abs=0.01)
    assert report.mean_brier is not None
    assert report.best_call is not None
    assert report.best_call.ticker == "AAPL"
    assert report.worst_call is not None
    assert report.worst_call.ticker == "TSLA"


# -- format_report test --


def test_format_report_output() -> None:
    """Formatted report contains key section headers and values."""
    report = ReportSummary(
        days=7,
        total_predictions=10,
        scored=8,
        pending=2,
        hit_rate=0.625,
        mean_brier=0.21,
        best_call=OutcomeDetail(
            prediction_id=1, ticker="AAPL", direction="up", prob_up=0.85,
            actual_return=0.05, direction_hit=True, brier=0.0225,
            created_at="2025-01-10T14:00:00+00:00",
            due_at="2025-01-13T21:00:00+00:00",
            rationale="Strong earnings momentum",
        ),
        worst_call=OutcomeDetail(
            prediction_id=2, ticker="TSLA", direction="up", prob_up=0.9,
            actual_return=-0.08, direction_hit=False, brier=0.81,
            created_at="2025-01-10T14:00:00+00:00",
            due_at="2025-01-13T21:00:00+00:00",
            rationale="Misjudged catalyst",
        ),
        total_return_bps=150.0,
        spend_usd=0.032,
    )

    text = format_report(report)

    assert "Hit rate" in text
    assert "Brier" in text
    assert "AAPL" in text
    assert "TSLA" in text
    assert "Best call" in text
    assert "Worst call" in text
    assert "150.0 bps" in text
    assert "$0.0320" in text
