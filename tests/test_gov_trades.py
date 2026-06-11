"""tests.test_gov_trades -- congressional trade disclosures collector (H3)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from stock.ingest.gov_trades import (
    format_gov_block,
    parse_entry,
    pull_gov_trades,
    recent_for_ticker,
)

_RECENT = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()


def test_parse_entry_quiverquant_shape() -> None:
    parsed = parse_entry({
        "Representative": "Jane Doe",
        "Ticker": "DELL",
        "Transaction": "Purchase",
        "Range": "$100,001 - $250,000",
        "TransactionDate": "2026-05-20",
        "ReportDate": "2026-06-01",
        "Chamber": "house",
    })
    assert parsed == {
        "politician": "Jane Doe", "chamber": "house", "ticker": "DELL",
        "transaction_type": "buy", "amount_range": "$100,001 - $250,000",
        "transaction_date": "2026-05-20", "disclosed_at": "2026-06-01",
    }


def test_parse_entry_stock_watcher_shape_and_rejects() -> None:
    parsed = parse_entry({
        "senator": "John Roe",
        "ticker": "nvda",
        "type": "Sale (Full)",
        "amount": "$15,001 - $50,000",
        "transaction_date": "2026-05-02",
        "disclosure_date": "2026-05-30",
    })
    assert parsed is not None
    assert parsed["ticker"] == "NVDA" and parsed["transaction_type"] == "sell"

    assert parse_entry({"ticker": "--", "senator": "X", "transaction_date": "2026-01-01"}) is None
    assert parse_entry({"ticker": "AAPL"}) is None  # no politician/date
    assert parse_entry("not a dict") is None  # type: ignore[arg-type]


def test_pull_skips_without_url(mem_db: sqlite3.Connection) -> None:
    assert pull_gov_trades(mem_db, url="") is None


def test_pull_inserts_and_dedupes(mem_db: sqlite3.Connection) -> None:
    payload = [
        {"Representative": "Jane Doe", "Ticker": "DELL", "Transaction": "Purchase",
         "Range": "$1,001 - $15,000", "TransactionDate": _RECENT,
         "ReportDate": _RECENT},
        # exact duplicate -> deduped by the unique index
        {"Representative": "Jane Doe", "Ticker": "DELL", "Transaction": "Purchase",
         "Range": "$1,001 - $15,000", "TransactionDate": _RECENT,
         "ReportDate": _RECENT},
        # too old -> skipped
        {"Representative": "Old Guy", "Ticker": "IBM", "Transaction": "Purchase",
         "TransactionDate": "2020-01-01"},
    ]
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None

    with patch("stock.ingest.gov_trades.httpx.get", return_value=response):
        result = pull_gov_trades(mem_db, url="https://example.com/feed.json")
        second = pull_gov_trades(mem_db, url="https://example.com/feed.json")

    assert result is not None and result.inserted == 1 and result.skipped == 2
    assert second is not None and second.inserted == 0

    rows = recent_for_ticker(mem_db, "DELL")
    assert len(rows) == 1 and rows[0][0] == "Jane Doe" and rows[0][1] == "buy"


def test_pull_handles_wrapped_payload(mem_db: sqlite3.Connection) -> None:
    response = MagicMock()
    response.json.return_value = {"data": [
        {"Senator": "John Roe", "Ticker": "NVDA", "Transaction": "Sale",
         "TransactionDate": _RECENT},
    ]}
    response.raise_for_status.return_value = None

    with patch("stock.ingest.gov_trades.httpx.get", return_value=response):
        result = pull_gov_trades(mem_db, url="https://example.com/feed.json")

    assert result is not None and result.inserted == 1


def test_format_gov_block(mem_db: sqlite3.Connection) -> None:
    assert format_gov_block("DELL", mem_db) == ""

    mem_db.execute(
        "INSERT INTO gov_trades (politician, ticker, transaction_type,"
        " amount_range, transaction_date, disclosed_at, ingested_at)"
        " VALUES ('Jane Doe', 'DELL', 'buy', '$1m', ?, ?, ?)",
        (_RECENT, _RECENT, datetime.now(timezone.utc).isoformat()),
    )
    mem_db.commit()

    block = format_gov_block("DELL", mem_db)
    assert "Jane Doe buy $1m" in block
    assert "45 days" in block  # the disclosure-lag caveat is always present
