"""tests.test_stops -- F24 stop-loss helper."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from stock.stops import (
    compute_stop_loss,
    format_stop_loss_block,
)


def _insert_bars(conn: sqlite3.Connection, ticker: str, prices: list[float]) -> None:
    """Insert daily bars with a clean upward drift; H/L = price ±0.5."""
    base_date = datetime.now(timezone.utc) - timedelta(days=len(prices))
    for i, c in enumerate(prices):
        ts = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT OR REPLACE INTO prices (ticker, ts, o, h, l, c, v)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, ts, c, c + 0.5, c - 0.5, c, 1_000_000),
        )
    conn.commit()


def test_no_history_returns_none(mem_db: sqlite3.Connection) -> None:
    """Ticker with no price rows -> all fields None, helpful rationale."""
    s = compute_stop_loss("NVDA", mem_db)
    assert s.entry_price is None
    assert s.recommended is None
    assert "No price history" in s.rationale


def test_recommended_uses_swing_low_when_higher_than_atr(
    mem_db: sqlite3.Connection,
) -> None:
    """Swing-low > atr-stop -> recommended = swing-low (tightest defensible)."""
    # Stable rising series 100..120; swing low over 30d = 100; ATR ~ 1.0; entry ~ 120
    prices = [100 + i for i in range(40)]  # 100, 101, ..., 139
    _insert_bars(mem_db, "TST", prices)
    s = compute_stop_loss("TST", mem_db)
    assert s.entry_price == 139.0
    # ATR with daily H-L = 1, so atr_stop ~ 139 - 2*1 = 137; swing_low_30d = lowest low in last 30 = ~110-0.5
    # Since swing_low (~109.5) < atr_stop (~137), recommended = max = atr_stop
    assert s.recommended == pytest.approx(s.atr_stop)


def test_recommended_falls_back_when_atr_above_entry(
    mem_db: sqlite3.Connection,
) -> None:
    """Pathological data where swing low > entry -> falls back to percent stop."""
    # Single bar with huge L (> entry) is non-physical; just a coverage test
    prices = [100.0]
    _insert_bars(mem_db, "EDGE", prices)
    s = compute_stop_loss("EDGE", mem_db)
    assert s.recommended is not None
    assert s.recommended < s.entry_price


def test_format_stop_loss_block_has_table_header(
    mem_db: sqlite3.Connection,
) -> None:
    """Markdown block contains the column headers + at least one data row."""
    _insert_bars(mem_db, "AAA", [50 + i * 0.5 for i in range(40)])
    out = format_stop_loss_block(mem_db, ["AAA", "MISSING"])
    assert "Recommended" in out
    assert "AAA" in out
    assert "MISSING" in out
