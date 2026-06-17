"""stock.market_track -- assign a ticker to a report track: 'CN' or 'US'.

Boss spec (2026-06-17), confirming the CN/US 双轨 design:
- A-share and H-share names are BOTH China: any ticker with a Shanghai (.SS),
  Shenzhen (.SZ), or Hong Kong (.HK) suffix is the 'CN' track. An A/H dual-listed
  name (e.g. 600941.SS + 0941.HK) lands in 'CN' from either leg -- no split.
- Everything else (US-listed equities and ADRs, which carry no foreign suffix) is
  the 'US' track.
- History is NOT re-partitioned: hit-rate / grading stays global. This module only
  decides which forward-looking report a ticker belongs to.
"""
from __future__ import annotations

from typing import Iterable

CN_SUFFIXES: tuple[str, ...] = (".SS", ".SZ", ".HK")
CN: str = "CN"
US: str = "US"


def market_track(ticker: str) -> str:
    """Return the report track for a ticker: 'CN' (A/H China) or 'US'.

    A/H dual-listed names map to 'CN' from either the .SS/.SZ or the .HK leg.
    Tickers with no recognized China suffix (incl. US ADRs like TSM, BABA) are 'US'.
    """
    t = (ticker or "").strip().upper()
    if not t:
        return US
    if any(t.endswith(suffix) for suffix in CN_SUFFIXES):
        return CN
    return US


def partition_by_track(tickers: Iterable[str]) -> dict[str, list[str]]:
    """Split tickers into {'CN': [...], 'US': [...]}, preserving input order.

    Both keys are always present (possibly with empty lists) so callers can
    iterate tracks without key-existence checks.
    """
    buckets: dict[str, list[str]] = {CN: [], US: []}
    for ticker in tickers:
        buckets[market_track(ticker)].append(ticker)
    return buckets
