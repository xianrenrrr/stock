"""tests.test_broker_sync -- Robinhood snapshot bridge into holdings."""
from __future__ import annotations

import sqlite3

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
