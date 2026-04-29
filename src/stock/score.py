"""stock.score -- outcome scoring and daily report."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from stock.learn import refit_calibration, update_bandit
from stock.memory import index_outcome

logger = logging.getLogger(__name__)


class ScoreResult(BaseModel):
    """Summary of a score_due run."""

    scored: int
    skipped: int
    already_scored: int


class OutcomeDetail(BaseModel):
    """A single scored prediction with full context."""

    prediction_id: int
    ticker: str
    direction: str
    prob_up: float
    actual_return: float
    direction_hit: bool
    brier: float
    created_at: str
    due_at: str
    rationale: str


class ReportSummary(BaseModel):
    """Aggregated performance report over a date range."""

    days: int
    total_predictions: int
    scored: int
    pending: int
    hit_rate: float | None
    mean_brier: float | None
    best_call: OutcomeDetail | None
    worst_call: OutcomeDetail | None
    total_return_bps: float
    spend_usd: float


def score_due(conn: sqlite3.Connection) -> ScoreResult:
    """Score all predictions whose due_at has passed. Idempotent."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # Find predictions that are due and not yet scored
    due_rows = conn.execute(
        "SELECT id, ticker, direction, prob_up, created_at, due_at"
        " FROM predictions"
        " WHERE due_at <= ?"
        " AND id NOT IN (SELECT prediction_id FROM outcomes)",
        (now_iso,),
    ).fetchall()

    scored = 0
    skipped = 0

    for row in due_rows:
        pred_id, ticker, direction, prob_up, created_at, due_at = row

        # Look up entry price: latest close at or before prediction creation
        entry_row = conn.execute(
            "SELECT c FROM prices"
            " WHERE ticker = ? AND ts <= substr(?, 1, 10)"
            " ORDER BY ts DESC LIMIT 1",
            (ticker, created_at),
        ).fetchone()

        if entry_row is None:
            skipped += 1
            continue

        # Look up exit price: earliest close at or after due_at
        exit_row = conn.execute(
            "SELECT c FROM prices"
            " WHERE ticker = ? AND ts >= substr(?, 1, 10)"
            " ORDER BY ts ASC LIMIT 1",
            (ticker, due_at),
        ).fetchone()

        if exit_row is None:
            skipped += 1
            continue

        entry_price: float = entry_row[0]
        exit_price: float = exit_row[0]

        # Compute actual return
        actual_return = (exit_price - entry_price) / entry_price

        # Determine if the stock went up (flat counts as not up)
        went_up = actual_return > 0.0

        # Compute direction hit
        direction_hit = 1 if (direction == "up") == went_up else 0

        # Clamp prob_up to [0, 1] before computing Brier score
        clamped_prob = max(0.0, min(1.0, prob_up))
        brier = (clamped_prob - (1.0 if went_up else 0.0)) ** 2

        # Insert outcome row
        conn.execute(
            "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (pred_id, actual_return, direction_hit, brier, now_iso),
        )

        # Index the scored case into the memory vector store
        try:
            index_outcome(pred_id, conn)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            logger.warning("Failed to index outcome %d: %s", pred_id, exc)

        # Update bandit posteriors for this outcome
        try:
            update_bandit(pred_id, conn)
        except (ValueError, sqlite3.Error) as exc:
            logger.warning("Failed to update bandit for %d: %s", pred_id, exc)

        scored += 1

    conn.commit()

    # Refit calibration model on accumulated outcomes
    if scored > 0:
        try:
            refit_calibration(conn)
        except (ValueError, RuntimeError) as exc:
            logger.warning("Failed to refit calibration: %s", exc)

    # Count already-scored predictions for reporting
    already_scored = conn.execute(
        "SELECT COUNT(*) FROM predictions"
        " WHERE due_at <= ?"
        " AND id IN (SELECT prediction_id FROM outcomes)",
        (now_iso,),
    ).fetchone()[0] - scored

    return ScoreResult(scored=scored, skipped=skipped, already_scored=already_scored)


