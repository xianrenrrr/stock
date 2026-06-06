"""tests.test_macro -- daily US macro regime digest."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from stock import db, macro


@pytest.fixture
def conn() -> sqlite3.Connection:
    return db.get_conn(":memory:")


def test_format_macro_block_empty(conn: sqlite3.Connection) -> None:
    assert "macro regime unknown" in macro.format_macro_block(conn)


def test_format_macro_block_uses_latest(conn: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO research_reports (kind, topic, body, cost_usd, created_at)"
        " VALUES ('macro', 'US macro regime', ?, 0, ?)",
        ("NET REGIME: risk-off -- Fed cut odds rising into Oct.", now),
    )
    conn.commit()
    block = macro.format_macro_block(conn)
    assert "NET REGIME" in block
    assert "as of" in block


def test_format_macro_block_ignores_stale(conn: sqlite3.Connection) -> None:
    """A snapshot older than the freshness window is treated as unknown."""
    conn.execute(
        "INSERT INTO research_reports (kind, topic, body, cost_usd, created_at)"
        " VALUES ('macro', 'old', 'stale macro', 0, datetime('now','-30 days'))"
    )
    conn.commit()
    assert "macro regime unknown" in macro.format_macro_block(conn)


def test_generate_macro_digest_persists(conn: sqlite3.Connection) -> None:
    from stock.models import ChatResponse

    def fake_core_chat(*, messages, max_tokens, conn, caller, cached_system=None):
        return ChatResponse(
            content="Labor tight, Fed likely to cut Oct. NET REGIME: risk-on.",
            input_tokens=10, output_tokens=200, cost_usd=0.0, model="x",
        )

    with patch("stock.research._core_chat", side_effect=fake_core_chat), \
         patch("stock.macro.check_cost_ceiling", return_value=None):
        rid = macro.generate_macro_digest(conn)

    assert rid and rid > 0
    row = conn.execute(
        "SELECT kind, body FROM research_reports WHERE id = ?", (rid,)
    ).fetchone()
    assert row[0] == "macro"
    assert "Not financial advice" in row[1]  # disclaimer appended


def test_macro_kind_is_in_knowledge_base() -> None:
    """Macro notes flow into the unified knowledge base."""
    from stock.knowledge import KNOWLEDGE_KINDS
    assert "macro" in KNOWLEDGE_KINDS
    assert "daily" in KNOWLEDGE_KINDS
