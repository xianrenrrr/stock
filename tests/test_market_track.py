"""tests.test_market_track -- CN/US report track assignment."""
from __future__ import annotations

import pytest

from stock.market_track import CN, US, market_track, partition_by_track


@pytest.mark.parametrize(
    "ticker,expected",
    [
        ("600941.SS", CN),   # A-share (Shanghai)
        ("002156.SZ", CN),   # A-share (Shenzhen)
        ("0941.HK", CN),     # H-share (Hong Kong)
        ("600941.ss", CN),   # case-insensitive
        ("NVDA", US),        # US-listed
        ("TSM", US),         # US ADR -> US track
        ("BABA", US),        # US ADR -> US track
        ("", US),            # empty -> US default
    ],
)
def test_market_track(ticker: str, expected: str) -> None:
    assert market_track(ticker) == expected


def test_ah_dual_listed_both_map_to_cn() -> None:
    """An A/H dual-listed name lands in CN from either leg."""
    assert market_track("600941.SS") == CN
    assert market_track("0941.HK") == CN


def test_partition_by_track_preserves_order_and_keys() -> None:
    tickers = ["NVDA", "600941.SS", "TSM", "0941.HK", "002156.SZ"]
    buckets = partition_by_track(tickers)
    assert buckets[CN] == ["600941.SS", "0941.HK", "002156.SZ"]
    assert buckets[US] == ["NVDA", "TSM"]


def test_partition_always_has_both_keys() -> None:
    buckets = partition_by_track(["NVDA"])
    assert set(buckets) == {CN, US}
    assert buckets[CN] == []
