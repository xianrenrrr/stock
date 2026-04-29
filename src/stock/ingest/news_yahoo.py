"""stock.ingest.news_yahoo -- fetch per-ticker news via yfinance."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import yfinance

from stock.ingest import NewsItem

logger = logging.getLogger(__name__)

MAX_BODY_CHARS: int = 40_000


def fetch_yahoo_news(ticker: str) -> list[NewsItem]:
    """Fetch news items for a ticker via yfinance.Ticker.news."""
    try:
        ticker_obj = yfinance.Ticker(ticker)
        raw_news = ticker_obj.news
    except AttributeError:
        logger.warning("yfinance API changed: Ticker.news unavailable for %s", ticker)
        return []

    if not raw_news:
        return []

    items: list[NewsItem] = []
    for entry in raw_news:
        link = entry.get("link", "")
        title = entry.get("title", "")
        publish_time = entry.get("providerPublishTime")

        # Skip items missing required fields
        if not link or not title:
            continue
        if publish_time is None:
            continue

        ts = datetime.fromtimestamp(publish_time, tz=timezone.utc).isoformat()
        body = entry.get("summary", "")[:MAX_BODY_CHARS]

        items.append(
            NewsItem(ticker=ticker, source="yahoo", url=link, title=title, body=body, ts=ts)
        )

    return items
