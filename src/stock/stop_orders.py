"""stock.stop_orders -- human-armed auto stop-loss order bridge.

Boss directive 2026-06-01: actually PLACE stop-loss orders for live holdings
(not just compute + alert). The background Python orchestrator cannot call the
Robinhood MCP directly, so this is a FILE BRIDGE (mirror of broker_sync.py, but
in the placing direction):

  1. `compute_desired_stops(conn)` turns each active holding + its F24 stop
     (stops.compute_stop_loss) into a desired SELL stop-LIMIT order.
  2. `write_proposal(...)` persists them to data/desired_stop_orders.json with
     mode='proposed'. The orchestrator only ever PROPOSES + alerts -- it never
     places.
  3. A human-armed step (`stock stops place --confirm`) spawns a codex / RH-MCP
     session that reads the proposal, runs `review_equity_order` (dry-run),
     dedups against `get_equity_orders`, then `place_equity_order` with
     type=stop_limit, and writes data/stop_orders_result.json.

SAFETY: nothing in this module places an order by itself. Placement only
happens when the operator explicitly runs the confirmed CLI path, which spawns
codex with a tightly-scoped instruction built here. Default is a review-only
dry run. The Robinhood account must be "agentic-allowed" for the MCP to place.
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

from pydantic import BaseModel

from stock.holdings import Holding, list_holdings
from stock.stops import compute_stop_loss

logger = logging.getLogger(__name__)

PROPOSAL_PATH: str = "data/desired_stop_orders.json"
RESULT_PATH: str = "data/stop_orders_result.json"

CODEX_BIN: str = "codex"
# Placement can wait on a live brokerage round-trip per order; give it room.
CODEX_PLACE_TIMEOUT_SECS: int = 600

# A SELL stop-LIMIT triggers a limit sell when the market falls to stop_price.
# We set the limit a small buffer BELOW the stop so the order still fills in a
# fast drop, while capping how far below the stop we are willing to sell (so a
# catastrophic gap-down does not dump at any price). 1% is a reasonable default.
LIMIT_BUFFER_PCT: float = 0.01
TIME_IN_FORCE: str = "gtc"  # good-till-cancelled so the stop persists across sessions


class DesiredStopOrder(BaseModel):
    """One intended SELL stop-limit order for a held position."""

    ticker: str
    qty: float
    side: str = "sell"
    type: str = "stop_limit"
    stop_price: float       # trigger price (F24 recommended stop)
    limit_price: float      # limit floor, a buffer below the stop
    time_in_force: str = TIME_IN_FORCE
    ref_id: str             # deterministic idempotency key for the broker
    basis: str              # short rationale from stops.py
    last_close: float
    computed_at: str


def _ref_id(ticker: str, stop_price: float, day: str) -> str:
    """Deterministic idempotency key so re-proposing the same stop never dupes.

    Changes when the stop level moves (cents) or the day rolls, which is the
    signal to replace a stale stop order rather than stack a second one.
    """
    return f"sl-{ticker.upper()}-{int(round(stop_price * 100))}-{day}"


def compute_desired_stops(
    conn: sqlite3.Connection, *, holdings: list[Holding] | None = None,
) -> list[DesiredStopOrder]:
    """Build a desired SELL stop-limit order for each active holding with a stop.

    Skips holdings with no price data, no recommended stop, non-positive qty, or
    a stop that is not safely below the latest close (a sell stop must sit below
    the current price). Never raises on a single bad ticker.
    """
    rows = holdings if holdings is not None else list_holdings(conn, active_only=True)
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    orders: list[DesiredStopOrder] = []

    for h in rows:
        if h.qty <= 0:
            continue
        try:
            stop = compute_stop_loss(h.ticker, conn)
        except Exception:
            logger.exception("stop computation failed for %s; skipping", h.ticker)
            continue
        if stop.recommended is None or stop.entry_price is None:
            continue
        stop_price = round(float(stop.recommended), 2)
        last_close = round(float(stop.entry_price), 2)
        # A sell stop must be below the current price, else it would trigger
        # immediately at market open. Skip rather than place a bad order.
        if stop_price <= 0 or stop_price >= last_close:
            logger.info(
                "skip %s: stop %.2f not below last close %.2f",
                h.ticker, stop_price, last_close,
            )
            continue
        limit_price = round(stop_price * (1 - LIMIT_BUFFER_PCT), 2)
        if limit_price <= 0:
            continue
        orders.append(DesiredStopOrder(
            ticker=h.ticker.upper(),
            qty=h.qty,
            stop_price=stop_price,
            limit_price=limit_price,
            ref_id=_ref_id(h.ticker, stop_price, day),
            basis=stop.rationale,
            last_close=last_close,
            computed_at=now.isoformat(timespec="seconds"),
        ))
    return orders


def write_proposal(
    orders: list[DesiredStopOrder], *, path: str = PROPOSAL_PATH,
) -> dict:
    """Persist proposed stop orders as JSON (mode='proposed'); return the payload."""
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "proposed",
        "order_type": "stop_limit",
        "count": len(orders),
        "orders": [o.model_dump() for o in orders],
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_proposal(*, path: str = PROPOSAL_PATH) -> dict | None:
    """Load the proposal file if present, else None."""
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def load_result(*, path: str = RESULT_PATH) -> dict | None:
    """Load the placement result file if present, else None."""
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def format_proposal_block(orders: list[DesiredStopOrder]) -> str:
    """Render proposed stop orders as a markdown table for alerts/email."""
    if not orders:
        return "(no stop orders to propose -- no eligible active holdings)"
    lines = [
        "| Ticker | Qty | Stop (trigger) | Limit (floor) | Last | Dist | ref_id |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for o in orders:
        dist = (o.last_close - o.stop_price) / o.last_close * 100 if o.last_close else 0.0
        lines.append(
            f"| {o.ticker} | {o.qty:g} | ${o.stop_price:.2f} | ${o.limit_price:.2f} "
            f"| ${o.last_close:.2f} | -{dist:.1f}% | {o.ref_id} |"
        )
    lines.append("")
    lines.append(
        "These are PROPOSED sell stop-limit orders. Nothing is placed until you "
        "arm it with `stock stops place --confirm`. Not financial advice."
    )
    return "\n".join(lines)


def build_review_instruction(proposal: dict) -> str:
    """Build a READ-ONLY codex/RH-MCP instruction: dry-run review only, no placing."""
    orders_json = json.dumps(proposal.get("orders", []), indent=2)
    return (
        "Using the robinhood-trading MCP, REVIEW (do NOT place) the following "
        "sell stop-limit orders. For EACH order call `review_equity_order` with "
        "side=sell, type=stop_limit, the given quantity, stop_price, limit_price, "
        "and time_in_force=gtc. Report the simulated result per order as JSON.\n\n"
        "ABSOLUTE SAFETY RULES:\n"
        "- Do NOT call place_equity_order. Do NOT call cancel_equity_order.\n"
        "- Do NOT place, modify, or cancel ANY order. Review/simulate ONLY.\n"
        "- Do NOT touch any position or order not listed below.\n\n"
        f"Orders to review:\n{orders_json}\n\n"
        "Output ONLY a JSON object: {\"reviewed\": [ {ticker, ok, detail}... ]}."
    )


def build_placement_instruction(proposal: dict) -> str:
    """Build the confirmed codex/RH-MCP instruction to PLACE the stop-limit orders.

    The instruction is deliberately rigid: review first, cancel only stale sell
    stops for the SAME ticker, place exactly the listed orders with the given
    ref_id (idempotency), and never touch anything else.
    """
    orders_json = json.dumps(proposal.get("orders", []), indent=2)
    return (
        "Using the robinhood-trading MCP, PLACE the following sell stop-limit "
        "stop-loss orders for the operator's account. Work strictly from this "
        "list and nothing else.\n\n"
        "STEP-BY-STEP, for EACH order in the list:\n"
        "1. Call `review_equity_order` (side=sell, type=stop_limit, quantity, "
        "stop_price, limit_price, time_in_force=gtc). If the review fails or the "
        "symbol is not tradable, SKIP that order and record the reason.\n"
        "2. Call `get_equity_orders` for the symbol; if an OPEN sell stop / "
        "stop_limit order already exists for this exact ref_id, SKIP (idempotent). "
        "If an OPEN sell stop exists for this symbol with a DIFFERENT ref_id, "
        "`cancel_equity_order` it first (it is a stale stop being replaced).\n"
        "3. Call `place_equity_order` (side=sell, type=stop_limit, the given "
        "quantity, stop_price, limit_price, time_in_force=gtc, and the given "
        "ref_id). Record the returned order_id.\n\n"
        "ABSOLUTE SAFETY RULES:\n"
        "- Place ONLY the orders listed below. Do NOT place buys. Do NOT place "
        "market orders. Do NOT alter quantities or prices.\n"
        "- Cancel ONLY a stale OPEN sell-stop on the SAME symbol being replaced. "
        "Never cancel any other order.\n"
        "- Never touch positions, buying power, or unrelated orders.\n\n"
        f"Orders to place:\n{orders_json}\n\n"
        "Output ONLY a JSON object: {\"placed\": [ {ticker, ref_id, order_id, "
        "status} ... ], \"skipped\": [ {ticker, reason} ... ]}."
    )


class StopOrderBridgeError(RuntimeError):
    """Raised when the codex / RH-MCP placement subprocess fails."""


def place_via_codex(
    proposal: dict,
    *,
    confirm: bool,
    result_path: str = RESULT_PATH,
    codex_bin: str = CODEX_BIN,
    timeout_secs: int = CODEX_PLACE_TIMEOUT_SECS,
) -> dict:
    """Spawn a codex / robinhood-trading MCP session to review or place stops.

    confirm=False (default) -> REVIEW-ONLY dry run (review_equity_order); no
    order is placed. confirm=True -> the confirmed placement instruction runs
    `place_equity_order`. The instruction is built here and is rigidly scoped to
    the proposal's orders. The codex subprocess inherits the operator's
    `codex login` and the robinhood-trading MCP from ~/.codex/config.toml.

    Returns a dict with keys: mode, raw (codex's JSON output, parsed if possible),
    written_to. Persists the result to `result_path`. Raises
    StopOrderBridgeError if codex is missing / times out / exits non-zero.
    """
    orders = proposal.get("orders") or []
    if not orders:
        return {"mode": "noop", "reason": "no orders in proposal", "raw": None}

    instruction = (
        build_placement_instruction(proposal) if confirm
        else build_review_instruction(proposal)
    )
    mode = "placed" if confirm else "review"

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
                argv,
                input=instruction,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_secs,
                creationflags=creation_flags,
            )
        except FileNotFoundError as exc:
            raise StopOrderBridgeError(
                f"`{resolved}` not on PATH; install Codex CLI + `codex login`"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise StopOrderBridgeError(
                f"codex stop-order bridge timed out after {timeout_secs}s"
            ) from exc

        try:
            raw_text = Path(out_file).read_text(encoding="utf-8").strip()
        except OSError:
            raw_text = ""

        if proc.returncode != 0:
            raise StopOrderBridgeError(
                f"codex exit={proc.returncode}: {(proc.stderr or '').strip()[:400]}"
            )

        parsed: dict | list | None
        try:
            parsed = json.loads(raw_text) if raw_text else None
        except json.JSONDecodeError:
            parsed = None

        result = {
            "mode": mode,
            "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "confirmed": confirm,
            "raw_text": raw_text,
            "parsed": parsed,
        }
        rp = Path(result_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result["written_to"] = str(rp)
        return result
    finally:
        try:
            Path(out_file).unlink()
        except OSError:
            pass
