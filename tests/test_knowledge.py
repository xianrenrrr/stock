"""tests.test_knowledge -- per-ticker knowledge base fed into predictions."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from stock import db
from stock.knowledge import (
    build_ticker_knowledge_block,
    format_knowledge_block,
    gather_ticker_knowledge,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    return db.get_conn(":memory:")


def _add(conn: sqlite3.Connection, kind: str, topic: str, body: str, *, days_ago: int = 1) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    conn.execute(
        "INSERT INTO research_reports (kind, topic, layer_focus, body, cost_usd, created_at)"
        " VALUES (?, ?, NULL, ?, 0, ?)",
        (kind, topic, body, ts),
    )
    conn.commit()


def test_gather_matches_ticker_word_boundary(conn: sqlite3.Connection) -> None:
    _add(conn, "deep_dive", "NVDA outlook", "NVDA HBM demand is strong.")
    _add(conn, "tech_dive", "iON note", "iON is not a ticker here.")  # must NOT match ON
    _add(conn, "reply", "About SMCI", "SMCI liquid cooling thesis.")

    nvda = gather_ticker_knowledge(conn, "NVDA")
    assert [i.topic for i in nvda] == ["NVDA outlook"]

    on = gather_ticker_knowledge(conn, "ON")  # ambiguous 2-letter ticker
    assert on == []  # 'iON' must not be promoted into an ON mention


def test_gather_filters_by_kind_and_recency(conn: sqlite3.Connection) -> None:
    _add(conn, "deep_dive", "NVDA deep", "NVDA recent.", days_ago=2)
    _add(conn, "tech_dive", "NVDA tech", "NVDA recent tech.", days_ago=2)
    _add(conn, "deep_dive", "NVDA stale", "NVDA long ago.", days_ago=400)

    # kind filter
    only_tech = gather_ticker_knowledge(conn, "NVDA", kinds=["tech_dive"])
    assert [i.kind for i in only_tech] == ["tech_dive"]

    # recency window excludes the 400-day-old row
    recent = gather_ticker_knowledge(conn, "NVDA", days=60)
    assert {i.topic for i in recent} == {"NVDA deep", "NVDA tech"}


def test_gather_respects_max_items_newest_first(conn: sqlite3.Connection) -> None:
    for i in range(5):
        _add(conn, "deep_dive", f"NVDA note {i}", "NVDA body", days_ago=i + 1)
    items = gather_ticker_knowledge(conn, "NVDA", max_items=2)
    assert len(items) == 2
    # newest first (smallest days_ago)
    assert items[0].topic == "NVDA note 0"


def test_format_block_tags_each_item(conn: sqlite3.Connection) -> None:
    _add(conn, "deep_dive", "NVDA outlook", "NVDA HBM demand strong.")
    block = build_ticker_knowledge_block(conn, "NVDA")
    assert "knowledge base" in block.lower()
    assert "Deep-dive" in block  # human tag, not raw kind
    assert "NVDA outlook" in block


def test_format_block_empty() -> None:
    assert format_knowledge_block([]).startswith("(no prior deep research")


# --- semantic retrieval (embeddings) ---------------------------------------

def _fake_embed(text: str) -> list[float]:
    """Deterministic 384-dim one-hot embedding keyed on a theme word in the text."""
    v = [0.0] * 384
    lower = text.lower()
    if "powertheme" in lower:
        v[0] = 1.0
    elif "biotheme" in lower:
        v[1] = 1.0
    else:
        v[2] = 1.0
    return v


def test_backfill_indexes_and_is_incremental(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stock import knowledge
    monkeypatch.setattr("stock.knowledge.embed", _fake_embed)
    _add(conn, "deep_dive", "A", "powertheme content")
    assert knowledge.backfill_knowledge(conn) == 1
    # Second run finds nothing new to index.
    assert knowledge.backfill_knowledge(conn) == 0


def test_retrieve_semantic_finds_thematic_match(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stock import knowledge
    monkeypatch.setattr("stock.knowledge.embed", _fake_embed)
    _add(conn, "tech_dive", "Power grid dive", "powertheme AI-DC nuclear grid")
    _add(conn, "deep_dive", "Bio dive", "biotheme drug discovery")
    knowledge.backfill_knowledge(conn)

    power_query = [0.0] * 384
    power_query[0] = 1.0
    items = knowledge.retrieve_semantic(conn, power_query, k=2)
    assert items[0].topic == "Power grid dive"
    assert items[0].via == "semantic"


def test_gather_combines_direct_and_thematic(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stock import knowledge
    monkeypatch.setattr("stock.knowledge.embed", _fake_embed)
    # Names NVDA (direct) AND is power-themed.
    _add(conn, "deep_dive", "NVDA direct", "NVDA powertheme rack power")
    # Power-themed but never names NVDA (thematic only).
    _add(conn, "tech_dive", "Power grid", "powertheme grid nuclear")
    knowledge.backfill_knowledge(conn)

    power_query = [0.0] * 384
    power_query[0] = 1.0
    items = knowledge.gather_knowledge(conn, "NVDA", query_embedding=power_query)
    by_topic = {i.topic: i.via for i in items}
    assert by_topic.get("NVDA direct") == "direct"
    assert by_topic.get("Power grid") == "semantic"
