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
    """Accept flat snapshots, MCP tool payloads, and the multi-account format.

    The multi-account shape is `{"accounts": [{"account_number", "positions": [...]}]}`;
    we flatten it and tag each position with its own account_number so per-account
    bookkeeping survives the merge.
    """
    if isinstance(raw.get("positions"), list):
        return raw["positions"]
    accounts = raw.get("accounts")
    if isinstance(accounts, list):
        flat: list[dict[str, Any]] = []
        for acct in accounts:
            if not isinstance(acct, dict):
                continue
            acct_no = acct.get("account_number")
            for pos in acct.get("positions") or []:
                if isinstance(pos, dict):
                    flat.append({**pos, "account_number": pos.get("account_number") or acct_no})
        return flat
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
    deactivate_missing: bool = True,
) -> BrokerSyncResult:
    """Sync non-zero filled positions from a Robinhood snapshot into holdings.

    deactivate_missing controls whether holdings absent from the snapshot are
    marked inactive (i.e. treated as sold). The AUTOMATED pull passes False
    because the Robinhood MCP is unreliable in headless sessions -- an empty or
    partial snapshot must NEVER wipe real holdings. Even when True, deactivation
    only happens within accounts that actually returned at least one position
    (an account with zero returned positions is treated as "could not read",
    not "sold everything").
    """
    default_account = _account_number(snapshot)
    as_of = str(snapshot.get("as_of") or datetime.now(timezone.utc).isoformat())
    result = BrokerSyncResult(path=path, account_number=default_account, as_of=as_of)
    seen_by_account: dict[str, set[str]] = {}

    # Aggregate same-ticker positions across accounts BEFORE upserting: VEEV
    # held in both margin and cash is ONE logical holding, and holdings rows
    # are keyed by ticker -- without this, the second account's upsert
    # silently overwrites the first instead of combining quantities.
    agg: dict[str, dict[str, Any]] = {}
    for pos in _positions_from_snapshot(snapshot):
        if not isinstance(pos, dict):
            continue
        ticker = str(pos.get("symbol") or pos.get("ticker") or "").strip().upper()
        qty = _to_float(pos.get("quantity") or pos.get("qty"))
        if not ticker or qty <= 0:
            result.skipped_empty += 1
            continue

        acct = str(pos.get("account_number") or default_account or "").strip() or None
        cost_basis = _to_float(
            pos.get("average_buy_price")
            or pos.get("average_cost")
            or pos.get("cost_basis")
        )
        ptype = str(pos.get("type") or "")

        prev = agg.get(ticker)
        if prev is None:
            agg[ticker] = {
                "qty": qty,
                "cost_basis": cost_basis,
                "accounts": [(acct, ptype)],
            }
        else:
            total_qty = prev["qty"] + qty
            if total_qty > 0:
                prev["cost_basis"] = (
                    prev["qty"] * prev["cost_basis"] + qty * cost_basis
                ) / total_qty
            prev["qty"] = total_qty
            prev["accounts"].append((acct, ptype))

    for ticker, info in agg.items():
        notes = " | ".join(_broker_note(acct, as_of, ptype) for acct, ptype in info["accounts"])
        holdings.add_holding(
            conn,
            ticker=ticker,
            qty=info["qty"],
            cost_basis=info["cost_basis"],
            notes=notes,
        )
        for acct, _ in info["accounts"]:
            if acct:
                seen_by_account.setdefault(acct, set()).add(ticker)
        result.upserted += 1

    # Deactivate sold positions ONLY within accounts that returned at least one
    # position, and only when explicitly requested. Never wipe on an empty pull.
    if deactivate_missing:
        for acct, seen in seen_by_account.items():
            like = f"{BROKER_TAG}%account={acct}%"
            rows = conn.execute(
                "SELECT ticker FROM holdings WHERE active = 1 AND notes LIKE ?",
                (like,),
            ).fetchall()
            for row in rows:
                ticker = str(row[0]).upper()
                if ticker not in seen and holdings.remove_holding(conn, ticker):
                    result.deactivated += 1

    return result


def import_snapshot_file(
    conn: sqlite3.Connection,
    path: str | Path = DEFAULT_SNAPSHOT_PATH,
    *,
    deactivate_missing: bool = True,
) -> BrokerSyncResult:
    """Import a snapshot file if present; missing files are a quiet no-op."""
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        return BrokerSyncResult(path=str(snapshot_path), missing=True)
    raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"broker snapshot must be a JSON object: {snapshot_path}")
    return import_snapshot(
        conn, raw, path=str(snapshot_path), deactivate_missing=deactivate_missing,
    )


# --- Robinhood positions PULL bridge (read-only) ---------------------------
# The background orchestrator cannot call the robinhood-trading MCP directly, so
# we spawn a codex session to READ live positions (get_equity_positions) and
# write them to the snapshot file, which import_snapshot_file() then ingests.
# This is the pull mirror of the broker snapshot import -- strictly read-only,
# never places or cancels an order.

