"""tests.test_context_graph -- memoized context nodes (plan H phase H1)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from stock import context_graph


def _add_macro(conn: sqlite3.Connection, body: str) -> None:
    conn.execute(
        "INSERT INTO research_reports (kind, topic, body, cost_usd, created_at)"
        " VALUES ('macro', 'US macro regime', ?, 0, ?)",
        (body, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def test_get_block_caches_until_fingerprint_changes(
    mem_db: sqlite3.Connection, monkeypatch,
) -> None:
    calls = {"render": 0}
    real_render = context_graph.NODES["macro"].render

    def counting_render(conn: sqlite3.Connection, scope: str) -> str:
        calls["render"] += 1
        return real_render(conn, scope)

    monkeypatch.setitem(
        context_graph.NODES, "macro",
        context_graph.NodeSpec(
            "macro", context_graph.NODES["macro"].fingerprint, counting_render,
        ),
    )

    _add_macro(mem_db, "regime A")
    first, hash1 = context_graph.get_block(mem_db, "macro")
    second, hash2 = context_graph.get_block(mem_db, "macro")

    assert calls["render"] == 1          # second call was a cache hit
    assert first == second and hash1 == hash2
    assert "regime A" in first

    _add_macro(mem_db, "regime B")       # new row -> new fingerprint
    third, hash3 = context_graph.get_block(mem_db, "macro")

    assert calls["render"] == 2
    assert "regime B" in third and hash3 != hash1


def test_get_block_persists_row(mem_db: sqlite3.Connection) -> None:
    _add_macro(mem_db, "regime A")
    content, content_hash = context_graph.get_block(mem_db, "macro")

    row = mem_db.execute(
        "SELECT content, content_hash, scope FROM context_nodes WHERE node='macro'",
    ).fetchone()
    assert row == (content, content_hash, context_graph.SHARED_SCOPE)


def test_sector_breadth_renders_with_peer_data(
    mem_db: sqlite3.Connection,
) -> None:
    from stock.predict import AI_INFRA_TICKERS

    for ticker in sorted(AI_INFRA_TICKERS)[:6]:
        for day, close in (("2026-06-09", 100.0), ("2026-06-10", 102.0)):
            mem_db.execute(
                "INSERT INTO prices (ticker, ts, o, h, l, c, v)"
                " VALUES (?, ?, ?, ?, ?, ?, 1)",
                (ticker, day, close, close, close, close),
            )
    mem_db.commit()

    content, _hash = context_graph.get_block(mem_db, "sector_breadth")

    assert "peer breadth" in content
    assert "100% positive" in content


def test_sector_breadth_degrades_without_data(mem_db: sqlite3.Connection) -> None:
    content, _hash = context_graph.get_block(mem_db, "sector_breadth")
    assert "insufficient" in content


def test_get_block_render_failure_degrades_uncached(
    mem_db: sqlite3.Connection, monkeypatch,
) -> None:
    """A broken cache path still renders the block directly."""
    def broken_fingerprint(_conn: sqlite3.Connection, _scope: str) -> str:
        raise RuntimeError("probe failed")

    monkeypatch.setitem(
        context_graph.NODES, "market_internals",
        context_graph.NodeSpec(
            "market_internals", broken_fingerprint,
            context_graph.NODES["market_internals"].render,
        ),
    )

    content, content_hash = context_graph.get_block(mem_db, "market_internals")

    assert "no index data" in content
    assert len(content_hash) == 12
