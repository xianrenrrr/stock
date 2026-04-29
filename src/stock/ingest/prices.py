"""stock.ingest.prices -- fetch daily OHLCV bars via yfinance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import yfinance

from stock.ingest import PriceBar


def fetch_daily_prices(ticker: str, days: int = 30) -> list[PriceBar]:
    """Download daily OHLCV bars for a ticker via yfinance."""
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    df = yfinance.download(ticker, start=start_date, end=end_date, progress=False)

    if df.empty:
        return []

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
