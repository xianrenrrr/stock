"""tests.test_broker_sync -- Robinhood snapshot bridge into holdings."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock import broker_sync
from stock.holdings import add_holding, list_holdings


def test_import_snapshot_ignores_zero_qty_and_upserts_filled(
    mem_db: sqlite3.Connection,
) -> None:
    snapshot = {
        "account_number": "643103732",
        "as_of": "2026-05-31T21:00:00+00:00",
        "positions": [
            {
                "symbol": "NVT",
                "quantity": "0.000000",
                "average_buy_price": "0.000000",
                "type": "empty",
            },
            {
                "symbol": "JBL",
                "quantity": "9.000000",
                "average_buy_price": "341.250000",
                "type": "long",
            },
        ],
    }

    result = broker_sync.import_snapshot(mem_db, snapshot, path="snapshot.json")

    assert result.upserted == 1
    assert result.skipped_empty == 1
    rows = list_holdings(mem_db)
    assert [r.ticker for r in rows] == ["JBL"]
    assert rows[0].qty == 9
    assert rows[0].cost_basis == 341.25
    assert "account=643103732" in rows[0].notes


def test_import_snapshot_deactivates_only_same_broker_account(
    mem_db: sqlite3.Connection,
) -> None:
    """With deactivate_missing=True and a non-empty snapshot, a sold position in
    the same account is deactivated; manual holdings are untouched."""
    add_holding(
        mem_db, ticker="OLD", qty=1, cost_basis=10,
        notes="[broker:robinhood account=643103732] synced",
    )
    add_holding(mem_db, ticker="MANUAL", qty=1, cost_basis=10, notes="manual")

    # Snapshot for the same account that returns ONE position (KEEP) -> OLD is
    # gone from the account, so it is deactivated; MANUAL is left alone.
    result = broker_sync.import_snapshot(
        mem_db,
        {"account_number": "643103732", "positions": [
            {"symbol": "KEEP", "quantity": 5, "average_buy_price": 10},
        ]},
        path="snapshot.json",
    )

    assert result.deactivated == 1
    active = {r.ticker for r in list_holdings(mem_db, active_only=True)}
    assert active == {"MANUAL", "KEEP"}


def test_import_snapshot_empty_never_deactivates(mem_db: sqlite3.Connection) -> None:
    """SAFETY: an empty snapshot must NOT wipe holdings (flaky MCP guard)."""
    add_holding(
        mem_db, ticker="SMCI", qty=10, cost_basis=46,
        notes="[broker:robinhood account=643103732] synced",
    )
    result = broker_sync.import_snapshot(
        mem_db, {"account_number": "643103732", "positions": []}, path="s.json",
    )
    assert result.deactivated == 0
    assert {r.ticker for r in list_holdings(mem_db, active_only=True)} == {"SMCI"}


def test_import_snapshot_upsert_only_never_deactivates(mem_db: sqlite3.Connection) -> None:
    """deactivate_missing=False never deactivates, even with positions."""
    add_holding(
        mem_db, ticker="SMCI", qty=10, cost_basis=46,
        notes="[broker:robinhood account=643103732] synced",
    )
    broker_sync.import_snapshot(
        mem_db,
        {"account_number": "643103732", "positions": [
            {"symbol": "GOOGL", "quantity": 1, "average_buy_price": 100},
        ]},
        deactivate_missing=False,
    )
    # SMCI absent from snapshot but NOT deactivated; GOOGL added.
    assert {r.ticker for r in list_holdings(mem_db, active_only=True)} == {"SMCI", "GOOGL"}


def test_import_snapshot_multi_account_format(mem_db: sqlite3.Connection) -> None:
    """The {accounts:[...]} format imports positions from every account."""
    result = broker_sync.import_snapshot(mem_db, {
        "as_of": "2026-06-04T00:00:00Z",
        "accounts": [
            {"account_number": "A1", "positions": [{"symbol": "GOOGL", "quantity": 60, "average_buy_price": 382}]},
            {"account_number": "A2", "positions": [{"symbol": "CAMT", "quantity": 23, "average_buy_price": 162}]},
        ],
    })
    assert result.upserted == 2
    active = {r.ticker for r in list_holdings(mem_db, active_only=True)}
    assert active == {"GOOGL", "CAMT"}


# --- positions PULL bridge (read-only) -------------------------------------


def test_positions_pull_instruction_is_read_only() -> None:
    instr = broker_sync.build_positions_pull_instruction()
    assert "get_equity_positions" in instr
    assert "READ-ONLY" in instr
    assert "Do NOT call" in instr and "place_equity_order" in instr


def test_pull_positions_via_codex_writes_snapshot(tmp_path) -> None:
    snap = tmp_path / "snap.json"
    payload = {
        "account_number": "643103732",
        "as_of": "2026-06-02T13:00:00+00:00",
        "positions": [{"symbol": "NVDA", "quantity": 10, "average_buy_price": 100.0}],
    }

    def fake_run(argv, **kwargs):
        out_idx = argv.index("-o") + 1
        Path(argv[out_idx]).write_text(json.dumps(payload), encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        result = broker_sync.pull_positions_via_codex(snapshot_path=str(snap))

    assert result["count"] == 1
    assert snap.exists()
    written = json.loads(snap.read_text(encoding="utf-8"))
    assert written["positions"][0]["symbol"] == "NVDA"


def test_pull_positions_via_codex_skips_on_empty(tmp_path) -> None:
    """SAFETY: an empty/MCP-unavailable result raises (no empty snapshot written)."""
    snap = tmp_path / "snap.json"
    payload = {"accounts": [], "errors": ["robinhood-trading MCP not available"]}

    def fake_run(argv, **kwargs):
        out_idx = argv.index("-o") + 1
        Path(argv[out_idx]).write_text(json.dumps(payload), encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        with pytest.raises(broker_sync.BrokerPullError):
            broker_sync.pull_positions_via_codex(snapshot_path=str(snap))
    # No snapshot file was written (so a later import can't wipe holdings).
    assert not snap.exists()


def test_pull_positions_via_codex_raises_on_bad_json(tmp_path) -> None:
    def fake_run(argv, **kwargs):
        out_idx = argv.index("-o") + 1
        Path(argv[out_idx]).write_text("not json at all", encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        with pytest.raises(broker_sync.BrokerPullError):
            broker_sync.pull_positions_via_codex(snapshot_path=str(tmp_path / "s.json"))


def test_pull_positions_via_codex_raises_on_nonzero_exit(tmp_path) -> None:
    def fake_run(argv, **kwargs):
        out_idx = argv.index("-o") + 1
        Path(argv[out_idx]).write_text("", encoding="utf-8")
        return MagicMock(returncode=1, stdout="", stderr="codex boom")

    with patch("subprocess.run", side_effect=fake_run):
        with pytest.raises(broker_sync.BrokerPullError):
            broker_sync.pull_positions_via_codex(snapshot_path=str(tmp_path / "s.json"))
