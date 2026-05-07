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


class EntryZone(BaseModel):
    """Pullback entry zone analysis for a ticker."""

    ticker: str
    current_price: float | None
    ma20: float | None
    ma50: float | None
    swing_low_30d: float | None
    swing_low_60d: float | None
    atr_20: float | None
    atr_minus_1: float | None  # current - 1 ATR (shallow pullback)
    atr_minus_2: float | None  # current - 2 ATR (deeper pullback)
    pct_minus_5: float | None
    pct_minus_10: float | None
    recommended_zone_low: float | None
    recommended_zone_high: float | None
    note: str


def compute_entry_zone(ticker: str, conn: sqlite3.Connection) -> EntryZone:
    """Compute pullback entry zones for a ticker.

    The 'recommended zone' is chosen as the OVERLAP of:
      * MA20 vicinity (mid-trend support)
      * 30-day swing-low cluster (structural support)
      * -1 ATR from current (shallow pullback)
    Returns the high/low of where to consider scaling in. Boss directive:
    "等到回踩时建仓" -- size up on pullback, not on strength.
    """
    bars = _fetch_recent_bars(conn, ticker, days=80)
    if not bars or len(bars) < 20:
        return EntryZone(
            ticker=ticker.upper(), current_price=None, ma20=None, ma50=None,
            swing_low_30d=None, swing_low_60d=None, atr_20=None,
            atr_minus_1=None, atr_minus_2=None, pct_minus_5=None,
            pct_minus_10=None, recommended_zone_low=None,
            recommended_zone_high=None, note="insufficient price history",
        )

    closes = [b[4] for b in bars]
    current = closes[-1]
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    atr = _compute_atr(bars[-21:], n=20)  # most recent 20 daily bars
    swing30 = _swing_low(bars, days=30)
    swing60 = _swing_low(bars, days=60)

    atr_minus_1 = (current - atr) if (atr and current) else None
    atr_minus_2 = (current - 2 * atr) if (atr and current) else None
    pct_minus_5 = current * 0.95 if current else None
    pct_minus_10 = current * 0.90 if current else None

    # Recommended zone: between MA20 and -1 ATR; floor with 30d swing-low when
    # they conflict (so we don't recommend an entry above structural support
    # the stock has already broken through).
    # Filter candidates to "actionable pullback range" -- between -3% and -20%
    # below current. Levels deeper than -20% are typically structural-break
    # zones (flash crashes, prior bear markets) that aren't a swing-trade entry.
    candidates: list[float] = []
    cap_low = current * 0.80 if current else 0
    cap_high = current * 0.97 if current else 0
    for lvl in (ma20, atr_minus_1, atr_minus_2, swing30):
        if lvl is None or current is None:
            continue
        if cap_low <= lvl <= cap_high:
            candidates.append(lvl)

    if not candidates:
        # Fall back to a clean -3% to -10% band when nothing clusters
        if current:
            rec_low, rec_high = current * 0.90, current * 0.97
            note = "no clean technical level in -3 to -20% range; using -3 to -10% default"
        else:
            rec_low = rec_high = None
            note = "no clear pullback zone"
    else:
        rec_low = min(candidates)
        rec_high = max(candidates)
        if rec_low == rec_high:
            rec_high = rec_low * 1.02
        if current and rec_high > current * 0.99:
            note = "near current; wait for pullback test"
        elif current and (current - rec_low) / current > 0.15:
            note = "deeper pullback zone -- scale in only on a confirmed turn"
        else:
            note = "moderate pullback zone -- scale in on test"

    return EntryZone(
        ticker=ticker.upper(), current_price=current,
        ma20=ma20, ma50=ma50,
        swing_low_30d=swing30, swing_low_60d=swing60,
        atr_20=atr,
        atr_minus_1=atr_minus_1, atr_minus_2=atr_minus_2,
        pct_minus_5=pct_minus_5, pct_minus_10=pct_minus_10,
        recommended_zone_low=rec_low, recommended_zone_high=rec_high,
        note=note,
    )


def format_entry_zone(z: EntryZone) -> str:
    """Render entry-zone analysis as markdown for terminal/APK display."""
    if z.current_price is None:
        return f"# {z.ticker} 入场区间 / Entry zone\n\n_(insufficient price data)_"

    def _f(v: float | None) -> str:
        return f"${v:.2f}" if v is not None else "N/A"

    lines = [
        f"# {z.ticker} 入场区间 / Entry zone",
        "",
        f"**当前价 / Current**: {_f(z.current_price)}",
        "",
        "## 关键技术位 / Key levels",
        f"- 20日均线 MA20: {_f(z.ma20)}",
        f"- 50日均线 MA50: {_f(z.ma50)}",
        f"- 30日低点 / 30d swing-low: {_f(z.swing_low_30d)}",
        f"- 60日低点 / 60d swing-low: {_f(z.swing_low_60d)}",
        "",
        "## ATR + 百分比回撤 / ATR + percent pullback",
        f"- ATR(20): {_f(z.atr_20)}",
        f"- -1 ATR (浅回撤 shallow): {_f(z.atr_minus_1)}",
        f"- -2 ATR (深回撤 deeper): {_f(z.atr_minus_2)}",
        f"- -5%: {_f(z.pct_minus_5)}",
        f"- -10%: {_f(z.pct_minus_10)}",
        "",
        "## 推荐建仓区间 / Recommended entry zone",
        f"- **{_f(z.recommended_zone_low)} -- {_f(z.recommended_zone_high)}**",
        f"- {z.note}",
        "",
        "_Not financial advice._",
    ]
    return "\n".join(lines)


def format_stop_loss_block(
    conn: sqlite3.Connection, tickers: list[str],
) -> str:
    """Render stop-loss suggestions for a list of tickers as a markdown block.

    Used by research.generate_daily_research to inject pre-computed stops into
    the prompt context so the LLM cites real numbers (not fabricated ones).
    """
    if not tickers:
        return "(no tickers to compute stops for)"

    def _cell(value: float | None, *, prefix: str = "$") -> str:
        return f"{prefix}{value:.2f}" if value is not None else "N/A"

    lines = ["| Ticker | Entry | ATR(20) | ATR stop | 30d swing-low | -15% | Recommended |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for t in tickers:
        s = compute_stop_loss(t, conn)
        if s.entry_price is None:
            lines.append(f"| {t} | N/A -- needs data | | | | | |")
            continue
        rec = f"**${s.recommended:.2f}**" if s.recommended is not None else "N/A"
        lines.append(
            f"| {t} "
            f"| {_cell(s.entry_price)} "
            f"| {_cell(s.atr_20)} "
            f"| {_cell(s.atr_stop)} "
            f"| {_cell(s.swing_low_30d)} "
            f"| {_cell(s.percent_stop)} "
            f"| {rec} |"
        )
    return "\n".join(lines)
