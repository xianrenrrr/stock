"""tests.test_ingest_news -- news ingestion tests with mocked I/O."""
from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stock.ingest import FeedConfig, NewsItem, fetch_news, load_feeds
from stock.ingest.news_rss import _strip_html, fetch_rss_news
from stock.ingest.news_yahoo import fetch_yahoo_news

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def yahoo_news_fixture() -> list[dict[str, Any]]:
    """Mimic yfinance.Ticker.news output."""
    return [
        {
            "link": "https://example.com/article-1",
            "title": "AAPL hits record high",
            "providerPublishTime": 1700000000,
            "summary": "Apple shares rose sharply.",
        },
        {
            "link": "https://example.com/article-2",
            "title": "Tech earnings roundup",
            "providerPublishTime": 1700001000,
            "summary": "",
        },
    ]


@pytest.fixture()
def rss_feed_fixture() -> MagicMock:
    """Fake feedparser result with sample entries."""
    feed = MagicMock()
    feed.bozo = False
    feed.entries = [
        {
            "link": "https://news.example.com/a",
            "title": "AAPL upgrade by analyst",
            "published": "Mon, 14 Nov 2023 10:00:00 GMT",
            "summary": "<p>Analysts upgrade <b>AAPL</b> to buy.</p>",
        },
        {
            "link": "https://news.example.com/b",
            "title": "Market overview",
            "published": "Mon, 14 Nov 2023 11:00:00 GMT",
            "summary": "<p>General market update with <i>no ticker mention</i>.</p>",
        },
        {
            "link": "https://news.example.com/c",
            "title": "AAPL new product launch",
            "published": "Mon, 14 Nov 2023 12:00:00 GMT",
            "summary": "Apple launches new product line.",
        },
    ]
    return feed


@pytest.fixture()
def sample_feeds_yaml(tmp_path: Path) -> Path:
    """Write a temporary feeds.yaml and return its path."""
    content = textwrap.dedent("""\
        feeds:
          - url: "https://example.com/rss?s={ticker}"
            source: "test_source"
            per_ticker: true
          - url: "https://example.com/general"
            source: "general"
            per_ticker: false
    """)
    p = tmp_path / "feeds.yaml"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Yahoo news tests
# ---------------------------------------------------------------------------

@patch("stock.ingest.news_yahoo.yfinance.Ticker")
def test_fetch_yahoo_news_returns_items(
    mock_ticker_cls: MagicMock, yahoo_news_fixture: list[dict[str, Any]]
) -> None:
    mock_ticker_cls.return_value.news = yahoo_news_fixture
    items = fetch_yahoo_news("AAPL")
    assert len(items) == 2
    assert items[0].title == "AAPL hits record high"
    assert items[0].source == "yahoo"
    assert items[0].ticker == "AAPL"
    assert items[0].url == "https://example.com/article-1"


@patch("stock.ingest.news_yahoo.yfinance.Ticker")
def test_fetch_yahoo_news_empty_for_unknown_ticker(mock_ticker_cls: MagicMock) -> None:
    mock_ticker_cls.return_value.news = []
    items = fetch_yahoo_news("XXXZZ")
    assert items == []


# ---------------------------------------------------------------------------
# RSS news tests
# ---------------------------------------------------------------------------

@patch("stock.ingest.news_rss.feedparser.parse")
def test_fetch_rss_news_parses_entries(
    mock_parse: MagicMock, rss_feed_fixture: MagicMock
) -> None:
    mock_parse.return_value = rss_feed_fixture
    feeds = [FeedConfig(url="https://example.com/rss?s={ticker}", source="test", per_ticker=True)]
    items = fetch_rss_news("AAPL", feeds)
    assert len(items) >= 1
    assert all(isinstance(i, NewsItem) for i in items)
    # HTML should be stripped
    for item in items:
        assert "<p>" not in item.body
        assert "<b>" not in item.body


@patch("stock.ingest.news_rss.feedparser.parse")
def test_fetch_rss_news_filters_irrelevant_general_feeds(
    mock_parse: MagicMock, rss_feed_fixture: MagicMock
) -> None:
    mock_parse.return_value = rss_feed_fixture
    feeds = [FeedConfig(url="https://example.com/general", source="general", per_ticker=False)]
    items = fetch_rss_news("AAPL", feeds)
    # "Market overview" entry does not mention AAPL — should be filtered out
    titles = [i.title for i in items]
    assert "Market overview" not in titles
    # But entries mentioning AAPL should remain
    assert any("AAPL" in t for t in titles)


def test_strip_html_removes_tags() -> None:
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"
    assert _strip_html("plain text") == "plain text"
    assert _strip_html("<div><span>nested</span></div>") == "nested"
    assert _strip_html("") == ""


# ---------------------------------------------------------------------------
# Integration tests (fetch_news orchestrator)
# ---------------------------------------------------------------------------

@patch("stock.ingest.news_rss.feedparser.parse")
@patch("stock.ingest.news_yahoo.yfinance.Ticker")
def test_news_dedup_by_url(
    mock_ticker_cls: MagicMock,
    mock_parse: MagicMock,
    mem_db: sqlite3.Connection,
    yahoo_news_fixture: list[dict[str, Any]],
    rss_feed_fixture: MagicMock,
    sample_feeds_yaml: Path,
) -> None:
    mock_ticker_cls.return_value.news = yahoo_news_fixture
    mock_parse.return_value = rss_feed_fixture

    # Insert once
    fetch_news("AAPL", mem_db, feeds_path=str(sample_feeds_yaml))
    # Insert again with same data
    result = fetch_news("AAPL", mem_db, feeds_path=str(sample_feeds_yaml))

    # Second run should skip all duplicates
    assert result.skipped == result.fetched

    # Verify unique URLs in DB
    rows = mem_db.execute("SELECT url FROM news WHERE ticker = 'AAPL'").fetchall()
    urls = [r[0] for r in rows]
    assert len(urls) == len(set(urls))


