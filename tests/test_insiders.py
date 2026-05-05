"""tests.test_insiders -- F35 Form 4 XML parsing + persist enrichment."""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import httpx
import pytest

from stock import db
from stock.ingest import insiders


SAMPLE_FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001234567</rptOwnerCik>
      <rptOwnerName>Smith, John</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>P</transactionCode>
        <equitySwapInvolved>0</equitySwapInvolved>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares>
          <value>10000</value>
        </transactionShares>
        <transactionPricePerShare>
          <value>27.50</value>
        </transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


SAMPLE_INDEX_JSON = {
    "directory": {
        "item": [
            {"name": "filing-summary.xml", "type": "summary"},
            {"name": "wf-form4_1234567.xml", "type": "form4-doc"},
            {"name": "primary_doc.html", "type": "html"},
        ]
    }
}


def test_parse_form4_xml_extracts_code_shares_price() -> None:
    """parse_form4_xml pulls transaction code + shares + price + role."""
    code, shares, price, role = insiders.parse_form4_xml(SAMPLE_FORM4_XML)
    assert code == "P"
    assert shares == 10000.0
    assert price == 27.50
    assert role == "Chief Executive Officer"


def test_parse_form4_xml_handles_director_only() -> None:
    """When isDirector=1 and no officerTitle, role is 'Director'."""
    xml = """
    <ownershipDocument>
      <reportingOwner>
        <reportingOwnerRelationship>
          <isDirector>1</isDirector>
        </reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>500</value></transactionShares>
            <transactionPricePerShare><value>100</value></transactionPricePerShare>
          </transactionAmounts>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>
    """
    code, shares, price, role = insiders.parse_form4_xml(xml)
    assert code == "S"
    assert shares == 500.0
    assert price == 100.0
    assert role == "Director"


def test_parse_form4_xml_empty_returns_none_tuple() -> None:
    """No transactions => all-Nones."""
    code, shares, price, role = insiders.parse_form4_xml("<ownershipDocument/>")
    assert code is None
    assert shares is None
    assert price is None
    assert role is None


def test_parse_form4_xml_sums_multi_transactions_same_code() -> None:
    """Two purchases in one filing -> shares summed, price weighted."""
    xml = """
    <ownershipDocument>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>1000</value></transactionShares>
            <transactionPricePerShare><value>10</value></transactionPricePerShare>
          </transactionAmounts>
        </nonDerivativeTransaction>
        <nonDerivativeTransaction>
          <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>3000</value></transactionShares>
            <transactionPricePerShare><value>20</value></transactionPricePerShare>
          </transactionAmounts>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>
    """
    code, shares, price, _ = insiders.parse_form4_xml(xml)
    assert code == "P"
    assert shares == 4000.0
    # weighted: (1000*10 + 3000*20) / 4000 = 70000/4000 = 17.5
    assert price == 17.5


def test_form4_xml_url_picks_form4_doc_skipping_summary() -> None:
    """_form4_xml_url_from_index skips filing-summary.xml and picks the doc."""
    fake_resp = httpx.Response(200, json=SAMPLE_INDEX_JSON)
    with patch.object(insiders, "_http_get", return_value=fake_resp):
        url = insiders._form4_xml_url_from_index("0001234567", "0001234567-26-000123")
    assert url is not None
    assert url.endswith("wf-form4_1234567.xml")
    assert "000123456726000123" in url  # un-dashed accession in path


def test_form4_xml_url_returns_none_on_404() -> None:
    """Index-not-found -> graceful None."""
    with patch.object(insiders, "_http_get", return_value=httpx.Response(404)):
        url = insiders._form4_xml_url_from_index("0001234567", "0001234567-26-000123")
    assert url is None


@pytest.fixture
def conn(monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """In-memory DB with full schema applied via stock.db.get_conn."""
    from stock.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "db_path", ":memory:")
    return db.get_conn(":memory:")


def test_persist_insiders_enriches_null_rows_with_xml_parse(conn: sqlite3.Connection) -> None:
    """ATOM-only metadata gets backfilled with XML transaction details."""
    atom_row = insiders.InsiderTransaction(
        ticker="EBAY",
        filer_name="Smith, John",
        form_type="4",
        filed_at="2026-05-04T15:00:00Z",
        accession_number="0001234567-26-000123",
        raw_url="https://www.sec.gov/cgi-bin/test",
    )

    def fake_fetch_and_parse(cik: str, acc: str) -> tuple:
        return ("P", 10000.0, 27.5, "Chief Executive Officer")

    with patch.object(insiders, "fetch_form4", return_value=[atom_row]), \
         patch.object(insiders, "lookup_cik", return_value="0001234567"), \
         patch.object(insiders, "_fetch_and_parse_xml", side_effect=fake_fetch_and_parse):
        inserted = insiders.persist_insiders(conn, "EBAY")

    assert inserted == 1
    row = conn.execute(
        "SELECT transaction_type, shares, price, filer_role"
        " FROM insider_filings WHERE accession_number = ?",
        ("0001234567-26-000123",),
    ).fetchone()
    assert row == ("P", 10000.0, 27.5, "Chief Executive Officer")