def build_report(conn: sqlite3.Connection, days: int = 7) -> ReportSummary:
    """Build a performance report for predictions created in the last N days."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Count total predictions in the window
    total_predictions: int = conn.execute(
        "SELECT COUNT(*) FROM predictions WHERE created_at >= ?",
        (since,),
    ).fetchone()[0]

    # Count scored predictions (those with an outcome row)
    scored: int = conn.execute(
        "SELECT COUNT(*) FROM predictions p"
        " JOIN outcomes o ON p.id = o.prediction_id"
        " WHERE p.created_at >= ?",
        (since,),
    ).fetchone()[0]

    pending = total_predictions - scored

    # Compute aggregates over scored predictions
    agg_row = conn.execute(
        "SELECT AVG(o.direction_hit), AVG(o.brier), SUM(o.actual_return)"
        " FROM predictions p"
        " JOIN outcomes o ON p.id = o.prediction_id"
        " WHERE p.created_at >= ?",
        (since,),
    ).fetchone()

    hit_rate: float | None = None
    mean_brier: float | None = None
    total_return_bps: float = 0.0

    if scored > 0 and agg_row[0] is not None:
        hit_rate = round(agg_row[0], 4)
        mean_brier = round(agg_row[1], 4)
        total_return_bps = round(agg_row[2] * 10000, 2)

    # Best call: highest actual_return among direction hits
    best_call = _load_outcome_detail(
        conn, since,
        "AND o.direction_hit = 1 ORDER BY o.actual_return DESC LIMIT 1",
    )

    # Worst call: lowest actual_return among direction misses
    worst_call = _load_outcome_detail(
        conn, since,
        "AND o.direction_hit = 0 ORDER BY o.actual_return ASC LIMIT 1",
    )

    # LLM spend in the window
    spend_row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0) FROM llm_calls WHERE created_at >= ?",
        (since,),
    ).fetchone()
    spend_usd: float = round(spend_row[0], 4)

    return ReportSummary(
        days=days,
        total_predictions=total_predictions,
        scored=scored,
        pending=pending,
        hit_rate=hit_rate,
        mean_brier=mean_brier,
        best_call=best_call,
        worst_call=worst_call,
        total_return_bps=total_return_bps,
        spend_usd=spend_usd,
    )


def _load_outcome_detail(
    conn: sqlite3.Connection,
    since: str,
    order_clause: str,
) -> OutcomeDetail | None:
    """Load a single OutcomeDetail row matching the given filter."""
    row = conn.execute(
        "SELECT p.id, p.ticker, p.direction, p.prob_up,"
        " o.actual_return, o.direction_hit, o.brier,"
        " p.created_at, p.due_at, p.rationale"
        " FROM predictions p"
        " JOIN outcomes o ON p.id = o.prediction_id"
        f" WHERE p.created_at >= ? {order_clause}",
        (since,),
    ).fetchone()

    if row is None:
        return None

    return OutcomeDetail(
        prediction_id=row[0],
        ticker=row[1],
        direction=row[2],
        prob_up=row[3],
        actual_return=row[4],
        direction_hit=bool(row[5]),
        brier=row[6],
        created_at=row[7],
        due_at=row[8],
        rationale=row[9],
    )


def format_report(report: ReportSummary) -> str:
    """Format a ReportSummary into human-readable text for CLI output."""
    lines: list[str] = []

    lines.append(f"Performance Report (last {report.days} days)")
    lines.append("=" * 45)

    # Prediction counts
    lines.append(
        f"Predictions: {report.total_predictions} total, "
        f"{report.scored} scored, {report.pending} pending"
    )

    # Hit rate and Brier
    if report.hit_rate is not None:
        lines.append(f"Hit rate: {report.hit_rate:.1%}")
    else:
        lines.append("Hit rate: N/A")

    if report.mean_brier is not None:
        lines.append(f"Mean Brier score: {report.mean_brier:.4f}")
    else:
        lines.append("Mean Brier score: N/A")

    # Best call
    lines.append("")
    if report.best_call is not None:
        bc = report.best_call
        lines.append(
            f"Best call: {bc.ticker} {bc.direction} "
            f"(return={bc.actual_return:+.2%})"
        )
        lines.append(f"  {bc.rationale[:120]}")
    else:
        lines.append("Best call: none")

    # Worst call
    if report.worst_call is not None:
        wc = report.worst_call
        lines.append(
            f"Worst call: {wc.ticker} {wc.direction} "
            f"(return={wc.actual_return:+.2%})"
        )
        lines.append(f"  {wc.rationale[:120]}")
    else:
        lines.append("Worst call: none")

    # Totals
    lines.append("")
    lines.append(f"Total return: {report.total_return_bps:+.1f} bps")
    lines.append(f"LLM spend: ${report.spend_usd:.4f}")

    return "\n".join(lines)
