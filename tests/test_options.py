"""tests.test_options -- F36 unusual options activity detector."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from stock import db
from stock.options import (
    _ChainRow,
    compute_ratio_snapshot,
    detect_unusual,
    format_ratio_block,
    format_uoa_block,
    persist,
    persist_ratio_snapshot,
    recent_anomalies,
    recent_ratio_snapshots,
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


def test_compute_ratio_snapshot_aggregates_nearby_expiries() -> None:
    """Ratio snapshots aggregate calls and puts across expiries within 75 days."""
    today = datetime(2026, 5, 4, tzinfo=timezone.utc)
    chains = {
        "2026-05-15": (
            [_row(100, 1000, 500), _row(105, 500, 300)],
            [_row(95, 250, 400)],
        ),
        "2026-06-19": (
            [_row(100, 200, 100)],
            [_row(90, 50, 200), _row(85, None, None)],
        ),
        "2026-09-18": (
            [_row(100, 99999, 99999)],
            [_row(100, 99999, 99999)],
        ),
    }

    snapshot = compute_ratio_snapshot(
        ticker="EBAY",
        expiries=list(chains),
        chain_provider=lambda expiry: chains[expiry],
        today=today,
    )

    assert snapshot.ticker == "EBAY"
    assert snapshot.call_volume == 1700
    assert snapshot.put_volume == 300
    assert snapshot.call_open_interest == 900
    assert snapshot.put_open_interest == 600
    assert snapshot.call_put_volume_ratio == pytest.approx(1700 / 300)
    assert snapshot.put_call_volume_ratio == pytest.approx(300 / 1700)
    assert snapshot.call_put_oi_ratio == pytest.approx(900 / 600)
    assert snapshot.expiries_scanned == 2
    assert snapshot.contracts_scanned == 6


def test_persist_ratio_snapshot_and_format_block(conn: sqlite3.Connection) -> None:
    """Persisted ratio snapshots round-trip and render as a compact table."""
    snapshot = compute_ratio_snapshot(
        ticker="TIGR",
        expiries=["2026-05-15"],
        chain_provider=lambda _expiry: (
            [_row(10, 1000, 500)],
            [_row(9, 250, 125)],
        ),
        today=datetime(2026, 5, 4, tzinfo=timezone.utc),
    )

    assert persist_ratio_snapshot(conn, snapshot) == 1
    rows = recent_ratio_snapshots(conn, days=1, limit=5)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "TIGR"
    assert rows[0]["call_put_volume_ratio"] == pytest.approx(4.0)

    block = format_ratio_block(conn, days=1, limit=5)
    assert "| Ticker | Call Vol |" in block
    assert "TIGR" in block
    assert "4.00x" in block
