"""tests.test_anomaly -- price/volume anomaly flagger tests."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from stock.anomaly import (
    MIN_AVG_VOLUME,
    AnomalyRow,
    compute_daily_anomalies,
    format_anomaly_block,
    recent_anomalies,
)


def _add_watchlist(conn: sqlite3.Connection, ticker: str) -> None:
    """Insert an active watchlist row."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES (?, ?, 1)",
        (ticker, now),
    )
    conn.commit()


def _seed_prices(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    days: int = 31,
    base_close: float = 100.0,
    base_volume: int = 1_000_000,
    latest_close: float | None = None,
    latest_volume: int | None = None,
) -> None:
    """Seed `days` daily bars; allow override of the most-recent close/volume."""
    today = datetime.now(timezone.utc).date()
    for offset in range(days, 0, -1):
        ts = (today - timedelta(days=offset)).isoformat()
        c = base_close
        v = base_volume
        conn.execute(
            "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, ts, c, c, c, c, v),
        )
    # Latest bar is today
    today_str = today.isoformat()
    c_today = latest_close if latest_close is not None else base_close
    v_today = latest_volume if latest_volume is not None else base_volume
    conn.execute(
        "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticker, today_str, c_today, c_today, c_today, c_today, v_today),
    )
    conn.commit()


def test_compute_volume_spike_flag(mem_db: sqlite3.Connection) -> None:
    """A 2x volume vs 30d average flips the flag to volume_spike."""
    _add_watchlist(mem_db, "NVDA")
    _seed_prices(mem_db, "NVDA", base_close=100.0, base_volume=1_000_000,
                 latest_close=100.0, latest_volume=2_500_000)

    flagged = compute_daily_anomalies(mem_db)

    assert len(flagged) == 1
    assert flagged[0].ticker == "NVDA"
    assert flagged[0].flag_reason == "volume_spike"
    assert flagged[0].volume_ratio >= 1.5


def test_compute_price_move_flag(mem_db: sqlite3.Connection) -> None:
    """A 6% price change with quiet volume flags as price_move."""
    _add_watchlist(mem_db, "AMD")
    _seed_prices(
        mem_db, "AMD",
        base_close=100.0, base_volume=1_000_000,
        latest_close=106.5, latest_volume=900_000,
    )

    flagged = compute_daily_anomalies(mem_db)

    assert len(flagged) == 1
    assert flagged[0].flag_reason == "price_move"
    assert flagged[0].pct_change > 0.05


def test_compute_no_flag_under_thresholds(mem_db: sqlite3.Connection) -> None:
    """Quiet bar (4% change, 1.1x volume) yields no flagged row."""
    _add_watchlist(mem_db, "INTC")
    _seed_prices(
        mem_db, "INTC",
        base_close=100.0, base_volume=1_000_000,
        latest_close=104.0, latest_volume=1_100_000,
    )

    flagged = compute_daily_anomalies(mem_db)

    assert flagged == []


def test_compute_idempotent_upsert(mem_db: sqlite3.Connection) -> None:
    """Re-running on the same data does not duplicate the row."""
    _add_watchlist(mem_db, "NVDA")
    _seed_prices(
        mem_db, "NVDA",
        base_close=100.0, base_volume=1_000_000,
        latest_close=110.0, latest_volume=2_500_000,
    )

    compute_daily_anomalies(mem_db)
    compute_daily_anomalies(mem_db)

    rows = mem_db.execute("SELECT COUNT(*) FROM price_anomalies").fetchone()
    assert rows[0] == 1


def test_compute_skips_illiquid_tickers(mem_db: sqlite3.Connection) -> None:
    """Tickers with avg volume below MIN_AVG_VOLUME are skipped entirely."""
    _add_watchlist(mem_db, "TINY")
    _seed_prices(
        mem_db, "TINY",
        base_close=10.0, base_volume=MIN_AVG_VOLUME // 4,
        latest_close=12.0, latest_volume=MIN_AVG_VOLUME * 4,
    )

    flagged = compute_daily_anomalies(mem_db)

    assert flagged == []


def test_compute_includes_holdings_ticker(mem_db: sqlite3.Connection) -> None:
    """A ticker only on holdings (not watchlist) is still scanned."""
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO holdings (ticker, qty, cost_basis, opened_at, notes, active, updated_at)"
        " VALUES (?, ?, ?, ?, '', 1, ?)",
        ("HOLD", 10.0, 50.0, now, now),
    )
    mem_db.commit()
    _seed_prices(
        mem_db, "HOLD",
        base_close=50.0, base_volume=1_000_000,
        latest_close=55.0, latest_volume=2_500_000,
    )

    flagged = compute_daily_anomalies(mem_db)

    assert any(row.ticker == "HOLD" for row in flagged)


def test_recent_anomalies_filter(mem_db: sqlite3.Connection) -> None:
    """recent_anomalies returns rows within the day cutoff."""
    now_iso = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
    mem_db.execute(
        "INSERT INTO price_anomalies (ticker, ts, pct_change, volume_ratio,"
        " flag_reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("FRESH", today, 0.06, 2.0, "both", now_iso),
    )
    mem_db.execute(
        "INSERT INTO price_anomalies (ticker, ts, pct_change, volume_ratio,"
        " flag_reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("STALE", old, 0.06, 2.0, "both", now_iso),
    )
    mem_db.commit()

    rows = recent_anomalies(mem_db, days=2)

    tickers = {row.ticker for row in rows}
    assert "FRESH" in tickers
    assert "STALE" not in tickers


def test_format_anomaly_block_empty() -> None:
    """Empty input produces a placeholder string."""
    out = format_anomaly_block([])
    assert "no anomalies" in out.lower()


def test_format_anomaly_block_populated() -> None:
    """Bullet line mentions ticker, pct, vol, and reason."""
    row = AnomalyRow(
        ticker="NVDA", ts="2026-04-28", pct_change=0.07,
        volume_ratio=2.4, flag_reason="both",
        created_at="2026-04-28T10:00:00Z",
    )
    out = format_anomaly_block([row])
    assert "NVDA" in out
    assert "+7.00%" in out
    assert "2.40x" in out
    assert "both" in out
