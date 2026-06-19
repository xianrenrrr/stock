"""stock.universe -- ranking candidate universe + mega-cap deprioritization (#6).

The Amber tool ranks ~4,360 candidates and BLACKLISTS the mega-caps
(AAPL/MSFT/NVDA) -- they are efficiently priced, over-covered, and carry little
cross-sectional edge. Our live watchlist is ~14 names; this widens the ranking
pool using tables we already populate (watchlist + discovery + small-cap
candidates) and lets a basket exclude the mega-caps where alpha is thin.
"""
from __future__ import annotations

import sqlite3

# Over-covered mega-caps: efficiently priced, little cross-sectional edge.
# Excluded from long baskets by default (mirrors the Amber blacklist).
MEGA_CAPS: frozenset[str] = frozenset({
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO",
})


def is_megacap(ticker: str) -> bool:
    return ticker.upper() in MEGA_CAPS


def ranking_universe(conn: sqlite3.Connection, *, include_megacaps: bool = False) -> set[str]:
    """Widen the candidate pool beyond the live watchlist using existing tables.

    Pulls active watchlist + recently promoted discovery candidates + recent
    small-cap candidates, so cross-sectional ranking can reach names a 14-ticker
    watchlist never sees. Mega-caps excluded unless asked for.
    """
    tickers: set[str] = set()
    for sql in (
        "SELECT ticker FROM watchlist WHERE active = 1",
        "SELECT ticker FROM discovery_candidates"
        " WHERE last_score_at >= datetime('now','-30 days')",
        "SELECT ticker FROM smallcap_candidates"
        " WHERE detected_at >= datetime('now','-30 days')",
    ):
        try:
            tickers.update(str(r[0]).upper() for r in conn.execute(sql))
        except sqlite3.OperationalError:
            continue  # table may not exist in a minimal test DB
    if not include_megacaps:
        tickers -= MEGA_CAPS
    return tickers
