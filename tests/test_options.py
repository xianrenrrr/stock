"""tests.test_options -- F36 unusual options activity detector."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from stock import db
from stock.options import (
    _ChainRow,
    detect_unusual,
    format_uoa_block,
    persist,
    recent_anomalies,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    """In-memory DB with full schema."""
    return db.get_conn(":memory:")


def _row(strike: float, vol: float | None, oi: float | None, iv: float = 0.55,
         symbol: str | None = None) -> _ChainRow:
    return _ChainRow(
        contract_symbol=symbol or f"EBAY260515C{int(strike*1000):08d}",
        strike=strike, volume=vol, open_interest=oi, implied_vol=iv,
    )


def test_detect_flags_ebay_pattern() -> None:
    """20,856 contracts at $106 (near $103 close) -> caught with high score."""
    today = datetime(2026, 5, 4, tzinfo=timezone.utc)
    expiry = "2026-05-15"
    calls = [
        _row(95, 5, 200),       # OTM low-vol -- skip
        _row(100, 50, 100),     # below volume floor -- skip
        _row(106, 20856, 800),  # the one we want -- vol/OI ~26, EXTREME
        _row(108, 800, 100),    # below volume floor
    ]
    puts: list[_ChainRow] = []
    hits = detect_unusual(
        ticker="EBAY", underlying=103.0, expiries=[expiry],
        chain_provider=lambda _e: (calls, puts), today=today,
    )
    assert len(hits) == 1
    h = hits[0]
    assert h.ticker == "EBAY"
    assert h.option_type == "call"
    assert h.strike == 106
    assert h.volume == 20856
    assert h.vol_oi_ratio == pytest.approx(20856 / 800)
    assert h.score > 15  # extreme by construction
    assert "EXTREME" in h.flag_reason


def test_detect_skips_far_otm() -> None:
    """High vol/OI but strike 30% from spot -> filtered."""
    today = datetime(2026, 5, 4, tzinfo=timezone.utc)
    calls = [_row(150, 50000, 100)]  # 50% above $100
    hits = detect_unusual(
        ticker="X", underlying=100.0, expiries=["2026-05-15"],
        chain_provider=lambda _e: (calls, []), today=today,
    )
    assert hits == []


def test_detect_skips_far_expiry() -> None:
    """Expiry > 75 days out -> not flagged."""
    today = datetime(2026, 5, 4, tzinfo=timezone.utc)
    expiry_far = "2026-09-15"  # ~134 days
    calls = [_row(105, 20000, 1000)]
    hits = detect_unusual(
        ticker="X", underlying=100.0, expiries=[expiry_far],
        chain_provider=lambda _e: (calls, []), today=today,
    )
    assert hits == []


def test_detect_handles_zero_oi_as_fresh_series() -> None:
    """OI=0 (brand-new strike) should still flag if volume is huge."""
    today = datetime(2026, 5, 4, tzinfo=timezone.utc)
    calls = [_row(102, 5000, 0)]
    hits = detect_unusual(
        ticker="X", underlying=100.0, expiries=["2026-05-15"],
        chain_provider=lambda _e: (calls, []), today=today,
    )
    assert len(hits) == 1
    assert hits[0].vol_oi_ratio == 5000.0  # treated as ratio = volume


def test_detect_caps_results_per_ticker() -> None:
    """Only the top TOP_PER_TICKER hits are returned."""
    today = datetime(2026, 5, 4, tzinfo=timezone.utc)
    # 8 qualifying contracts; module is configured to keep top 5
    calls = [
        _row(100 + i, 5000 + i * 100, 500, symbol=f"X{i}")
        for i in range(8)
    ]
    hits = detect_unusual(
        ticker="X", underlying=100.0, expiries=["2026-05-15"],
        chain_provider=lambda _e: (calls, []), today=today,
    )
    assert len(hits) == 5
    # And they should be the highest-volume ones
    assert all(h.volume >= 5300 for h in hits)


def test_persist_and_query_round_trip(conn: sqlite3.Connection) -> None:
    """persist + recent_anomalies recovers the rows ordered by score."""
    today = datetime(2026, 5, 4, tzinfo=timezone.utc)
    calls = [_row(106, 20856, 800)]
    hits = detect_unusual(
        ticker="EBAY", underlying=103.0, expiries=["2026-05-15"],
        chain_provider=lambda _e: (calls, []), today=today,
    )
    n = persist(conn, hits)
    assert n == 1
    rows = recent_anomalies(conn, days=1, limit=10)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "EBAY"
    assert rows[0]["volume"] == 20856


def test_format_uoa_block_renders_table(conn: sqlite3.Connection) -> None:
    """format_uoa_block emits a markdown table when there are hits."""
    today = datetime(2026, 5, 4, tzinfo=timezone.utc)
    calls = [_row(106, 20856, 800, iv=0.58)]
    hits = detect_unusual(
        ticker="EBAY", underlying=103.0, expiries=["2026-05-15"],
        chain_provider=lambda _e: (calls, []), today=today,
    )
    persist(conn, hits)
    block = format_uoa_block(conn, days=1, limit=5)
    assert "| Ticker |" in block
    assert "EBAY" in block
    assert "$106" in block
    assert "58%" in block  # IV rendered as percent


def test_format_uoa_block_empty_when_nothing(conn: sqlite3.Connection) -> None:
    """No detections -> empty string (caller suppresses the section header)."""
    assert format_uoa_block(conn, days=1) == ""
