"""stock.anomaly -- detect daily volume/price anomalies on watchlist + holdings."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

logger = logging.getLogger(__name__)

VOLUME_RATIO_THRESHOLD: float = 1.5
PCT_CHANGE_THRESHOLD: float = 0.05
AVG_WINDOW_DAYS: int = 30
MAX_FLAGGED_PER_DAY: int = 25
MIN_AVG_VOLUME: int = 50_000


class AnomalyRow(BaseModel):
    """One detected price/volume anomaly."""

    id: int | None = None
    ticker: str
    ts: str
    pct_change: float
    volume_ratio: float
    flag_reason: str
    created_at: str


def _candidate_tickers(conn: sqlite3.Connection) -> list[str]:
    """Return tickers that appear in prices AND (watchlist OR holdings)."""
    rows = conn.execute(
        "SELECT DISTINCT p.ticker FROM prices p"
        " WHERE p.ticker IN ("
        "   SELECT ticker FROM watchlist WHERE active = 1"
        "   UNION"
        "   SELECT ticker FROM holdings WHERE active = 1"
        " )"
        " ORDER BY p.ticker"
    ).fetchall()
    return [r[0] for r in rows]


def _latest_two_bars(conn: sqlite3.Connection, ticker: str) -> list[tuple[str, float, int]]:
    """Return up to two most recent (ts, close, volume) rows for a ticker."""
    rows = conn.execute(
        "SELECT ts, c, v FROM prices WHERE ticker = ?"
        " ORDER BY ts DESC LIMIT 2",
        (ticker,),
    ).fetchall()
    return [(str(r[0]), float(r[1]), int(r[2])) for r in rows]


def _avg_volume_excluding_latest(
    conn: sqlite3.Connection, ticker: str, latest_ts: str, window_days: int
) -> float:
    """Average daily volume over the prior window, excluding the latest bar."""
    rows = conn.execute(
        "SELECT v FROM prices WHERE ticker = ? AND ts < ?"
        " ORDER BY ts DESC LIMIT ?",
        (ticker, latest_ts, window_days),
    ).fetchall()
    if not rows:
        return 0.0
    vols = [int(r[0]) for r in rows]
    return float(sum(vols)) / float(len(vols))


def compute_daily_anomalies(conn: sqlite3.Connection) -> list[AnomalyRow]:
    """Compute and UPSERT today's anomalies for every relevant ticker.

    Flags a ticker when its latest close/prior-close pct change exceeds
    PCT_CHANGE_THRESHOLD or its latest volume / 30d average volume exceeds
    VOLUME_RATIO_THRESHOLD. Tickers with avg volume below MIN_AVG_VOLUME
    are skipped to avoid illiquid noise.
    """
    flagged: list[AnomalyRow] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # Iterate every active watchlist + holdings ticker that has prices
    for ticker in _candidate_tickers(conn):
        if len(flagged) >= MAX_FLAGGED_PER_DAY:
            break

        bars = _latest_two_bars(conn, ticker)
        if len(bars) < 2:
            continue

        # Bars are DESC-sorted, so index 0 is latest
        latest_ts, latest_close, latest_vol = bars[0]
        _, prev_close, _ = bars[1]
        if prev_close <= 0:
            continue

        avg_vol = _avg_volume_excluding_latest(conn, ticker, latest_ts, AVG_WINDOW_DAYS)
        if avg_vol < MIN_AVG_VOLUME:
            continue

        pct_change = (latest_close - prev_close) / prev_close
        volume_ratio = float(latest_vol) / avg_vol if avg_vol else 0.0

        # Decide whether either threshold triggers a flag
        is_volume_spike = volume_ratio >= VOLUME_RATIO_THRESHOLD
        is_price_move = abs(pct_change) >= PCT_CHANGE_THRESHOLD
        if not (is_volume_spike or is_price_move):
            continue

        if is_volume_spike and is_price_move:
            reason = "both"
        elif is_volume_spike:
            reason = "volume_spike"
        else:
            reason = "price_move"

        # UPSERT idempotent on (ticker, ts)
        conn.execute(
            "INSERT INTO price_anomalies (ticker, ts, pct_change, volume_ratio,"
            " flag_reason, created_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(ticker, ts) DO UPDATE SET"
            " pct_change=excluded.pct_change, volume_ratio=excluded.volume_ratio,"
            " flag_reason=excluded.flag_reason, created_at=excluded.created_at",
            (ticker, latest_ts, pct_change, volume_ratio, reason, now_iso),
        )
        flagged.append(
            AnomalyRow(
                ticker=ticker,
                ts=latest_ts,
                pct_change=pct_change,
                volume_ratio=volume_ratio,
                flag_reason=reason,
                created_at=now_iso,
            )
        )
    conn.commit()
    return flagged


def recent_anomalies(conn: sqlite3.Connection, *, days: int = 2) -> list[AnomalyRow]:
    """Return all anomalies whose ts falls within the last N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    rows = conn.execute(
        "SELECT id, ticker, ts, pct_change, volume_ratio, flag_reason, created_at"
        " FROM price_anomalies WHERE ts >= ?"
        " ORDER BY ts DESC, ticker ASC",
        (cutoff,),
    ).fetchall()
    return [
        AnomalyRow(
            id=int(r[0]),
            ticker=str(r[1]),
            ts=str(r[2]),
            pct_change=float(r[3]),
            volume_ratio=float(r[4]),
            flag_reason=str(r[5]),
            created_at=str(r[6]),
        )
        for r in rows
    ]


def format_anomaly_block(rows: list[AnomalyRow]) -> str:
    """Render anomaly rows as a compact bullet block for prompt injection."""
    if not rows:
        return "(no anomalies in the last 24-48h on watchlist/holdings)"

    lines: list[str] = []
    for row in rows:
        pct = f"{row.pct_change * 100:+.2f}%"
        vol = f"{row.volume_ratio:.2f}x"
        lines.append(
            f"- [{row.ts}] {row.ticker} | pct={pct} | vol={vol} | reason={row.flag_reason}"
        )
    return "\n".join(lines)
