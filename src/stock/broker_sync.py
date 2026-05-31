"""Broker-position snapshot import for externally connected trading tools.

The Python orchestrator cannot call Codex MCP tools directly.  Codex/RH MCP
sessions can, however, write a small JSON snapshot that this module imports
into the local holdings table.  Only non-zero filled positions become holdings;
queued orders are deliberately ignored until they fill.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from stock import holdings

logger = logging.getLogger(__name__)

DEFAULT_SNAPSHOT_PATH = Path("data/robinhood_positions_snapshot.json")
BROKER_TAG = "[broker:robinhood"


class BrokerSyncResult(BaseModel):
    """Summary of one broker snapshot import."""

    path: str
    account_number: str | None = None
    as_of: str | None = None
    upserted: int = 0
    deactivated: int = 0
    skipped_empty: int = 0
    missing: bool = False


def _to_float(value: object) -> float:
    """Parse Robinhood numeric strings without raising on blanks/nulls."""
    if value is None:
        return 0.0
    try:
        return float(str(value).strip() or "0")
    except (TypeError, ValueError):
        return 0.0


def _positions_from_snapshot(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept both direct snapshots and MCP tool response payloads."""
    if isinstance(raw.get("positions"), list):
        return raw["positions"]
    data = raw.get("data")
    if isinstance(data, dict) and isinstance(data.get("positions"), list):
        return data["positions"]
    return []


def _account_number(raw: dict[str, Any]) -> str | None:
    account = raw.get("account_number") or raw.get("account")
    if account:
        return str(account).strip()
    data = raw.get("data")
    if isinstance(data, dict):
        account = data.get("account_number") or data.get("account")
        if account:
            return str(account).strip()
    return None


def _broker_note(account_number: str | None, as_of: str | None, ptype: str) -> str:
    parts = ["[broker:robinhood"]
    if account_number:
        parts.append(f"account={account_number}")
    if as_of:
        parts.append(f"as_of={as_of}")
    if ptype:
        parts.append(f"type={ptype}")
    return " ".join(parts) + "] synced from Robinhood MCP filled position snapshot"


def import_snapshot(
    conn: sqlite3.Connection,
    snapshot: dict[str, Any],
    *,
    path: str = "",
) -> BrokerSyncResult:
    """Sync non-zero filled positions from a Robinhood snapshot into holdings."""
    account = _account_number(snapshot)
    as_of = str(snapshot.get("as_of") or datetime.now(timezone.utc).isoformat())
    result = BrokerSyncResult(path=path, account_number=account, as_of=as_of)
    seen: set[str] = set()

    for pos in _positions_from_snapshot(snapshot):
        if not isinstance(pos, dict):
            continue
        ticker = str(pos.get("symbol") or pos.get("ticker") or "").strip().upper()
        qty = _to_float(pos.get("quantity") or pos.get("qty"))
        ptype = str(pos.get("type") or "")
        if not ticker or qty <= 0:
            result.skipped_empty += 1
            continue

        cost_basis = _to_float(
            pos.get("average_buy_price")
            or pos.get("average_cost")
            or pos.get("cost_basis")
        )
        holdings.add_holding(
            conn,
            ticker=ticker,
            qty=qty,
            cost_basis=cost_basis,
            notes=_broker_note(account, as_of, ptype),
        )
        seen.add(ticker)
        result.upserted += 1

    # Only deactivate rows previously created from this same broker account.
    # Manual holdings and YAML-managed holdings are intentionally untouched.
    if account:
        like = f"{BROKER_TAG}%account={account}%"
        rows = conn.execute(
            "SELECT ticker FROM holdings WHERE active = 1 AND notes LIKE ?",
            (like,),
        ).fetchall()
        for row in rows:
            ticker = str(row[0]).upper()
            if ticker not in seen:
                if holdings.remove_holding(conn, ticker):
                    result.deactivated += 1

    return result


def import_snapshot_file(
    conn: sqlite3.Connection,
    path: str | Path = DEFAULT_SNAPSHOT_PATH,
) -> BrokerSyncResult:
    """Import a snapshot file if present; missing files are a quiet no-op."""
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        return BrokerSyncResult(path=str(snapshot_path), missing=True)
    raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"broker snapshot must be a JSON object: {snapshot_path}")
    return import_snapshot(conn, raw, path=str(snapshot_path))
