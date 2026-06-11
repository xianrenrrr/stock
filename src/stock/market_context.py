"""stock.market_context -- plan H phase H0: market tape for the predict prompt.

Three signals the 1-day predictor was blind to:

1. Market internals -- index/sector-ETF/VIX/10Y daily moves from the local
   prices table (the ingest job pulls INDEX_TICKERS bars alongside the
   watchlist). Quantitative grounding for the LLM-text macro block.
2. Live quote -- the 14:15 UTC prediction batch runs ~45 min after the US
   open, but daily bars are yesterday's; the overnight gap was invisible.
3. Next earnings date -- the single most important known 1-day catalyst;
   previously the model only saw it if a news item happened to mention it.

Live quote + earnings are best-effort network calls (yfinance); failures
degrade to an explicit "(unavailable)" line, never an exception. Tests patch
`fetch_live_quote` / `fetch_next_earnings_date` (autouse fixture in conftest).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

INDEX_TICKERS: tuple[str, ...] = ("SPY", "QQQ", "SMH", "SOXX", "XLK", "^VIX", "^TNX")
INDEX_LABELS: dict[str, str] = {
    "SPY": "S&P500", "QQQ": "Nasdaq100", "SMH": "Semis", "SOXX": "Semis(SOXX)",
    "XLK": "Tech", "^VIX": "VIX", "^TNX": "US10Y",
}


def _recent_closes(
    conn: sqlite3.Connection, ticker: str, limit: int = 6
) -> list[float]:
    rows = conn.execute(
        "SELECT c FROM prices WHERE ticker = ? ORDER BY ts DESC LIMIT ?",
        (ticker, limit),
    ).fetchall()
    return [float(r[0]) for r in rows]


def format_market_internals(conn: sqlite3.Connection) -> str:
    """One line per index: level, 1d move, 5d move. DB-only, no network."""
    lines: list[str] = []
    for ticker in INDEX_TICKERS:
        closes = _recent_closes(conn, ticker)
        if len(closes) < 2:
            continue
        latest, prior = closes[0], closes[1]
        d1 = (latest - prior) / prior * 100 if prior else 0.0
        part = f"- {INDEX_LABELS.get(ticker, ticker)}: {latest:.2f} ({d1:+.1f}% 1d"
        if len(closes) >= 6 and closes[5]:
            d5 = (latest - closes[5]) / closes[5] * 100
            part += f", {d5:+.1f}% 5d"
        part += ")"
        lines.append(part)
    if not lines:
        return "(no index data in local DB yet)"
    return "\n".join(lines)


def fetch_live_quote(ticker: str) -> float | None:
    """Best-effort current/last price via yfinance. None on any failure."""
    try:
        import yfinance as yf

        price = yf.Ticker(ticker).fast_info.last_price
        return float(price) if price else None
    except Exception:  # noqa: BLE001 -- network/parse failures degrade silently
        logger.warning("live quote fetch failed for %s", ticker)
        return None


def format_live_quote_line(ticker: str, conn: sqlite3.Connection) -> str:
    live = fetch_live_quote(ticker)
    if live is None:
        return "Live quote: unavailable."
    closes = _recent_closes(conn, ticker, limit=1)
    if not closes or not closes[0]:
        return f"Live quote: ${live:.2f}."
    gap = (live - closes[0]) / closes[0] * 100
    return (
        f"Live quote: ${live:.2f} ({gap:+.1f}% vs last daily close ${closes[0]:.2f})"
        " -- this gap is NOT yet in the daily bars above."
    )


def fetch_next_earnings_date(ticker: str) -> date | None:
    """Best-effort next earnings date via yfinance calendar. None on failure."""
    try:
        import yfinance as yf

        calendar = yf.Ticker(ticker).calendar or {}
        dates = calendar.get("Earnings Date") or []
        today = datetime.now(timezone.utc).date()
        future = sorted(d for d in dates if isinstance(d, date) and d >= today)
        return future[0] if future else None
    except Exception:  # noqa: BLE001 -- network/parse failures degrade silently
        logger.warning("earnings date fetch failed for %s", ticker)
        return None


def format_earnings_line(ticker: str) -> str:
    when = fetch_next_earnings_date(ticker)
    if when is None:
        return "Next earnings: unknown."
    days = (when - datetime.now(timezone.utc).date()).days
    note = " — INSIDE the prediction horizon, expect outsized move risk" if days <= 1 else ""
    return f"Next earnings: {when.isoformat()} (in {days} day(s)){note}."


def build_market_context(ticker: str, conn: sqlite3.Connection) -> str:
    """The full H0 market-tape block for the prediction prompt."""
    return "\n".join([
        format_market_internals(conn),
        format_live_quote_line(ticker, conn),
        format_earnings_line(ticker),
    ])