@patch("stock.ingest.news_rss.feedparser.parse")
@patch("stock.ingest.news_yahoo.yfinance.Ticker")
def test_news_dedup_across_sources(
    mock_ticker_cls: MagicMock,
    mock_parse: MagicMock,
    mem_db: sqlite3.Connection,
    sample_feeds_yaml: Path,
) -> None:
    # Same URL from both yahoo and RSS
    shared_url = "https://example.com/shared-article"
    mock_ticker_cls.return_value.news = [
        {
            "link": shared_url,
            "title": "Shared article",
            "providerPublishTime": 1700000000,
            "summary": "",
        },
    ]
    rss_mock = MagicMock()
    rss_mock.bozo = False
    rss_mock.entries = [
        {
            "link": shared_url,
            "title": "Shared article from RSS",
            "published": "Mon, 14 Nov 2023 10:00:00 GMT",
            "summary": "AAPL related content",
        },
    ]
    mock_parse.return_value = rss_mock

    result = fetch_news("AAPL", mem_db, feeds_path=str(sample_feeds_yaml))

    rows = mem_db.execute(
        "SELECT COUNT(*) FROM news WHERE url = ?", (shared_url,)
    ).fetchone()
    assert rows[0] == 1
    assert result.inserted == 1


@patch("stock.ingest.news_rss.feedparser.parse")
@patch("stock.ingest.news_yahoo.yfinance.Ticker")
def test_news_dry_run_does_not_write(
    mock_ticker_cls: MagicMock,
    mock_parse: MagicMock,
    mem_db: sqlite3.Connection,
    yahoo_news_fixture: list[dict[str, Any]],
    sample_feeds_yaml: Path,
) -> None:
    mock_ticker_cls.return_value.news = yahoo_news_fixture
    mock_parse.return_value = MagicMock(bozo=False, entries=[])

    result = fetch_news("AAPL", mem_db, feeds_path=str(sample_feeds_yaml), dry_run=True)

    assert result.inserted == 0
    rows = mem_db.execute("SELECT COUNT(*) FROM news").fetchone()
    assert rows[0] == 0


@patch("stock.ingest.news_yahoo.yfinance.Ticker")
def test_news_body_truncation(
    mock_ticker_cls: MagicMock,
    mem_db: sqlite3.Connection,
    sample_feeds_yaml: Path,
) -> None:
    long_body = "x" * 50_000
    mock_ticker_cls.return_value.news = [
        {
            "link": "https://example.com/long",
            "title": "Long article",
            "providerPublishTime": 1700000000,
            "summary": long_body,
        },
    ]

    with patch("stock.ingest.news_rss.feedparser.parse") as mock_parse:
        mock_parse.return_value = MagicMock(bozo=False, entries=[])
        fetch_news("AAPL", mem_db, feeds_path=str(sample_feeds_yaml))

    row = mem_db.execute("SELECT body FROM news WHERE url = 'https://example.com/long'").fetchone()
    assert row is not None
    assert len(row[0]) <= 40_000


def test_load_feeds_from_yaml(sample_feeds_yaml: Path) -> None:
    feeds = load_feeds(str(sample_feeds_yaml))
    assert len(feeds) == 2
    assert feeds[0].source == "test_source"
    assert feeds[0].per_ticker is True
    assert feeds[1].per_ticker is False


def test_fetch_rss_news_skips_sec_edgar_for_non_us_tickers(
    rss_feed_fixture: MagicMock,
) -> None:
    """SEC EDGAR doesn't resolve Shanghai/Shenzhen/Hong Kong tickers, so the
    sec_edgar feed must be skipped for any ticker containing a dot. Other
    feeds (Yahoo, custom RSS) are unaffected."""
    sec_feed = FeedConfig(
        url="https://www.sec.gov/cgi-bin/browse-edgar?CIK={ticker}&type=8-K",
        source="sec_edgar",
        per_ticker=True,
    )
    yahoo_feed = FeedConfig(
        url="https://news.example.com/rss?ticker={ticker}",
        source="yahoo_rss",
        per_ticker=True,
    )

    # With a Chinese ticker, only the yahoo feed should be hit (1 call to
    # feedparser, not 2).
    with patch("stock.ingest.news_rss.feedparser.parse", return_value=rss_feed_fixture) as mock:
        items = fetch_rss_news("600276.SS", [sec_feed, yahoo_feed])
    assert mock.call_count == 1
    assert mock.call_args.args[0].startswith("https://news.example.com")
    # All resulting items came from yahoo_rss, not sec_edgar
    assert all(item.source == "yahoo_rss" for item in items)

    # With a US ticker, both feeds run -- 2 calls.
    with patch("stock.ingest.news_rss.feedparser.parse", return_value=rss_feed_fixture) as mock:
        fetch_rss_news("NVDA", [sec_feed, yahoo_feed])
    assert mock.call_count == 2
