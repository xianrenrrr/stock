"""stock.holdings -- portfolio tracker fed by data/holdings.yaml + DB."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

HOLDINGS_PATH: str = "data/holdings.yaml"


class Holding(BaseModel):
    """One row of the holdings table."""

    ticker: str
    qty: float
    cost_basis: float
    opened_at: str
    notes: str = ""
    active: bool = True
    updated_at: str = ""


def _row_to_holding(row: tuple) -> Holding:
    """Convert a SELECT row into a Holding model."""
    return Holding(
        ticker=str(row[0]),
        qty=float(row[1]),
        cost_basis=float(row[2]),
        opened_at=str(row[3]),
        notes=str(row[4] or ""),
        active=bool(row[5]),
        updated_at=str(row[6]),
    )


def list_holdings(
    conn: sqlite3.Connection, *, active_only: bool = True
) -> list[Holding]:
    """Return rows from the holdings table, optionally filtering inactive ones."""
    query = (
        "SELECT ticker, qty, cost_basis, opened_at, notes, active, updated_at"
        " FROM holdings"
    )
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY ticker"
    rows = conn.execute(query).fetchall()
    return [_row_to_holding(r) for r in rows]


def add_holding(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    qty: float,
    cost_basis: float,
    notes: str = "",
    opened_at: str | None = None,
) -> Holding:
    """Insert or update a holding row idempotently."""
    ticker = ticker.upper().strip()
    if not ticker:
        raise ValueError("ticker is required")
    if qty <= 0:
        raise ValueError("qty must be positive")
    if cost_basis < 0:
        raise ValueError("cost_basis must be non-negative")

    now = datetime.now(timezone.utc).isoformat()
    opened_iso = opened_at or now

    conn.execute(
        "INSERT INTO holdings (ticker, qty, cost_basis, opened_at, notes,"
        " active, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?)"
        " ON CONFLICT(ticker) DO UPDATE SET qty=excluded.qty,"
        " cost_basis=excluded.cost_basis, notes=excluded.notes,"
        " active=1, updated_at=excluded.updated_at",
        (ticker, qty, cost_basis, opened_iso, notes, now),
    )
    conn.commit()
    return Holding(
        ticker=ticker, qty=qty, cost_basis=cost_basis,
        opened_at=opened_iso, notes=notes, active=True, updated_at=now,
    )


def remove_holding(conn: sqlite3.Connection, ticker: str) -> bool:
    """Set active=0 for a holding. Returns True when a row was modified."""
    ticker = ticker.upper().strip()
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "UPDATE holdings SET active = 0, updated_at = ? WHERE ticker = ?",
        (now, ticker),
    )
    conn.commit()
    return bool(cursor.rowcount)


def set_note(conn: sqlite3.Connection, ticker: str, note: str) -> bool:
    """Update the notes column for an existing holding."""
    ticker = ticker.upper().strip()
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "UPDATE holdings SET notes = ?, updated_at = ? WHERE ticker = ?",
        (note, now, ticker),
    )
    conn.commit()
    return bool(cursor.rowcount)


def sync_from_yaml(
    conn: sqlite3.Connection, *, path: str = HOLDINGS_PATH
) -> int:
    """Read YAML, upsert each row, mark missing tickers active=0."""
    cfg_path = Path(path)
    if not cfg_path.exists():
        return 0

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    rows = raw.get("holdings") or []
    if not isinstance(rows, list):
        return 0

    seen: set[str] = set()
    upserted = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        try:
            qty = float(row.get("qty", 0))
            cost_basis = float(row.get("cost_basis", 0))
        except (TypeError, ValueError):
            logger.warning("skip holdings row with bad numerics: %s", row)
            continue
        notes = str(row.get("notes", ""))
        opened_at = str(row.get("opened_at", "")) or None
        add_holding(
            conn, ticker=ticker, qty=qty, cost_basis=cost_basis,
            notes=notes, opened_at=opened_at,
        )
        seen.add(ticker)
        upserted += 1

    # Mark any DB rows not in YAML as inactive
    if seen:
        placeholders = ",".join("?" * len(seen))
        now = datetime.now(timezone.utc).isoformat()
        params: list[object] = [now]
        params.extend(seen)
        conn.execute(
            f"UPDATE holdings SET active = 0, updated_at = ?"
            f" WHERE ticker NOT IN ({placeholders})",
            params,
        )
        conn.commit()
    return upserted


def _latest_close(conn: sqlite3.Connection, ticker: str) -> float | None:
    """Return the most recent close price for a ticker, or None."""
    row = conn.execute(
        "SELECT c FROM prices WHERE ticker = ? ORDER BY ts DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not row:
        return None
    return float(row[0])


def format_holdings_block(rows: list[Holding], conn: sqlite3.Connection) -> str:
    """Render holdings as a markdown table with P&L + stop distance + alerts.

    Boss explicitly asked for sell-trigger awareness on every holding. This block
    is the at-a-glance risk dashboard that lands in every daily research note:

      Ticker | Qty | Cost | Last | P&L | Recommended stop | Stop dist | 7d alerts | 14d anomaly

    Stop distance is the gap between latest close and the F24 recommended stop
    (negative = below stop, sell-trigger fired). 7d alerts is the count of
    kind='alert' research_reports rows for the ticker in the last 7 days
    (F28 keyword scan output). 14d anomaly is the most-recent flag_reason
    in price_anomalies for this ticker, or '—'.

    Notes column omitted from the table to keep it scannable; full notes
    still live in data/holdings.yaml + the holdings table for context.
    """
    if not rows:
        return "(no active holdings tracked yet)"

    # Lazy imports to avoid cycles -- holdings is imported by many modules.
    from datetime import datetime, timedelta, timezone
    from stock.stops import compute_stop_loss

    lines: list[str] = [
        "| Ticker | Qty | Cost | Last | P&L | 推荐止损 | 距止损 | 7d alerts | 14d 异常 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    now = datetime.now(timezone.utc)
    week_iso = (now - timedelta(days=7)).isoformat()
    fortnight_date = (now - timedelta(days=14)).strftime("%Y-%m-%d")

    for h in rows:
        close = _latest_close(conn, h.ticker)
        last_str = f"${close:.2f}" if close is not None else "N/A"
        if close is not None and h.cost_basis > 0:
            pnl_pct = (close - h.cost_basis) / h.cost_basis
            pnl_str = f"{pnl_pct * 100:+.1f}%"
        else:
            pnl_str = "N/A"

        # F24 stop-loss
        stop = compute_stop_loss(h.ticker, conn)
        if stop.recommended is not None and close is not None:
            stop_str = f"${stop.recommended:.2f}"
            stop_dist_pct = (close - stop.recommended) / close * 100
            stop_dist_str = f"{stop_dist_pct:+.1f}%"
            if stop_dist_pct <= 0:
                stop_dist_str = f"⚠️ {stop_dist_str}"
        else:
            stop_str = "N/A"
            stop_dist_str = "N/A"

        # F28 alert count (last 7d)
        alert_row = conn.execute(
            "SELECT COUNT(*) FROM research_reports"
            " WHERE kind = 'alert' AND COALESCE(topic, '') LIKE ?"
            " AND created_at >= ?",
            (f"{h.ticker}%", week_iso),
        ).fetchone()
        alert_count = int(alert_row[0]) if alert_row else 0
        alert_str = f"⚠️ {alert_count}" if alert_count > 0 else "—"

        # F12 anomaly (last 14d, most recent)
        anom_row = conn.execute(
            "SELECT ts, pct_change, flag_reason FROM price_anomalies"
            " WHERE ticker = ? AND ts >= ? ORDER BY ts DESC LIMIT 1",
            (h.ticker, fortnight_date),
        ).fetchone()
        if anom_row:
            anom_str = f"[{anom_row[0]}] {anom_row[1] * 100:+.1f}% ({anom_row[2]})"
        else:
            anom_str = "—"

        cost_str = f"${h.cost_basis:.2f}" if h.cost_basis > 0 else "N/A"
        lines.append(
            f"| {h.ticker} | {h.qty:g} | {cost_str} | {last_str} | {pnl_str}"
            f" | {stop_str} | {stop_dist_str} | {alert_str} | {anom_str} |"
        )
    return "\n".join(lines)
