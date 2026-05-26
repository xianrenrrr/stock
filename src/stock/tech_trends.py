"""stock.tech_trends -- F41/F42 tech-trend atlas + conviction watchlist.

Two YAML files drive everything:
  data/tech_trends.yaml         -- 10 specific tech trends with falsification
  data/conviction_watchlist.yaml-- 10 deeply-tracked tickers, 1 per trend

Both have an `enabled: bool` flag so the operator can swap without delete.
This module provides:
  * load_trends / load_conviction         read YAML, filter by enabled
  * pick_focus_trend                       day-of-year rotation across enabled trends
  * format_trend_radar_block               markdown for the daily research note
  * format_conviction_watchlist_block      same, with live prices + F24 stops
  * toggle / swap / add / remove           mutate the YAMLs (used by CLI)

Boss directive 2026-05-06: don't be a news reporter. Lead the daily note
with these two layers; demote news + web_discovery to a footer.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

TRENDS_PATH: str = "data/tech_trends.yaml"
CONVICTION_PATH: str = "data/conviction_watchlist.yaml"


class TechTrend(BaseModel):
    """One specific tech trend with evidence + falsification + vehicles."""

    id: str
    name: str
    sector: str           # ai_compute | ai_biopharma | energy | space_tech | ...
    horizon: str          # "2-3y" | "3-5y" | "4-5y"
    why_now: list[str]
    falsification: list[str]
    vehicles_pure_play: list[str]
    vehicles_diversified: list[str] = []
    ai_biopharma_combo: bool = False
    enabled: bool = True


class ConvictionName(BaseModel):
    """One deeply-tracked ticker linked to a trend."""

    ticker: str
    name: str
    trend_id: str
    why: str
    enabled: bool = True


# ============================================================================
# Load + persist
# ============================================================================


def load_trends(*, path: str = TRENDS_PATH, enabled_only: bool = True) -> list[TechTrend]:
    """Read tech_trends.yaml, optionally filter to enabled."""
    p = Path(path)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    rows = data.get("trends") or []
    out: list[TechTrend] = []
    for r in rows:
        try:
            t = TechTrend(**r)
        except Exception:  # noqa: BLE001 -- malformed row, log + skip
            logger.warning("skip malformed trend: %s", r.get("id", "?"), exc_info=True)
            continue
        if enabled_only and not t.enabled:
            continue
        out.append(t)
    return out


def load_conviction(*, path: str = CONVICTION_PATH, enabled_only: bool = True) -> list[ConvictionName]:
    """Read conviction_watchlist.yaml, optionally filter to enabled."""
    p = Path(path)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    rows = data.get("names") or []
    out: list[ConvictionName] = []
    for r in rows:
        try:
            n = ConvictionName(**r)
        except Exception:  # noqa: BLE001
            logger.warning("skip malformed conviction row: %s", r.get("ticker", "?"), exc_info=True)
            continue
        if enabled_only and not n.enabled:
            continue
        out.append(n)
    return out


def _save_yaml(path: str, root_key: str, rows: list[dict[str, Any]]) -> None:
    """Write YAML preserving key order + readable formatting."""
    p = Path(path)
    payload = {root_key: rows}
    p.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, default_flow_style=False, width=200),
        encoding="utf-8",
    )


def _load_raw(path: str, root_key: str) -> list[dict[str, Any]]:
    """Load YAML rows as raw dicts (preserves all fields incl unknowns for round-trip)."""
    p = Path(path)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    rows = data.get(root_key) or []
    return [dict(r) for r in rows if isinstance(r, dict)]


# ============================================================================
# Mutate (toggle / swap / add / remove)
# ============================================================================


def toggle_trend(trend_id: str, *, path: str = TRENDS_PATH) -> bool:
    """Flip the `enabled` flag on a trend; returns the new value or raises if not found."""
    rows = _load_raw(path, "trends")
    for r in rows:
        if r.get("id") == trend_id:
            r["enabled"] = not bool(r.get("enabled", True))
            _save_yaml(path, "trends", rows)
            return bool(r["enabled"])
    raise KeyError(f"trend id not found: {trend_id}")


def swap_trends(disable_id: str, enable_id: str, *, path: str = TRENDS_PATH) -> None:
    """Atomic swap: disable one trend, enable another."""
    rows = _load_raw(path, "trends")
    seen_disable = seen_enable = False
    for r in rows:
        if r.get("id") == disable_id:
            r["enabled"] = False
            seen_disable = True
        if r.get("id") == enable_id:
            r["enabled"] = True
            seen_enable = True
    if not seen_disable:
        raise KeyError(f"trend id not found (disable target): {disable_id}")
    if not seen_enable:
        raise KeyError(f"trend id not found (enable target): {enable_id}")
    _save_yaml(path, "trends", rows)


def add_trend(trend: TechTrend, *, path: str = TRENDS_PATH) -> None:
    """Append a new trend; raises if id already exists."""
    rows = _load_raw(path, "trends")
    for r in rows:
        if r.get("id") == trend.id:
            raise ValueError(f"trend id already exists: {trend.id}")
    rows.append(trend.model_dump())
    _save_yaml(path, "trends", rows)


def remove_trend(trend_id: str, *, path: str = TRENDS_PATH) -> None:
    """Hard-delete a trend by id."""
    rows = _load_raw(path, "trends")
    new_rows = [r for r in rows if r.get("id") != trend_id]
    if len(new_rows) == len(rows):
        raise KeyError(f"trend id not found: {trend_id}")
    _save_yaml(path, "trends", new_rows)


def toggle_conviction(ticker: str, *, path: str = CONVICTION_PATH) -> bool:
    """Flip the `enabled` flag on a conviction-list ticker."""
    rows = _load_raw(path, "names")
    for r in rows:
        if str(r.get("ticker", "")).upper() == ticker.upper():
            r["enabled"] = not bool(r.get("enabled", True))
            _save_yaml(path, "names", rows)
            return bool(r["enabled"])
    raise KeyError(f"conviction ticker not found: {ticker}")


def swap_conviction(disable_ticker: str, enable_ticker: str, *, path: str = CONVICTION_PATH) -> None:
    """Atomic swap on conviction list."""
    rows = _load_raw(path, "names")
    seen_disable = seen_enable = False
    for r in rows:
        t = str(r.get("ticker", "")).upper()
        if t == disable_ticker.upper():
            r["enabled"] = False
            seen_disable = True
        if t == enable_ticker.upper():
            r["enabled"] = True
            seen_enable = True
    if not seen_disable:
        raise KeyError(f"conviction ticker not found (disable): {disable_ticker}")
    if not seen_enable:
        raise KeyError(f"conviction ticker not found (enable): {enable_ticker}")
    _save_yaml(path, "names", rows)


def add_conviction(name: ConvictionName, *, path: str = CONVICTION_PATH) -> None:
    """Append a new conviction-list ticker; raises if already present."""
    rows = _load_raw(path, "names")
    for r in rows:
        if str(r.get("ticker", "")).upper() == name.ticker.upper():
            raise ValueError(f"conviction ticker already exists: {name.ticker}")
    rows.append(name.model_dump())
    _save_yaml(path, "names", rows)


def remove_conviction(ticker: str, *, path: str = CONVICTION_PATH) -> None:
    """Hard-delete a conviction-list ticker."""
    rows = _load_raw(path, "names")
    new_rows = [r for r in rows if str(r.get("ticker", "")).upper() != ticker.upper()]
    if len(new_rows) == len(rows):
        raise KeyError(f"conviction ticker not found: {ticker}")
    _save_yaml(path, "names", new_rows)


# ============================================================================
# Render (for daily research note)
# ============================================================================


def pick_focus_trend(
    trends: list[TechTrend], *, now: datetime | None = None,
) -> TechTrend | None:
    """Day-of-year rotation across enabled trends; deterministic, no randomness."""
    if not trends:
        return None
    now = now or datetime.now(timezone.utc)
    return trends[now.timetuple().tm_yday % len(trends)]


def format_trend_radar_block(trend: TechTrend | None) -> str:
    """Render the focus-trend block for the daily research note."""
    if trend is None:
        return "(no enabled trends -- run `stock trend list` to inspect)"
    lines = [
        f"### {trend.name}",
        f"_Sector: {trend.sector} | Horizon: {trend.horizon} | "
        f"AI x biopharma: {'YES' if trend.ai_biopharma_combo else 'no'}_",
        "",
        "**为何当下 / Why now (specific evidence, not narrative):**",
    ]
    for ev in trend.why_now:
        lines.append(f"- {ev}")
    lines.append("")
    lines.append("**证伪信号 / Falsification triggers:**")
    for fs in trend.falsification:
        lines.append(f"- {fs}")
    lines.append("")
    pure = ", ".join(trend.vehicles_pure_play) or "(none)"
    div = ", ".join(trend.vehicles_diversified) or "(none)"
    lines.append(f"**纯标的 / Pure-play vehicle:** {pure}")
    lines.append(f"**间接受益 / Diversified exposure:** {div}")
    return "\n".join(lines)


def format_conviction_watchlist_block(
    conn: sqlite3.Connection,
    names: list[ConvictionName],
) -> str:
    """Render the conviction watchlist as a markdown table.

    Pulls latest close from prices table + F24 recommended stop.
    Empty string when list is empty so caller can suppress the section.
    """
    if not names:
        return ""
    from stock.stops import compute_stop_loss

    lines = [
        "| Ticker | Name | Sector trigger | Last | Stop (F24) | 距止损 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for n in names:
        row = conn.execute(
            "SELECT c FROM prices WHERE ticker = ? ORDER BY ts DESC LIMIT 1",
            (n.ticker.upper(),),
        ).fetchone()
        last = float(row[0]) if row else 0.0
        try:
            sl = compute_stop_loss(n.ticker, conn)
            stop = sl.recommended if sl.recommended else 0.0
        except Exception:  # noqa: BLE001 -- be tolerant
            stop = 0.0
        if last > 0 and stop > 0:
            dist_pct = (last / stop - 1) * 100
            dist_s = f"{dist_pct:+.1f}%"
        else:
            dist_s = "-"
        last_s = f"${last:.2f}" if last > 0 else "?"
        stop_s = f"${stop:.2f}" if stop > 0 else "N/A"
        # Trim 'why' to 60 chars for table rendering
        trigger = n.why if len(n.why) <= 60 else n.why[:57] + "..."
        lines.append(
            f"| {n.ticker} | {n.name[:24]} | {trigger} | "
            f"{last_s} | {stop_s} | {dist_s} |"
        )
    return "\n".join(lines)
