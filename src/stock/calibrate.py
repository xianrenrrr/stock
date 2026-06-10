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
# Hold out the newest fraction of samples to VALIDATE that calibration actually
# reduces Brier before we let it touch live predictions.
HOLDOUT_FRACTION: float = 0.3
MIN_HOLDOUT_SAMPLES: int = 8


def calibrate(raw_prob_up: float, conn: sqlite3.Connection) -> float:
    """Apply the latest calibration model -- but ONLY if it validated as helping.

    A model that did not beat raw Brier on its holdout is ignored (we return the
    raw probability), so calibration can never make predictions worse than raw.
    """
    model = _load_latest_helping_model(conn)
    if model is None:
        return raw_prob_up
    calibrated: float = float(model.predict(np.array([[raw_prob_up]]))[0])
    return calibrated


def _load_latest_helping_model(conn: sqlite3.Connection) -> IsotonicRegression | None:
    """Load the most recent calibration model that validated as helping (helps=1)."""
    row = conn.execute(
        "SELECT params FROM calibration WHERE COALESCE(helps, 0) = 1"
        " ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    model: IsotonicRegression = pickle.loads(row[0])  # noqa: S301
    return model


def _brier(probs: np.ndarray, actuals: np.ndarray) -> float:
    return float(np.mean((probs - actuals) ** 2))


def fit_calibration(conn: sqlite3.Connection) -> int | None:
    """Fit + VALIDATE a calibration model on the last N scored predictions.

    The model is fit on the older portion and validated on the newest holdout; it
    is flagged helps=1 only when its holdout Brier beats raw. The stored model is
    refit on all samples (for coverage) but `calibrate()` only applies it when
    helps=1. Returns the version number (always stored, for the audit trail).
    """
    rows = conn.execute(
        "SELECT p.id, p.prob_up, o.direction_hit"
        " FROM predictions p"
        " JOIN outcomes o ON p.id = o.prediction_id"
        " ORDER BY o.scored_at DESC, p.id DESC LIMIT ?",
        (CALIBRATION_WINDOW,),
    ).fetchall()
    if len(rows) < MIN_CALIBRATION_SAMPLES:
        return None

    # rows are newest-first; go chronological so the holdout is the NEWEST data.
    chrono = list(reversed(rows))
    raw_all = np.array([r[1] for r in chrono], dtype=np.float64)
    hit_all = np.array([r[2] for r in chrono], dtype=np.float64)

    split = int(len(chrono) * (1.0 - HOLDOUT_FRACTION))
    helps = 0
    brier_raw = brier_cal = None
    if len(chrono) - split >= MIN_HOLDOUT_SAMPLES:
        train_raw, train_hit = raw_all[:split], hit_all[:split]
        val_raw, val_hit = raw_all[split:], hit_all[split:]
        val_model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        val_model.fit(train_raw, train_hit)
        cal_val = val_model.predict(val_raw)
        brier_raw = _brier(val_raw, val_hit)
        brier_cal = _brier(np.asarray(cal_val), val_hit)
        helps = 1 if brier_cal < brier_raw else 0
        logger.info(
            "calibration validation: brier_raw=%.4f brier_cal=%.4f -> helps=%d",
            brier_raw, brier_cal, helps,
        )

    # Production model refit on ALL samples (only used when helps=1).
    model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    model.fit(raw_all, hit_all)
    params_blob = pickle.dumps(model)

    max_row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM calibration").fetchone()
    next_version: int = int(max_row[0]) + 1
    trained_on_ids = json.dumps([r[0] for r in rows])
    conn.execute(
        "INSERT INTO calibration"
        " (version, params, trained_on_ids, trained_at, helps, brier_raw, brier_cal)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (next_version, params_blob, trained_on_ids,
         datetime.now(timezone.utc).isoformat(), helps, brier_raw, brier_cal),
    )
    conn.commit()
    return next_version
