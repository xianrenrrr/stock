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
    """Render holdings as a bullet block with live P&L when prices available."""
    if not rows:
        return "(no active holdings tracked yet)"

    lines: list[str] = []
    for h in rows:
        close = _latest_close(conn, h.ticker)
        pnl_str = "P&L=N/A"
        if close is not None and h.cost_basis > 0:
            pnl_pct = (close - h.cost_basis) / h.cost_basis
            pnl_str = f"P&L={pnl_pct * 100:+.1f}% (last={close:.2f})"
        notes = f" -- {h.notes}" if h.notes else ""
        lines.append(
            f"- {h.ticker} | qty={h.qty:g} | cost={h.cost_basis:.2f} | {pnl_str}{notes}"
        )
    return "\n".join(lines)
