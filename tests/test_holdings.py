"""tests.test_holdings -- portfolio tracker tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from stock.holdings import (
    Holding,
    add_holding,
    format_holdings_block,
    list_holdings,
    remove_holding,
    set_note,
    sync_from_yaml,
)


def test_add_holding_inserts(mem_db: sqlite3.Connection) -> None:
    """add_holding writes a new active row."""
    h = add_holding(mem_db, ticker="nvda", qty=10, cost_basis=400.0, notes="core")
    assert h.ticker == "NVDA"
    assert h.active is True

    rows = list_holdings(mem_db)
    assert len(rows) == 1
    assert rows[0].ticker == "NVDA"
    assert rows[0].qty == 10


def test_add_holding_idempotent(mem_db: sqlite3.Connection) -> None:
    """add_holding twice with same ticker upserts qty/cost without duplicates."""
    add_holding(mem_db, ticker="NVDA", qty=10, cost_basis=400.0)
    add_holding(mem_db, ticker="NVDA", qty=15, cost_basis=420.0)

    rows = list_holdings(mem_db)
    assert len(rows) == 1
    assert rows[0].qty == 15
    assert rows[0].cost_basis == 420.0


def test_add_holding_validation(mem_db: sqlite3.Connection) -> None:
    """qty <= 0 or cost_basis < 0 raises ValueError."""
    with pytest.raises(ValueError):
        add_holding(mem_db, ticker="X", qty=0, cost_basis=10.0)
    with pytest.raises(ValueError):
        add_holding(mem_db, ticker="X", qty=10, cost_basis=-1.0)


def test_remove_holding_sets_inactive(mem_db: sqlite3.Connection) -> None:
    """remove_holding flips active to 0 but keeps the row."""
    add_holding(mem_db, ticker="NVDA", qty=10, cost_basis=400.0)
    assert remove_holding(mem_db, "NVDA") is True

    rows = list_holdings(mem_db, active_only=True)
    assert rows == []
    rows = list_holdings(mem_db, active_only=False)
    assert len(rows) == 1
    assert rows[0].active is False


def test_set_note_updates_text(mem_db: sqlite3.Connection) -> None:
    """set_note updates only the notes column."""
    add_holding(mem_db, ticker="NVDA", qty=10, cost_basis=400.0, notes="initial")
    assert set_note(mem_db, "NVDA", "updated note") is True

    rows = list_holdings(mem_db)
    assert rows[0].notes == "updated note"


def test_sync_from_yaml(mem_db: sqlite3.Connection, tmp_path: Path) -> None:
    """sync_from_yaml upserts YAML rows and deactivates missing ones."""
    add_holding(mem_db, ticker="OLD", qty=5, cost_basis=10.0)

    yaml_path = tmp_path / "holdings.yaml"
    yaml_path.write_text(
        "holdings:\n"
        "  - ticker: NVDA\n"
        "    qty: 100\n"
        "    cost_basis: 480.00\n"
        "    opened_at: '2025-12-01'\n"
        "    notes: 'core AI compute exposure'\n"
        "  - ticker: AVGO\n"
        "    qty: 50\n"
        "    cost_basis: 1200.0\n"
        "    opened_at: '2026-01-15'\n",
        encoding="utf-8",
    )

    upserted = sync_from_yaml(mem_db, path=str(yaml_path))
    assert upserted == 2

    active = list_holdings(mem_db, active_only=True)
    tickers = {h.ticker for h in active}
    assert tickers == {"NVDA", "AVGO"}

    # OLD ticker should be deactivated
    all_rows = list_holdings(mem_db, active_only=False)
    old_row = next(r for r in all_rows if r.ticker == "OLD")
    assert old_row.active is False


def test_sync_from_yaml_missing_file(mem_db: sqlite3.Connection) -> None:
    """Missing YAML returns 0 without raising."""
    n = sync_from_yaml(mem_db, path="/nonexistent/path.yaml")
    assert n == 0


def test_format_holdings_block_empty(mem_db: sqlite3.Connection) -> None:
    """Empty list yields a stable placeholder string."""
    out = format_holdings_block([], mem_db)
    assert "no active holdings" in out.lower()


def test_format_holdings_block_with_pnl(mem_db: sqlite3.Connection) -> None:
    """Block contains P&L when latest price is available."""
    add_holding(mem_db, ticker="NVDA", qty=10, cost_basis=400.0, notes="core")
    mem_db.execute(
        "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("NVDA", "2026-04-28", 480.0, 485.0, 478.0, 480.0, 1_000_000),
    )
    mem_db.commit()

    rows = list_holdings(mem_db)
    out = format_holdings_block(rows, mem_db)
    assert "NVDA" in out
    assert "+20.0%" in out
    # F27 enhancement: notes column dropped from the table to keep it scannable;
    # full notes still live in holdings.yaml + DB. Block now has table headers.
    assert "Ticker" in out


def test_format_holdings_block_without_price(mem_db: sqlite3.Connection) -> None:
    """No prices row yields P&L=N/A but still renders the line."""
    add_holding(mem_db, ticker="NVDA", qty=10, cost_basis=400.0)
    rows = list_holdings(mem_db)
    out = format_holdings_block(rows, mem_db)
    assert "NVDA" in out
    assert "N/A" in out
