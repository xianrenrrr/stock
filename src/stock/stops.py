"""stock.stops -- compute concrete stop-loss prices for ticker suggestions.

F24: every research-note recommendation must come with a real stop-loss price,
not "you should set one." The boss asked for this directly. We compute three
candidate stops per ticker and return all three so the LLM can pick the most
appropriate one (or the operator can override based on conviction):

  - ATR stop  : entry - 2 * ATR(20)         tight-but-realistic for swing trades
  - Swing low : most recent N-day pivot low recent structural support
  - Percent   : entry * (1 - 0.15)           hard cap for high-volatility names

The helper never raises -- if a ticker has no price history we return None
fields so the LLM can flag "needs data" instead of fabricating numbers.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

logger = logging.getLogger(__name__)

ATR_LOOKBACK_DAYS: int = 20
ATR_MULTIPLIER: float = 2.0
SWING_LOW_LOOKBACK_DAYS: int = 30
PERCENT_STOP: float = 0.15
PRICE_HISTORY_DAYS: int = 60


class StopLossSuggestion(BaseModel):
    """Three candidate stop-loss prices for a ticker, plus a recommended pick."""

    ticker: str
    entry_price: float | None       # most recent close, used as proxy entry
    atr_20: float | None            # 20-day average true range
    atr_stop: float | None          # entry - 2 * ATR
    swing_low_30d: float | None     # most recent 30d pivot low
    percent_stop: float | None      # entry * 0.85
    recommended: float | None       # max of (atr_stop, swing_low) -- tightest defensible
    rationale: str                  # one-line explanation


def _fetch_recent_bars(
    conn: sqlite3.Connection, ticker: str, days: int = PRICE_HISTORY_DAYS,
) -> list[tuple[str, float, float, float, float]]:
    """Return (ts, o, h, l, c) tuples for the last `days` bars, oldest-first."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT ts, o, h, l, c FROM prices WHERE ticker = ? AND ts >= ?"
        " ORDER BY ts ASC",
        (ticker.upper(), cutoff),
    ).fetchall()
    return [(r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows]


def _compute_atr(bars: list[tuple[str, float, float, float, float]], n: int) -> float | None:
    """Wilder-ish ATR: mean of true-range over last N bars."""
    if len(bars) < 2:
        return None
    last = bars[-n - 1:] if len(bars) > n + 1 else bars
    trs: list[float] = []
    for i in range(1, len(last)):
        h, l, _c = last[i][2], last[i][3], last[i][4]
        prev_c = last[i - 1][4]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    if not trs:
        return None
    return sum(trs) / len(trs)


def _swing_low(
    bars: list[tuple[str, float, float, float, float]], days: int,
) -> float | None:
    """Lowest LOW over the last `days` bars."""
    if not bars:
        return None
    window = bars[-days:] if len(bars) > days else bars
    return min(b[3] for b in window)


def compute_stop_loss(
    ticker: str, conn: sqlite3.Connection,
    *, entry_override: float | None = None,
) -> StopLossSuggestion:
    """Compute three stop-loss candidates + a recommended pick for a ticker.

    entry_override lets the caller pass the actual fill price when known;
    otherwise we use the latest close as a proxy.
    """
    bars = _fetch_recent_bars(conn, ticker)
    if not bars:
        return StopLossSuggestion(
            ticker=ticker, entry_price=None, atr_20=None, atr_stop=None,
            swing_low_30d=None, percent_stop=None, recommended=None,
            rationale="No price history -- ingest prices first via `stock ingest prices <ticker>`.",
        )

    entry = float(entry_override) if entry_override is not None else bars[-1][4]
    atr = _compute_atr(bars, ATR_LOOKBACK_DAYS)
    atr_stop = entry - ATR_MULTIPLIER * atr if atr is not None else None
    swing = _swing_low(bars, SWING_LOW_LOOKBACK_DAYS)
    pct_stop = entry * (1 - PERCENT_STOP)

    # Recommended: the TIGHTEST defensible stop -- whichever of {atr_stop, swing_low}
    # is HIGHER (closer to entry) defines real structural support; if both are
    # below percent_stop, fall back to percent_stop as the absolute floor.
    candidates = [s for s in (atr_stop, swing) if s is not None]
    if not candidates:
        recommended = pct_stop
        rationale = (
            f"Fallback: {PERCENT_STOP:.0%} below entry ${entry:.2f} = ${pct_stop:.2f}."
            " (ATR + swing-low unavailable.)"
        )
    else:
        recommended = max(candidates)
        # Sanity: never recommend a stop that's higher than entry
        if recommended >= entry:
            recommended = pct_stop
            rationale = (
                f"Swing-low ${swing:.2f} above entry ${entry:.2f} (recent rally);"
                f" using {PERCENT_STOP:.0%} fallback at ${pct_stop:.2f}."
            )
        else:
            picked = "ATR-based" if recommended == atr_stop else "swing-low"
            distance_pct = (entry - recommended) / entry * 100
            rationale = (
                f"{picked} stop ${recommended:.2f} ({distance_pct:.1f}% below entry"
                f" ${entry:.2f}); ATR(20)=${atr:.2f}, swing-low(30d)=${swing:.2f}"
                if atr is not None and swing is not None
                else f"Stop ${recommended:.2f} ({distance_pct:.1f}% below entry ${entry:.2f})."
            )

    return StopLossSuggestion(
        ticker=ticker, entry_price=entry, atr_20=atr, atr_stop=atr_stop,
        swing_low_30d=swing, percent_stop=pct_stop, recommended=recommended,
        rationale=rationale,
    )


def format_stop_loss_block(
    conn: sqlite3.Connection, tickers: list[str],
) -> str:
    """Render stop-loss suggestions for a list of tickers as a markdown block.

    Used by research.generate_daily_research to inject pre-computed stops into
    the prompt context so the LLM cites real numbers (not fabricated ones).
    """
    if not tickers:
        return "(no tickers to compute stops for)"
    lines = ["| Ticker | Entry | ATR(20) | ATR stop | 30d swing-low | -15% | Recommended |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for t in tickers:
        s = compute_stop_loss(t, conn)
        if s.entry_price is None:
            lines.append(f"| {t} | N/A -- needs data | | | | | |")
            continue
        lines.append(
            f"| {t} | ${s.entry_price:.2f}"
            f" | ${s.atr_20:.2f}" if s.atr_20 is not None else " | N/A"
            f" | ${s.atr_stop:.2f}" if s.atr_stop is not None else " | N/A"
            f" | ${s.swing_low_30d:.2f}" if s.swing_low_30d is not None else " | N/A"
            f" | ${s.percent_stop:.2f}"
            f" | **${s.recommended:.2f}** |"
        )
    return "\n".join(lines)
