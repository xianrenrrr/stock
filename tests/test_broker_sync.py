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
    add_holding(
        mem_db,
        ticker="OLD",
        qty=1,
        cost_basis=10,
        notes="[broker:robinhood account=643103732] synced",
    )
    add_holding(mem_db, ticker="MANUAL", qty=1, cost_basis=10, notes="manual")

    result = broker_sync.import_snapshot(
        mem_db,
        {"account_number": "643103732", "positions": []},
        path="snapshot.json",
    )

    assert result.deactivated == 1
    active = {r.ticker for r in list_holdings(mem_db, active_only=True)}
    assert active == {"MANUAL"}


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
    assert result["account_number"] == "643103732"
    assert snap.exists()
    written = json.loads(snap.read_text(encoding="utf-8"))
    assert written["positions"][0]["symbol"] == "NVDA"


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
