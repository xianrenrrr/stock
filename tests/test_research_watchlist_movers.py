"""Tests for deterministic broad-watchlist mover coverage in daily research."""
from __future__ import annotations

import sqlite3

from stock.research import _build_watchlist_movers_block


def test_watchlist_movers_block_includes_large_price_move(mem_db: sqlite3.Connection) -> None:
    mem_db.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES (?, ?, 1)",
        ("MU", "2026-05-25T00:00:00+00:00"),
    )
    mem_db.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES (?, ?, 1)",
        ("CALM", "2026-05-25T00:00:00+00:00"),
    )
    mem_db.execute(
        "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("MU", "2026-05-25", 700, 760, 690, 751, 35_000_000),
    )
    mem_db.execute(
        "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("MU", "2026-05-26", 800, 916, 790, 895.88, 74_000_000),
    )
    mem_db.execute(
        "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("CALM", "2026-05-25", 99, 101, 98, 100, 1_000_000),
    )
    mem_db.execute(
        "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("CALM", "2026-05-26", 99, 101, 98, 101, 1_100_000),
    )
    mem_db.execute(
        "INSERT INTO predictions ("
        "ticker, horizon_minutes, direction, prob_up, prob_up_calibrated,"
        " expected_return_bps, confidence, rationale, key_factors_json,"
        " model_used, strategy_arm, rules_version, retrieved_case_ids,"
        " created_at, due_at, feature_context_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "MU",
            1440,
            "down",
            0.48,
            0.49,
            None,
            0.47,
            "UBS target hike but extended after a one-day surge.",
            "[]",
            "test",
            None,
            None,
            None,
            "2026-05-26T14:24:00+00:00",
            "2026-05-27T14:24:00+00:00",
            None,
        ),
    )
    mem_db.commit()

    block = _build_watchlist_movers_block(mem_db)

    assert "| MU |" in block
    assert "+19.3%" in block
    assert "UBS target hike" in block
    assert "CALM" not in block

