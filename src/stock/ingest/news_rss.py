"""stock.ingest.news_rss -- fetch and parse RSS feeds."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
from bs4 import BeautifulSoup

from stock.ingest import FeedConfig, NewsItem

logger = logging.getLogger(__name__)

MAX_BODY_CHARS: int = 40_000

# SEC EDGAR fair-access policy requires a declared UA with contact info, otherwise 403.
USER_AGENT: str = "stock-research-bot research@example.com"


def fetch_rss_news(ticker: str, feeds: list[FeedConfig]) -> list[NewsItem]:
    """Fetch news from configured RSS feeds, filter for ticker relevance."""
    items: list[NewsItem] = []
    for feed in feeds:
        # SEC EDGAR only resolves US-listed CIKs. Tickers from non-US
        # exchanges (Shanghai .SS, Shenzhen .SZ, Hong Kong .HK, etc.) flow
        # in via secular_themes.yaml and trigger a 404 + warning on every
        # ingest cycle. A dot in the ticker is a reliable non-US signal
        # for this codebase -- no US class-share tickers (BRK.B style) are
        # in any watchlist or theme file. If one is ever added, it can be
        # carried as e.g. BRK-B (yfinance's dash form) or this filter can
        # be tightened to an explicit suffix denylist.
        if feed.source == "sec_edgar" and "." in ticker:
            continue
        url = feed.url.replace("{ticker}", ticker) if feed.per_ticker else feed.url
        parsed = _parse_feed(url, feed.source, ticker, feed.per_ticker)
        items.extend(parsed)
    return items


def _parse_feed(url: str, source: str, ticker: str, per_ticker: bool) -> list[NewsItem]:
    """Parse a single RSS feed and return matching items."""
    feed = feedparser.parse(url, agent=USER_AGENT)

    if feed.bozo and not feed.entries:
        logger.warning("Feed %s returned error: %s", url, feed.get("bozo_exception", "unknown"))
        return []

    items: list[NewsItem] = []
    for entry in feed.entries:
        link = entry.get("link", "")
        title = entry.get("title", "")
        if not link or not title:
            continue

        # Parse publication date
        ts = _parse_date(entry)

        # Strip HTML from body
        raw_body = entry.get("summary", "")
        body = _strip_html(raw_body)[:MAX_BODY_CHARS]

        # Filter non-per-ticker feeds for relevance
        if not per_ticker and not _is_ticker_relevant(title, body, ticker):
            continue

        items.append(
            NewsItem(ticker=ticker, source=source, url=link, title=title, body=body, ts=ts)
        )

    return items


def _strip_html(raw: str) -> str:
    """Remove HTML tags using BeautifulSoup. Return plain text."""
    return BeautifulSoup(raw, "html.parser").get_text(separator=" ", strip=True)


def _is_ticker_relevant(title: str, body: str, ticker: str) -> bool:
    """Check if news text mentions the ticker as a whole word."""
    pattern = re.compile(rf"\b{re.escape(ticker)}\b", re.IGNORECASE)
    return bool(pattern.search(title) or pattern.search(body))


def _parse_date(entry: dict[str, object]) -> str:
    """Extract a publication date from an RSS or Atom entry as ISO-8601 UTC.

    Tries `published` (RSS) then `updated` (Atom, e.g. SEC EDGAR), falling back
    to the parsed-tuple variants and finally to wall clock if nothing parses.
    """
    for key in ("published", "updated"):
        value = entry.get(key)
        if isinstance(value, str):
            try:
                return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
            except (ValueError, TypeError):
                pass

    for key in ("published_parsed", "updated_parsed"):
        parsed_tuple = entry.get(key)
        if parsed_tuple is not None:
            try:
                from time import mktime

                return (
                    datetime.fromtimestamp(mktime(parsed_tuple), tz=timezone.utc)  # type: ignore[arg-type]
                    .isoformat()
                )
            except (OverflowError, OSError, TypeError):
                pass

    logger.warning("Missing or unparseable date in RSS entry: %s", entry.get("link", "unknown"))
    return datetime.now(timezone.utc).isoformat()
