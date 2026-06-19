"""tests.test_weekly_review -- Sunday weekly prediction + Saturday review."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from stock.predict import WEEKLY_HORIZON_MINUTES, compute_weekly_due_at
from stock.weekly_review import build_weekly_review_body, generate_weekly_review


def test_compute_weekly_due_at_is_next_saturday():
    # 2026-06-21 is a Sunday; the coming Saturday is 2026-06-27.
    sunday = datetime(2026, 6, 21, 16, 0, tzinfo=timezone.utc)
    due = compute_weekly_due_at(sunday)
    assert due.startswith("2026-06-27")
    # A Saturday input rolls to the NEXT Saturday (strictly future).
    sat = datetime(2026, 6, 27, 0, 0, tzinfo=timezone.utc)
    assert compute_weekly_due_at(sat).startswith("2026-07-04")


def _weekly_pred(conn, ticker, direction, hit, actual, prob=0.6):
    created = "2026-06-21T16:00:00+00:00"
    cur = conn.execute(
        "INSERT INTO predictions (ticker, horizon_minutes, direction, prob_up,"
        " expected_return_bps, confidence, rationale, key_factors_json, model_used,"
        " created_at, due_at, feature_context_json)"
        " VALUES (?,?,?,?,50,0.6,'r','[]','m',?, '2026-06-27T00:00:00+00:00', '{}')",
        (ticker, WEEKLY_HORIZON_MINUTES, direction, prob, created),
    )
    conn.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, ?, ?, 0.2, ?)",
        (cur.lastrowid, actual, 1 if hit else 0, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def test_weekly_review_splits_cn_us_and_persists(mem_db: sqlite3.Connection):
    _weekly_pred(mem_db, "NVDA", "up", hit=True, actual=0.05)
    _weekly_pred(mem_db, "AMD", "down", hit=False, actual=0.06)
    _weekly_pred(mem_db, "688126.SS", "up", hit=True, actual=0.03)

    rid = generate_weekly_review(mem_db)
    assert rid is not None
    body = mem_db.execute(
        "SELECT body FROM research_reports WHERE id=?", (rid,)
    ).fetchone()[0]
    assert "US" in body and "China" in body
    assert "1/2" in body  # US: 1 hit of 2
    assert "1/1" in body  # CN: 1 hit of 1
    assert "最佳" in body and "最差" in body


def test_weekly_review_none_when_no_weekly_scored(mem_db: sqlite3.Connection):
    # A daily prediction (different horizon) must not count as weekly.
    mem_db.execute(
        "INSERT INTO predictions (ticker, horizon_minutes, direction, prob_up,"
        " expected_return_bps, confidence, rationale, key_factors_json, model_used,"
        " created_at, due_at, feature_context_json)"
        " VALUES ('NVDA',390,'up',0.6,50,0.6,'r','[]','m','2026-06-21T16:00:00+00:00',"
        " '2026-06-22T21:00:00+00:00','{}')",
    )
    mem_db.commit()
    assert generate_weekly_review(mem_db) is None
    assert "无到期" in build_weekly_review_body([])
