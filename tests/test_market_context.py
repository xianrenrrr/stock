"""tests.test_market_context -- H0 market tape block for predictions."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from stock import market_context

# Captured at import time, BEFORE the conftest autouse fixture replaces the
# module attributes -- lets the parser/error-path tests run the real functions.
_REAL_FETCH_QUOTE = market_context.fetch_live_quote
_REAL_FETCH_EARNINGS = market_context.fetch_next_earnings_date


def _seed_prices(
    conn: sqlite3.Connection, ticker: str, closes: list[float]
) -> None:
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    for i, close in enumerate(closes):
        conn.execute(
            "INSERT INTO prices (ticker, ts, o, h, l, c, v)"
            " VALUES (?, ?, ?, ?, ?, ?, 1000)",
            (ticker, (base + timedelta(days=i)).date().isoformat(),
             close, close, close, close),
        )
    conn.commit()


def test_market_internals_formats_moves(mem_db: sqlite3.Connection) -> None:
    _seed_prices(mem_db, "SPY", [100, 100, 100, 100, 100, 110])  # +10% 1d and 5d
    _seed_prices(mem_db, "^VIX", [20, 22])  # +10% 1d, too short for 5d

    block = market_context.format_market_internals(mem_db)

    assert "S&P500: 110.00 (+10.0% 1d, +10.0% 5d)" in block
    assert "VIX: 22.00 (+10.0% 1d)" in block


def test_market_internals_empty_db(mem_db: sqlite3.Connection) -> None:
    assert "no index data" in market_context.format_market_internals(mem_db)


def test_live_quote_line_includes_gap(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_prices(mem_db, "NVDA", [200.0])
    monkeypatch.setattr(market_context, "fetch_live_quote", lambda _t: 210.0)

    line = market_context.format_live_quote_line("NVDA", mem_db)

    assert "$210.00" in line and "+5.0%" in line and "NOT yet" in line


def test_live_quote_line_unavailable(mem_db: sqlite3.Connection) -> None:
    # conftest autouse fixture already forces fetch_live_quote -> None
    assert "unavailable" in market_context.format_live_quote_line("NVDA", mem_db)


def test_earnings_line_flags_inside_horizon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    monkeypatch.setattr(
        market_context, "fetch_next_earnings_date", lambda _t: tomorrow,
    )

    line = market_context.format_earnings_line("NVDA")

    assert tomorrow.isoformat() in line
    assert "INSIDE the prediction horizon" in line


def test_earnings_line_unknown() -> None:
    assert "unknown" in market_context.format_earnings_line("NVDA")


def test_build_market_context_combines_all(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_prices(mem_db, "SPY", [100, 101])
    _seed_prices(mem_db, "NVDA", [200.0])
    monkeypatch.setattr(market_context, "fetch_live_quote", lambda _t: 196.0)
    far = datetime.now(timezone.utc).date() + timedelta(days=20)
    monkeypatch.setattr(market_context, "fetch_next_earnings_date", lambda _t: far)

    block = market_context.build_market_context("NVDA", mem_db)

    assert "S&P500" in block
    assert "-2.0%" in block            # live gap vs 200 close
    assert "in 20 day(s)" in block
    assert "INSIDE" not in block


def test_fetch_next_earnings_date_picks_future(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = datetime.now(timezone.utc).date()

    class _FakeTicker:
        calendar = {
            "Earnings Date": [today - timedelta(days=90), today + timedelta(days=5)],
        }

    import yfinance as yf

    monkeypatch.setattr(yf, "Ticker", lambda _t: _FakeTicker())
    assert _REAL_FETCH_EARNINGS("NVDA") == today + timedelta(days=5)


def test_fetch_helpers_swallow_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import yfinance as yf

    def _boom(_t: str) -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr(yf, "Ticker", _boom)
    assert _REAL_FETCH_QUOTE("NVDA") is None
    assert _REAL_FETCH_EARNINGS("NVDA") is None
