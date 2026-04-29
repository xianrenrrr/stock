"""tests.test_calibrate -- probability calibration tests."""
from __future__ import annotations

import pickle
import sqlite3
from datetime import datetime, timezone

import numpy as np
import pytest
from sklearn.isotonic import IsotonicRegression

from stock.calibrate import (
    MIN_CALIBRATION_SAMPLES,
    calibrate,
    fit_calibration,
)


def _insert_scored_prediction(
    conn: sqlite3.Connection,
    prob_up: float,
    direction_hit: int,
    idx: int = 0,
) -> int:
    """Insert a prediction + outcome pair, return prediction_id."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO predictions ("
        "  ticker, horizon_minutes, direction, prob_up, confidence,"
        "  rationale, key_factors_json, model_used, created_at, due_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("TEST", 390, "up", prob_up, 0.5, "test", "[]", "test",
         f"2025-01-{10 + idx:02d}T14:00:00+00:00",
         f"2025-01-{13 + idx:02d}T21:00:00+00:00"),
    )
    pred_id = cursor.lastrowid or 0
    conn.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (pred_id, 0.01 if direction_hit else -0.01, direction_hit, 0.0, now),
    )
    conn.commit()
    return pred_id


def _seed_calibration_data(
    conn: sqlite3.Connection,
    count: int,
    raw_prob: float,
    true_rate: float,
) -> None:
    """Insert count scored predictions with given raw prob and true hit rate."""
    rng = np.random.default_rng(42)
    for idx in range(count):
        hit = 1 if rng.random() < true_rate else 0
        _insert_scored_prediction(conn, raw_prob, hit, idx=idx)


def test_calibrate_returns_raw_when_no_model(mem_db: sqlite3.Connection) -> None:
    """No calibration rows -- returns raw prob unchanged."""
    result = calibrate(0.8, mem_db)
    assert result == pytest.approx(0.8)


def test_calibrate_applies_stored_model(mem_db: sqlite3.Connection) -> None:
    """Manually stored model is applied by calibrate()."""
    # Fit a simple model
    model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    model.fit(np.array([0.1, 0.5, 0.9]), np.array([0.0, 0.5, 1.0]))
    params_blob = pickle.dumps(model)

    mem_db.execute(
        "INSERT INTO calibration (version, params, trained_on_ids, trained_at)"
        " VALUES (?, ?, ?, ?)",
        (1, params_blob, "[]", datetime.now(timezone.utc).isoformat()),
    )
    mem_db.commit()

    # Should apply the model, not return raw
    result = calibrate(0.5, mem_db)
    expected = float(model.predict(np.array([[0.5]]))[0])
    assert result == pytest.approx(expected)


def test_fit_calibration_creates_version(mem_db: sqlite3.Connection) -> None:
    """Seeding 50 predictions produces calibration version 1."""
    _seed_calibration_data(mem_db, 50, raw_prob=0.7, true_rate=0.6)

    version = fit_calibration(mem_db)
    assert version == 1

    row = mem_db.execute("SELECT COUNT(*) FROM calibration").fetchone()
    assert row[0] == 1


def test_fit_calibration_returns_none_too_few(mem_db: sqlite3.Connection) -> None:
    """Below MIN_CALIBRATION_SAMPLES, returns None."""
    _seed_calibration_data(mem_db, MIN_CALIBRATION_SAMPLES - 1, raw_prob=0.7, true_rate=0.6)

    version = fit_calibration(mem_db)
    assert version is None


def test_fit_calibration_increments_version(mem_db: sqlite3.Connection) -> None:
    """Fitting twice produces version 1 then version 2."""
    _seed_calibration_data(mem_db, 50, raw_prob=0.7, true_rate=0.6)

    v1 = fit_calibration(mem_db)
    assert v1 == 1

    v2 = fit_calibration(mem_db)
    assert v2 == 2


def test_calibration_reduces_brier(mem_db: sqlite3.Connection) -> None:
    """Calibration reduces Brier score on synthetic overconfident data."""
    rng = np.random.default_rng(123)

    # Seed 100 training pairs: overconfident (raw ~0.85, true rate ~0.55)
    for idx in range(100):
        raw = float(rng.uniform(0.80, 0.90))
        hit = 1 if rng.random() < 0.55 else 0
        _insert_scored_prediction(mem_db, raw, hit, idx=idx)

    # Fit calibration
    fit_calibration(mem_db)

    # Generate 50 test pairs with same distribution
    test_raws: list[float] = []
    test_actuals: list[float] = []
    for _ in range(50):
        raw = float(rng.uniform(0.80, 0.90))
        actual = 1.0 if rng.random() < 0.55 else 0.0
        test_raws.append(raw)
        test_actuals.append(actual)

    # Compute raw Brier
    raw_brier = np.mean([(r - a) ** 2 for r, a in zip(test_raws, test_actuals)])

    # Compute calibrated Brier
    cal_brier = np.mean(
        [(calibrate(r, mem_db) - a) ** 2 for r, a in zip(test_raws, test_actuals)]
    )

    assert cal_brier < raw_brier


def test_calibrate_clips_to_bounds(mem_db: sqlite3.Connection) -> None:
    """Calibrated output is within [0, 1] even for edge inputs."""
    # Seed and fit a model
    _seed_calibration_data(mem_db, 30, raw_prob=0.5, true_rate=0.5)
    fit_calibration(mem_db)

    # Edge inputs
    for raw in [0.0, 0.001, 0.999, 1.0]:
        result = calibrate(raw, mem_db)
        assert 0.0 <= result <= 1.0


def test_fit_calibration_stores_trained_on_ids(mem_db: sqlite3.Connection) -> None:
    """After fitting, trained_on_ids contains a JSON list of prediction IDs."""
    import json

    _seed_calibration_data(mem_db, 30, raw_prob=0.6, true_rate=0.5)
    fit_calibration(mem_db)

    row = mem_db.execute(
        "SELECT trained_on_ids FROM calibration WHERE version = 1"
    ).fetchone()
    ids = json.loads(row[0])
    assert isinstance(ids, list)
    assert len(ids) == 30
    assert all(isinstance(i, int) for i in ids)
