"""tests.test_stop_orders -- human-armed auto stop-loss order bridge.

No test places a live order; the codex/RH-MCP subprocess is always mocked.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock import db, holdings, stop_orders
from stock.stop_orders import (
    DesiredStopOrder,
    StopOrderBridgeError,
    build_placement_instruction,
    build_review_instruction,
    compute_desired_stops,
    format_proposal_block,
    place_via_codex,
    write_proposal,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    return db.get_conn(":memory:")


def _seed_prices(conn: sqlite3.Connection, ticker: str, closes: list[float]) -> None:
    """Insert a simple ascending series of daily bars for a ticker."""
    base = datetime.now(timezone.utc) - timedelta(days=len(closes) - 1)
    for i, c in enumerate(closes):
        ts = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO prices (ticker, ts, o, h, l, c, v)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, ts, c, c * 1.01, c * 0.99, c, 1_000_000),
        )
    conn.commit()


def test_compute_desired_stops_builds_sell_stop_limit(conn: sqlite3.Connection) -> None:
    # Stable price history so a recommended stop exists below the last close.
    _seed_prices(conn, "NVDA", [100.0 + i * 0.2 for i in range(40)])
    holdings.add_holding(conn, ticker="NVDA", qty=10, cost_basis=90.0)

    orders = compute_desired_stops(conn)
    assert len(orders) == 1
    o = orders[0]
    assert o.ticker == "NVDA"
    assert o.side == "sell"
    assert o.type == "stop_limit"
    assert o.qty == 10
    # limit sits below the stop (fills in a fast drop, capped downside)
    assert o.limit_price < o.stop_price < o.last_close
    # limit is ~1% below the stop
    assert abs(o.limit_price - round(o.stop_price * 0.99, 2)) < 0.01
    assert o.ref_id.startswith("sl-NVDA-")


def test_compute_desired_stops_skips_when_no_prices(conn: sqlite3.Connection) -> None:
    holdings.add_holding(conn, ticker="ZZZZ", qty=5, cost_basis=10.0)
    # No price rows -> compute_stop_loss returns recommended=None -> skipped.
    assert compute_desired_stops(conn) == []


def test_ref_id_is_deterministic_and_idempotent(conn: sqlite3.Connection) -> None:
    _seed_prices(conn, "AMD", [50.0 + i * 0.1 for i in range(40)])
    holdings.add_holding(conn, ticker="AMD", qty=3, cost_basis=40.0)
    a = compute_desired_stops(conn)[0]
    b = compute_desired_stops(conn)[0]
    # Same holding + same stop + same day -> identical ref_id (broker dedups).
    assert a.ref_id == b.ref_id


def test_write_and_load_proposal_roundtrip(conn: sqlite3.Connection, tmp_path) -> None:
    _seed_prices(conn, "AVGO", [200.0 + i * 0.5 for i in range(40)])
    holdings.add_holding(conn, ticker="AVGO", qty=2, cost_basis=150.0)
    orders = compute_desired_stops(conn)
    path = str(tmp_path / "desired.json")
    payload = write_proposal(orders, path=path)
    assert payload["mode"] == "proposed"
    assert payload["count"] == 1
    loaded = stop_orders.load_proposal(path=path)
    assert loaded["orders"][0]["ticker"] == "AVGO"


def test_format_proposal_block_has_disclaimer() -> None:
    o = DesiredStopOrder(
        ticker="NVDA", qty=10, stop_price=95.0, limit_price=94.05,
        ref_id="sl-NVDA-9500-2026-06-01", basis="atr", last_close=100.0,
        computed_at="2026-06-01T20:10:00+00:00",
    )
    block = format_proposal_block([o])
    assert "NVDA" in block
    assert "$95.00" in block
    assert "Not financial advice" in block
    assert format_proposal_block([]).startswith("(no stop orders")


def test_review_instruction_is_strictly_read_only() -> None:
    proposal = {"orders": [{"ticker": "NVDA", "qty": 10, "stop_price": 95.0,
                            "limit_price": 94.05, "ref_id": "sl-NVDA-9500-x"}]}
    instr = build_review_instruction(proposal)
    assert "review_equity_order" in instr
    assert "Do NOT call place_equity_order" in instr
    assert "NVDA" in instr


def test_placement_instruction_places_stop_limit() -> None:
    proposal = {"orders": [{"ticker": "NVDA", "qty": 10, "stop_price": 95.0,
                            "limit_price": 94.05, "ref_id": "sl-NVDA-9500-x"}]}
    instr = build_placement_instruction(proposal)
    assert "place_equity_order" in instr
    assert "stop_limit" in instr
    assert "ref_id" in instr  # idempotency
    assert "cancel" in instr.lower()  # replace stale stops


def test_place_via_codex_noop_on_empty_proposal() -> None:
    out = place_via_codex({"orders": []}, confirm=True)
    assert out["mode"] == "noop"


def test_place_via_codex_review_mode_uses_review_instruction(tmp_path) -> None:
    """confirm=False -> the codex subprocess gets the REVIEW (read-only) instruction."""
    proposal = {"orders": [{"ticker": "NVDA", "qty": 10, "stop_price": 95.0,
                            "limit_price": 94.05, "ref_id": "sl-NVDA-9500-x"}]}
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["input"] = kwargs.get("input", "")
        out_idx = argv.index("-o") + 1
        # codex writes its JSON result to the -o file
        with open(argv[out_idx], "w", encoding="utf-8") as f:
            f.write('{"reviewed": [{"ticker": "NVDA", "ok": true}]}')
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        result = place_via_codex(
            proposal, confirm=False, result_path=str(tmp_path / "res.json"),
        )
    assert result["mode"] == "review"
    assert result["confirmed"] is False
    # Read-only instruction was sent, NOT the placement one.
    assert "Do NOT call place_equity_order" in captured["input"]
    assert result["parsed"] == {"reviewed": [{"ticker": "NVDA", "ok": True}]}


def test_place_via_codex_confirm_uses_placement_instruction(tmp_path) -> None:
    proposal = {"orders": [{"ticker": "NVDA", "qty": 10, "stop_price": 95.0,
                            "limit_price": 94.05, "ref_id": "sl-NVDA-9500-x"}]}
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["input"] = kwargs.get("input", "")
        out_idx = argv.index("-o") + 1
        with open(argv[out_idx], "w", encoding="utf-8") as f:
            f.write('{"placed": [{"ticker": "NVDA", "order_id": "abc", "status": "queued"}]}')
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        result = place_via_codex(
            proposal, confirm=True, result_path=str(tmp_path / "res.json"),
        )
    assert result["mode"] == "placed"
    assert result["confirmed"] is True
    assert "place_equity_order" in captured["input"]


def test_place_via_codex_raises_on_nonzero_exit(tmp_path) -> None:
    proposal = {"orders": [{"ticker": "NVDA", "qty": 10, "stop_price": 95.0,
                            "limit_price": 94.05, "ref_id": "x"}]}

    def fake_run(argv, **kwargs):
        out_idx = argv.index("-o") + 1
        with open(argv[out_idx], "w", encoding="utf-8") as f:
            f.write("")
        return MagicMock(returncode=1, stdout="", stderr="codex boom")

    with patch("subprocess.run", side_effect=fake_run):
        with pytest.raises(StopOrderBridgeError):
            place_via_codex(
                proposal, confirm=False, result_path=str(tmp_path / "res.json"),
            )
