"""stock.calibrate -- probability calibration via isotonic regression."""
from __future__ import annotations

import json
import logging
import pickle
import sqlite3
from datetime import datetime, timezone

import numpy as np
from sklearn.isotonic import IsotonicRegression

logger = logging.getLogger(__name__)

CALIBRATION_WINDOW: int = 500
MIN_CALIBRATION_SAMPLES: int = 20


def calibrate(raw_prob_up: float, conn: sqlite3.Connection) -> float:
    """Apply the latest calibration model to a raw probability."""
    model = _load_latest_model(conn)
    if model is None:
        return raw_prob_up

    # Run the isotonic regression prediction
    calibrated: float = float(model.predict(np.array([[raw_prob_up]]))[0])
    return calibrated


def _load_latest_model(conn: sqlite3.Connection) -> IsotonicRegression | None:
    """Load the most recent calibration model from the database."""
    row = conn.execute(
        "SELECT params FROM calibration ORDER BY version DESC LIMIT 1"
    ).fetchone()

    if row is None:
        return None

    model: IsotonicRegression = pickle.loads(row[0])  # noqa: S301
    return model


def fit_calibration(conn: sqlite3.Connection) -> int | None:
    """Fit a new calibration model on the last N scored predictions."""
    # Fetch recent scored prediction/outcome pairs
    rows = conn.execute(
        "SELECT p.id, p.prob_up, o.direction_hit"
        " FROM predictions p"
        " JOIN outcomes o ON p.id = o.prediction_id"
        " ORDER BY o.scored_at DESC LIMIT ?",
        (CALIBRATION_WINDOW,),
    ).fetchall()

    # Need enough samples for reliable isotonic regression
    if len(rows) < MIN_CALIBRATION_SAMPLES:
        return None

    # Extract arrays for fitting
    raw_probs = np.array([r[1] for r in rows])
    actuals = np.array([r[2] for r in rows], dtype=np.float64)

    # Fit isotonic regression
    model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    model.fit(raw_probs, actuals)

    # Serialize model
    params_blob = pickle.dumps(model)

    # Get next version number
    max_row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM calibration").fetchone()
    next_version: int = int(max_row[0]) + 1

    # Store prediction IDs used for training
    trained_on_ids = json.dumps([r[0] for r in rows])

    # Insert calibration row
    conn.execute(
        "INSERT INTO calibration (version, params, trained_on_ids, trained_at)"
        " VALUES (?, ?, ?, ?)",
        (next_version, params_blob, trained_on_ids,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

    return next_version
