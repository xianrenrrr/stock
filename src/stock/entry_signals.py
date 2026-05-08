"""stock.entry_signals -- weekly scan: which tracked names are NOW in their
recommended pullback entry zone?

Boss directive 2026-05-08: "when you think it's a good time to enter flag it
in weekly report". This module:
* iterates every conviction watchlist + company dive-queue ticker
* computes the F24 entry zone (MA20 + swing-low + ATR-based pullback range)
* classifies each as IN_ZONE / ABOVE / BELOW
* aggregates the IN_ZONE hits into a markdown report
* persists as research_reports kind='entry_signals' so the APK shows it

No LLM cost -- pure price-table arithmetic. Free to run any time.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml
from pydantic import BaseModel

from stock.stops import compute_entry_zone
from stock.tech_trends import load_conviction

logger = logging.getLogger(__name__)

DIVE_QUEUE_PATH: str = "data/company_dive_queue.yaml"

# Classify "in zone" generously: current price within +/-2% of the
# recommended zone. Below zone = "broke support, watch for stabilization".
IN_ZONE_TOLERANCE: float = 0.02


class EntrySignal(BaseModel):
    """One ticker's entry-zone classification at scan time."""

    ticker: str
    current_price: float
    zone_low: float
    zone_high: float
    classification: str  # IN_ZONE | ABOVE | BELOW
    pct_from_zone_high: float  # negative if below the zone
    note: str


def _collect_tracked_tickers(conn: sqlite3.Connection) -> set[str]:
    """Union of conviction watchlist + dive queue (enabled-only)."""
    out: set[str] = set()
    for n in load_conviction(enabled_only=True):
        out.add(n.ticker.upper())
    p = Path(DIVE_QUEUE_PATH)
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for c in data.get("companies", []) or []:
            if c.get("enabled", True) and c.get("ticker"):
                out.add(str(c["ticker"]).upper())
    return out


def scan_for_entry_signals(conn: sqlite3.Connection) -> list[EntrySignal]:
    """Walk every tracked ticker; compute zone; classify."""
    out: list[EntrySignal] = []
    for ticker in sorted(_collect_tracked_tickers(conn)):
        try:
            zone = compute_entry_zone(ticker, conn)
        except Exception:  # noqa: BLE001 -- per-ticker isolation
            logger.debug("entry_zone failed for %s", ticker, exc_info=True)
            continue
        if zone.current_price is None or zone.recommended_zone_low is None:
            continue
        cur = zone.current_price
        lo = zone.recommended_zone_low
        hi = zone.recommended_zone_high or lo
        # Tolerance band around the zone
        in_zone_lo = lo * (1 - IN_ZONE_TOLERANCE)
        in_zone_hi = hi * (1 + IN_ZONE_TOLERANCE)

        if cur < in_zone_lo:
            classification = "BELOW"
        elif cur > in_zone_hi:
            classification = "ABOVE"
        else:
            classification = "IN_ZONE"

        pct_from_hi = (cur / hi - 1) * 100 if hi > 0 else 0
        out.append(EntrySignal(
            ticker=ticker, current_price=cur,
            zone_low=lo, zone_high=hi,
            classification=classification,
            pct_from_zone_high=pct_from_hi,
            note=zone.note,
        ))
    return out


def render_report(signals: list[EntrySignal]) -> str:
    """Render the weekly entry-signal markdown."""
    in_zone = [s for s in signals if s.classification == "IN_ZONE"]
    below = [s for s in signals if s.classification == "BELOW"]
    above = [s for s in signals if s.classification == "ABOVE"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [
        f"# 入场信号扫描 / Weekly entry-signal scan -- {today}",
        "",
        f"_Scanned {len(signals)} tracked tickers (conviction + dive queue). "
        f"**{len(in_zone)} now IN_ZONE** -- candidate pullback entries._",
        "",
        "---",
        "",
    ]

    if in_zone:
        lines.append("## ✅ IN ZONE -- pullback entry candidates")
        lines.append("")
        lines.append("| Ticker | Current | Zone | Position | Note |")
        lines.append("| --- | ---: | --- | ---: | --- |")
        for s in sorted(in_zone, key=lambda x: x.ticker):
            zone = f"${s.zone_low:.2f} -- ${s.zone_high:.2f}"
            pos = f"{s.pct_from_zone_high:+.1f}% vs zone top"
            lines.append(
                f"| **{s.ticker}** | ${s.current_price:.2f} | {zone} | "
                f"{pos} | {s.note} |"
            )
        lines.append("")
    else:
        lines.append("## ✅ IN ZONE -- _none this week_")
        lines.append("")
        lines.append(
            "All tracked names are either still extended (above the pullback zone) "
            "or have broken below structural support. Wait for one to pull back."
        )
        lines.append("")

    if below:
        lines.append("## ⚠️ BELOW ZONE -- broke support, watch for stabilization")
        lines.append("")
        lines.append("| Ticker | Current | Zone | Below by |")
        lines.append("| --- | ---: | --- | ---: |")
        for s in sorted(below, key=lambda x: x.pct_from_zone_high):
            zone = f"${s.zone_low:.2f} -- ${s.zone_high:.2f}"
            below_by = f"{(s.current_price / s.zone_low - 1) * 100:+.1f}% vs zone low"
            lines.append(
                f"| {s.ticker} | ${s.current_price:.2f} | {zone} | {below_by} |"
            )
        lines.append("")

    if above:
        lines.append(f"## ⏳ ABOVE ZONE -- still extended ({len(above)} names)")
        lines.append("")
        lines.append("Tickers currently extended above the recommended pullback zone. "
                     "Wait. Not actionable this week.")
        lines.append("")
        lines.append("| Ticker | Current | Zone top | Distance |")
        lines.append("| --- | ---: | ---: | ---: |")
        for s in sorted(above, key=lambda x: -x.pct_from_zone_high):
            lines.append(
                f"| {s.ticker} | ${s.current_price:.2f} | "
                f"${s.zone_high:.2f} | {s.pct_from_zone_high:+.1f}% |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Methodology_: pullback zone = MA20 to -1 ATR, filtered to -3% to "
        "-20% from current. Tolerance ±2% so 'in zone' captures names testing "
        "the upper band. **Action**: scale in 1/3 on first touch, 2/3 if it "
        "consolidates above the zone for 2+ sessions. Set stop just below "
        "the zone-low (recommended F24 stop)."
    )
    lines.append("")
    lines.append("_Not financial advice._")
    return "\n".join(lines)


def persist_report(conn: sqlite3.Connection, body: str) -> int:
    """Insert as research_reports kind='entry_signals'; return research_id."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO research_reports (kind, topic, body, created_at)"
        " VALUES ('entry_signals', ?, ?, ?)",
        (f"入场信号扫描 {today}", body, now),
    )
    conn.commit()
    return int(cur.lastrowid)


def run_and_persist(conn: sqlite3.Connection) -> tuple[int, list[EntrySignal]]:
    """Convenience: scan, render, persist; return (research_id, signals)."""
    signals = scan_for_entry_signals(conn)
    body = render_report(signals)
    rid = persist_report(conn, body)
    return rid, signals
