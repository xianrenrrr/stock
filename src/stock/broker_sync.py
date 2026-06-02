"""Broker-position snapshot import for externally connected trading tools.

The Python orchestrator cannot call Codex MCP tools directly.  Codex/RH MCP
sessions can, however, write a small JSON snapshot that this module imports
into the local holdings table.  Only non-zero filled positions become holdings;
queued orders are deliberately ignored until they fill.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from stock import holdings

logger = logging.getLogger(__name__)

DEFAULT_SNAPSHOT_PATH = Path("data/robinhood_positions_snapshot.json")
BROKER_TAG = "[broker:robinhood"

CODEX_BIN: str = "codex"
CODEX_PULL_TIMEOUT_SECS: int = 300


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


# --- Robinhood positions PULL bridge (read-only) ---------------------------
# The background orchestrator cannot call the robinhood-trading MCP directly, so
# we spawn a codex session to READ live positions (get_equity_positions) and
# write them to the snapshot file, which import_snapshot_file() then ingests.
# This is the pull mirror of the broker snapshot import -- strictly read-only,
# never places or cancels an order.

class BrokerPullError(RuntimeError):
    """Raised when the codex / RH-MCP positions-pull subprocess fails."""


def build_positions_pull_instruction() -> str:
    """Read-only codex/RH-MCP instruction: fetch current positions as a snapshot."""
    return (
        "Using the robinhood-trading MCP, fetch the operator's CURRENT open "
        "equity positions. Call `get_accounts` to get the account_number if "
        "needed, then `get_equity_positions`. Output ONLY a JSON object in "
        "EXACTLY this shape (numbers as numbers, not strings):\n"
        '{"account_number": "<acct>", "as_of": "<iso8601 utc>", '
        '"positions": [ {"symbol": "AAPL", "quantity": 10, '
        '"average_buy_price": 150.0, "type": "long"} ... ]}\n\n'
        "ABSOLUTE SAFETY RULES: this is READ-ONLY. Do NOT call "
        "place_equity_order or cancel_equity_order. Do NOT place, modify, or "
        "cancel any order. Only read positions. Include every open position with "
        "a non-zero quantity."
    )


def pull_positions_via_codex(
    *,
    snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH,
    codex_bin: str = CODEX_BIN,
    timeout_secs: int = CODEX_PULL_TIMEOUT_SECS,
) -> dict:
    """Spawn a codex / RH-MCP session to read live positions; write the snapshot.

    Returns {count, account_number, written_to, raw}. Raises BrokerPullError if
    codex is missing / times out / exits non-zero / returns unparseable output.
    The written file is the same shape import_snapshot_file() expects.
    """
    instruction = build_positions_pull_instruction()
    resolved = shutil.which(codex_bin) or codex_bin
    out_handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8",
    )
    out_file = out_handle.name
    out_handle.close()

    argv = [
        resolved, "exec",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "-o", out_file,
    ]
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        try:
            proc = subprocess.run(
                argv, input=instruction, capture_output=True, text=True,
                encoding="utf-8", timeout=timeout_secs, creationflags=creation_flags,
            )
        except FileNotFoundError as exc:
            raise BrokerPullError(
                f"`{resolved}` not on PATH; install Codex CLI + `codex login`"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise BrokerPullError(
                f"codex positions pull timed out after {timeout_secs}s"
            ) from exc

        try:
            raw_text = Path(out_file).read_text(encoding="utf-8").strip()
        except OSError:
            raw_text = ""
        if proc.returncode != 0:
            raise BrokerPullError(
                f"codex exit={proc.returncode}: {(proc.stderr or '').strip()[:400]}"
            )
        try:
            payload = json.loads(raw_text) if raw_text else None
        except json.JSONDecodeError as exc:
            raise BrokerPullError(f"codex returned non-JSON positions: {exc}") from exc
        if not isinstance(payload, dict) or "positions" not in payload:
            raise BrokerPullError("codex output missing a 'positions' list")

        sp = Path(snapshot_path)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "count": len(payload.get("positions") or []),
            "account_number": payload.get("account_number"),
            "written_to": str(sp),
            "raw": payload,
        }
    finally:
        try:
            Path(out_file).unlink()
        except OSError:
            pass
