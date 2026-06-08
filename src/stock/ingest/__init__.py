"""stock.ingest -- pull news and prices into SQLite."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MAX_BODY_CHARS: int = 40_000
DEFAULT_FEEDS_PATH: str = "data/feeds.yaml"
DEFAULT_PRICE_DAYS: int = 30


class FeedConfig(BaseModel):
    """RSS feed URL and metadata from feeds.yaml."""

    url: str
    source: str
    per_ticker: bool


class NewsItem(BaseModel):
    """Single news article before DB insertion."""

    ticker: str
    source: str
    url: str
    title: str
    body: str = ""
    ts: str


class PriceBar(BaseModel):
    """Single daily OHLCV bar."""

    ticker: str
    ts: str
    o: float
    h: float
    l: float  # noqa: E741
    c: float
    v: int


class IngestResult(BaseModel):
    """Summary of an ingestion run."""

    ticker: str
    source: str
    fetched: int
    inserted: int
    skipped: int


def load_feeds(feeds_path: str | None = None) -> list[FeedConfig]:
    """Load RSS feed configs from data/feeds.yaml."""
    path = Path(feeds_path or DEFAULT_FEEDS_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Feeds config not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "feeds" not in raw:
        raise ValueError(f"Invalid feeds.yaml: expected top-level 'feeds' key in {path}")

    return [FeedConfig(**entry) for entry in raw["feeds"]]


def fetch_news(
    ticker: str,
    conn: sqlite3.Connection,
    feeds_path: str | None = None,
    dry_run: bool = False,
) -> IngestResult:
    """Fetch news from Yahoo API + RSS feeds, deduplicate, insert into DB."""
    from stock.ingest.news_rss import fetch_rss_news
    from stock.ingest.news_yahoo import fetch_yahoo_news

    # Fetch from both sources
    yahoo_items = fetch_yahoo_news(ticker)
    feeds = load_feeds(feeds_path)
    rss_items = fetch_rss_news(ticker, feeds)

    # Combine and deduplicate by URL within the batch
    seen_urls: dict[str, NewsItem] = {}
    for item in yahoo_items + rss_items:
        if item.url not in seen_urls:
            seen_urls[item.url] = item
    all_items = list(seen_urls.values())

    fetched = len(all_items)
    if dry_run:
        for item in all_items:
            print(f"[{item.source}] {item.title} — {item.url}")
        return IngestResult(ticker=ticker, source="news", fetched=fetched, inserted=0, skipped=0)

    # Insert with dedup via unique index
    inserted = 0
    now = datetime.now(timezone.utc).isoformat()
    for item in all_items:
        body = item.body[:MAX_BODY_CHARS]
        cursor = conn.execute(
            "INSERT OR IGNORE INTO news (ticker, source, url, title, body, ts, ingested_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item.ticker, item.source, item.url, item.title, body, item.ts, now),
        )
        if cursor.rowcount > 0:
            inserted += 1
    conn.commit()

    skipped = fetched - inserted
    return IngestResult(
        ticker=ticker, source="news", fetched=fetched, inserted=inserted, skipped=skipped
    )


def fetch_prices(
    ticker: str,
    conn: sqlite3.Connection,
    days: int = DEFAULT_PRICE_DAYS,
    dry_run: bool = False,
) -> IngestResult:
    """Fetch daily OHLCV bars from yfinance, insert into DB."""
    from stock.ingest.prices import canonical_yfinance_ticker, fetch_daily_prices

    ticker = canonical_yfinance_ticker(ticker)
    bars = fetch_daily_prices(ticker, days)
    fetched = len(bars)

    if dry_run:
        for bar in bars:
            print(
                f"{bar.ts}  O={bar.o:.2f}  H={bar.h:.2f}"
                f"  L={bar.l:.2f}  C={bar.c:.2f}  V={bar.v}"
            )
        return IngestResult(
            ticker=ticker, source="prices", fetched=fetched, inserted=0, skipped=0
        )

    # UPSERT on composite primary key (ticker, ts). Boss directive 2026-05-09:
    # the previous INSERT OR IGNORE silently dropped post-close updates --
    # if an intraday partial-bar was already inserted by the morning ingest
    # cron (14:00 UTC, pre-market), the 4 PM ET fetch couldn't overwrite it
    # with the FINAL close volume. Result: AMD 5/8 row was stuck at a stale
    # 10.5M volume instead of the real 57.7M, leading the morning-note's
    # 'distribution / low conviction rally' thesis astray.
    inserted = 0
    for bar in bars:
        cursor = conn.execute(
            "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(ticker, ts) DO UPDATE SET"
            " o = excluded.o, h = excluded.h, l = excluded.l,"
            " c = excluded.c, v = excluded.v",
            (bar.ticker, bar.ts, bar.o, bar.h, bar.l, bar.c, bar.v),
        )
        if cursor.rowcount > 0:
            inserted += 1
    conn.commit()

    skipped = fetched - inserted
    return IngestResult(
        ticker=ticker, source="prices", fetched=fetched, inserted=inserted, skipped=skipped
    )