class BrokerPullError(RuntimeError):
    """Raised when an RH-MCP positions-pull subprocess fails."""


CLAUDE_BIN: str = "claude"


def _finalize_pull_payload(
    payload: object, snapshot_path: str | Path, *, source: str
) -> dict:
    """Validate a positions payload and write the snapshot file.

    Shared tail of the codex and claude pull paths. Raises BrokerPullError on
    anything unusable -- CRITICALLY including zero positions, because a flaky
    or unauthenticated MCP returning nothing must never be mistaken for
    "sold everything" and wipe real holdings.
    """
    if not isinstance(payload, dict):
        raise BrokerPullError(f"{source} output is not a JSON object")

    positions = _positions_from_snapshot(payload)
    errors = payload.get("errors") or []
    if not positions:
        detail = "; ".join(str(e) for e in errors) or "no positions returned"
        raise BrokerPullError(f"RH MCP returned no positions via {source} ({detail})")

    sp = Path(snapshot_path)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    accounts = payload.get("accounts")
    return {
        "count": len(positions),
        "accounts": len(accounts) if isinstance(accounts, list) else 1,
        "written_to": str(sp),
        "source": source,
        "raw": payload,
    }


def build_positions_pull_instruction() -> str:
    """Read-only codex/RH-MCP instruction: fetch positions for EVERY account."""
    return (
        "You MUST actually invoke the robinhood-trading MCP tools (do NOT return "
        "an empty result without calling them). Steps: (1) call `get_accounts` "
        "and capture EVERY account_number. (2) For EACH account_number, call "
        "`get_equity_positions` with that account_number. (3) If any tool errors "
        "or the MCP is unavailable, report it in `errors`.\n"
        "Output ONLY a JSON object in EXACTLY this shape (numbers as numbers):\n"
        '{"as_of": "<iso8601 utc>", "accounts": [ {"account_number": "<acct>", '
        '"type": "<margin|cash>", "positions": [ {"symbol": "AAPL", '
        '"quantity": 10, "average_buy_price": 150.0} ... ]} ], "errors": []}\n'
        "Include every open position with a non-zero quantity.\n\n"
        "ABSOLUTE SAFETY RULES: this is READ-ONLY. Do NOT call "
        "place_equity_order or cancel_equity_order. Do NOT place, modify, or "
        "cancel any order. Only read positions."
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
        return _finalize_pull_payload(payload, snapshot_path, source="codex")
    finally:
        try:
            Path(out_file).unlink()
        except OSError:
            pass


def pull_positions_via_claude(
    *,
    snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH,
    claude_bin: str = CLAUDE_BIN,
    timeout_secs: int = CODEX_PULL_TIMEOUT_SECS,
) -> dict:
    """Spawn a `claude -p` / RH-MCP session to read live positions (read-only).

    Mirror of pull_positions_via_codex on the Claude CLI: the robinhood-trading
    MCP is registered at user scope (`claude mcp add --transport http ...`) and
    must be OAuth-authenticated once via `/mcp` in an interactive session.
    Raises BrokerPullError on missing binary / timeout / non-zero exit /
    unparseable output / zero positions.
    """
    instruction = build_positions_pull_instruction()
    resolved = shutil.which(claude_bin) or claude_bin
    argv = [
        resolved, "-p",
        "--output-format", "text",
        "--dangerously-skip-permissions",
    ]
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            argv, input=instruction, capture_output=True, text=True,
            encoding="utf-8", timeout=timeout_secs, creationflags=creation_flags,
        )
    except FileNotFoundError as exc:
        raise BrokerPullError(
            f"`{resolved}` not on PATH; install Claude Code + `claude login`"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise BrokerPullError(
            f"claude positions pull timed out after {timeout_secs}s"
        ) from exc

    if proc.returncode != 0:
        raise BrokerPullError(
            f"claude exit={proc.returncode}: {(proc.stderr or '').strip()[:400]}"
        )

    raw_text = (proc.stdout or "").strip()
    try:
        from stock.models import parse_llm_json

        payload = parse_llm_json(raw_text) if raw_text else None
    except Exception as exc:  # noqa: BLE001 -- any parse failure is a pull failure
        raise BrokerPullError(f"claude returned non-JSON positions: {exc}") from exc
    return _finalize_pull_payload(payload, snapshot_path, source="claude")


def pull_positions(
    *, snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH
) -> dict:
    """Pull live positions via Claude first, falling back to codex.

    Boss directive 2026-06-11: Claude is the primary CLI (codex was flaky on
    the RH MCP); keeping both doubles the chance a pull lands. Until the
    Claude-side MCP OAuth is completed once, the claude attempt fails fast and
    codex carries the job exactly as before.
    """
    try:
        return pull_positions_via_claude(snapshot_path=snapshot_path)
    except BrokerPullError as exc:
        logger.warning("claude positions pull failed (%s); trying codex", exc)
    return pull_positions_via_codex(snapshot_path=snapshot_path)
