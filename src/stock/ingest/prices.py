"""stock.ingest.prices -- fetch daily OHLCV bars via yfinance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import yfinance

from stock.ingest import PriceBar


def canonical_yfinance_ticker(ticker: str) -> str:
    """Normalize symbols before yfinance lookup and local price storage."""
    return ticker.strip().upper()


def fetch_daily_prices(ticker: str, days: int = 30) -> list[PriceBar]:
    """Download daily OHLCV bars for a ticker via yfinance.

    yfinance treats the `end` parameter as EXCLUSIVE -- end='2026-05-05'
    returns data strictly before that date. We want to include today's
    close once it's settled (US session ends 20:00 UTC; data settles in
    yfinance shortly after), so set end to tomorrow.
    """
    ticker = canonical_yfinance_ticker(ticker)
    today = datetime.now(timezone.utc)
    end_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")

    df = yfinance.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=False)

    if df.empty:
        return []

    # yfinance returns MultiIndex columns (field, ticker) even for a single ticker; flatten to scalars
    if df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    # Drop rows with any NaN
    df = df.dropna()

    bars: list[PriceBar] = []
    for idx, row in df.iterrows():
        ts = idx.strftime("%Y-%m-%d")
        bars.append(
            PriceBar(
                ticker=ticker,
                ts=ts,
                o=float(row["Open"]),
                h=float(row["High"]),
                l=float(row["Low"]),
                c=float(row["Close"]),
                v=int(row["Volume"]),
            )
        )

    return bars
