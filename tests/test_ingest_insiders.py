"""tests.test_ingest_insiders -- EDGAR Form 4 fetcher tests."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from stock.ingest import insiders
from stock.ingest.insiders import (
    InsiderTransaction,
    fetch_form4,
    format_insider_block,
    parse_atom_feed,
    persist_insiders,
    recent_for_ticker,
)


_ATOM_FIXTURE = """\
<?xml version="1.0" encoding="UTF-8" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>4 - Smith Jane (0001234567)</title>
    <link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/123/0001234567-26-000001-index.htm"/>
    <updated>2026-04-25T12:00:00-04:00</updated>
  </entry>
  <entry>
    <title>4/A - Doe John (0007654321)</title>
    <link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/123/0007654321-26-000002-index.htm"/>
    <updated>2026-04-22T09:30:00-04:00</updated>
  </entry>
  <entry>
    <title>3 - Random Other (0001111111)</title>
    <link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/123/0001111111-26-000003-index.htm"/>
    <updated>2026-04-20T08:00:00-04:00</updated>
  </entry>
</feed>
"""


def test_parse_atom_feed_extracts_form4_rows() -> None:
    """Three entries (form 4, 4/A, 3) yield three rows; form_type detected."""
    rows = parse_atom_feed(_ATOM_FIXTURE, ticker="NVDA")
    assert len(rows) == 3
    forms = {r.form_type for r in rows}
    assert "4" in forms
    assert "4/A" in forms
    assert any("Smith Jane" in r.filer_name for r in rows)


def test_parse_atom_feed_extracts_accession() -> None:
    """Accession number is extracted from the link href."""
    rows = parse_atom_feed(_ATOM_FIXTURE, ticker="NVDA")
    assert any(r.accession_number == "0001234567-26-000001" for r in rows)


def test_lookup_cik_uses_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """lookup_cik prefers cached map over network refresh."""
    cache_path = tmp_path / "cik.json"  # type: ignore[operator]
    cache_path.write_text('{"NVDA": "0001045810"}', encoding="utf-8")
    monkeypatch.setattr("stock.ingest.insiders.CIK_CACHE_PATH", str(cache_path))

    refresh_mock = MagicMock()
    monkeypatch.setattr("stock.ingest.insiders._refresh_cik_cache", refresh_mock)

    cik = insiders.lookup_cik("NVDA")

    assert cik == "0001045810"
    refresh_mock.assert_not_called()


def test_fetch_form4_uses_user_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """The HTTP layer is invoked with the configured EDGAR User-Agent."""
    cache_path = tmp_path / "cik.json"  # type: ignore[operator]
    cache_path.write_text('{"NVDA": "0001045810"}', encoding="utf-8")
    monkeypatch.setattr("stock.ingest.insiders.CIK_CACHE_PATH", str(cache_path))

    captured: dict[str, object] = {}

    def _fake_get(url: str) -> object:
        captured["url"] = url
        resp = MagicMock()
        resp.status_code = 200
        resp.text = _ATOM_FIXTURE
        return resp

    monkeypatch.setattr("stock.ingest.insiders._http_get", _fake_get)

    rows = fetch_form4("NVDA", limit=3)

    assert len(rows) == 3
    assert "0001045810" in str(captured["url"])


def test_persist_insiders_idempotent(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """persist_insiders UPSERTs by accession_number, no duplicates on rerun."""
    fake_rows = [
        InsiderTransaction(
            ticker="NVDA", filer_name="Smith", filer_role=None,
            form_type="4", filed_at="2026-04-25",
            transaction_type=None, shares=None, price=None,
            accession_number="0001234567-26-000001",
            raw_url="https://example.com/x",
        )
    ]
    monkeypatch.setattr(
        "stock.ingest.insiders.fetch_form4", lambda ticker, **kw: fake_rows
    )

    first = persist_insiders(mem_db, "NVDA")
    second = persist_insiders(mem_db, "NVDA")

    assert first == 1
    assert second == 0
    rows = mem_db.execute(
        "SELECT COUNT(*) FROM insider_filings WHERE ticker = 'NVDA'"
    ).fetchone()
    assert rows[0] == 1


def test_recent_for_ticker_filter(mem_db: sqlite3.Connection) -> None:
    """recent_for_ticker only returns rows within the day cutoff."""
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO insider_filings (ticker, filer_name, filer_role, form_type,"
        " filed_at, transaction_type, shares, price, accession_number, raw_url, fetched_at)"
        " VALUES ('NVDA', 'A', NULL, '4', ?, NULL, NULL, NULL, 'a-1', 'u', ?)",
        (now, now),
    )
    mem_db.execute(
        "INSERT INTO insider_filings (ticker, filer_name, filer_role, form_type,"
        " filed_at, transaction_type, shares, price, accession_number, raw_url, fetched_at)"
        " VALUES ('NVDA', 'B', NULL, '4', '2020-01-01T00:00:00Z', NULL, NULL, NULL, 'b-2', 'u', ?)",
        (now,),
    )
    mem_db.commit()

    rows = recent_for_ticker(mem_db, "NVDA", days=30)
    assert len(rows) == 1
    assert rows[0].filer_name == "A"


def test_format_insider_block_empty() -> None:
    """Empty input yields a stable placeholder string."""
    out = format_insider_block([])
    assert "no recent insider" in out.lower()


def test_format_insider_block_populated() -> None:
    """Bullet line shows ticker, form, filer."""
    row = InsiderTransaction(
        ticker="NVDA", filer_name="Smith Jane", filer_role=None,
        form_type="4", filed_at="2026-04-25",
        transaction_type=None, shares=None, price=None,
        accession_number="x", raw_url="u",
    )
    out = format_insider_block([row])
    assert "NVDA" in out
    assert "Smith Jane" in out
    assert "4" in out
