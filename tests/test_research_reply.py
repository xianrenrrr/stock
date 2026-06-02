"""tests.test_research_reply -- direct reply grounding helpers."""
from __future__ import annotations

import sqlite3

from stock import db
from stock.research import (
    _build_live_quote_block,
    _detect_tickers_in_text,
    _known_reply_tickers,
)


def test_detect_tickers_accepts_lowercase_known_symbol() -> None:
    """Lowercase ticker mentions are valid when the ticker is known."""
    found = _detect_tickers_in_text(
        "check crdo after report, not the stale price",
        known_tickers={"CRDO"},
    )
    assert found == ["CRDO"]


def test_detect_tickers_does_not_promote_lowercase_words() -> None:
    """Known-ticker gate prevents ordinary words from becoming symbols."""
    found = _detect_tickers_in_text(
        "check price after report",
        known_tickers={"CRDO"},
    )
    assert found == []


def test_live_quote_block_uses_known_lowercase_ticker() -> None:
    """Reply context includes quote-style data for lowercase known tickers."""
    conn: sqlite3.Connection = db.get_conn(":memory:")
    conn.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES ('CRDO', 'now', 1)"
    )
    conn.commit()

    out = _build_live_quote_block(
        conn,
        boss_reply="look at crdo live price today",
        provider=lambda ticker: (97.0, 114.0, -0.1491228),
    )

    assert "PRIMARY price grounding" in out
    assert "CRDO: last=$97.00" in out
    assert "change=-14.91%" in out


def test_known_reply_tickers_reads_watchlist_and_holdings() -> None:
    """Case-insensitive matching is limited to symbols already known locally."""
    conn: sqlite3.Connection = db.get_conn(":memory:")
    conn.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES ('CRDO', 'now', 1)"
    )
    conn.execute(
        "INSERT INTO holdings (ticker, qty, cost_basis, opened_at, active, updated_at)"
        " VALUES ('RKLB', 1, 10, 'now', 1, 'now')"
    )
    conn.commit()

    assert {"CRDO", "RKLB"}.issubset(_known_reply_tickers(conn))
