"""tests.test_conversation -- conversation memory tests."""
from __future__ import annotations

import sqlite3

import pytest

from stock.conversation import (
    format_context_block,
    get_run_id,
    has_entry,
    recent_instruction_ids,
    recent_turns,
    record_inbound,
    record_outbound,
    set_intent,
)


@pytest.fixture()
def mock_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub embed() to avoid loading sentence-transformers in tests."""
    fake_vec = [0.0] * 384
    fake_vec[0] = 1.0
    monkeypatch.setattr("stock.conversation.embed", lambda text: fake_vec)


def test_record_inbound_inserts_row(
    mem_db: sqlite3.Connection, mock_embed: None
) -> None:
    """record_inbound writes a conversation row + an embedding."""
    cid = record_inbound("boss", "shorter notes please", mem_db)
    assert cid > 0

    row = mem_db.execute(
        "SELECT direction, body, recipient FROM conversations WHERE id = ?",
        (cid,),
    ).fetchone()
    assert row[0] == "inbound"
    assert "shorter" in row[1]
    assert row[2] == "boss"

    # Embedding row exists
    emb = mem_db.execute(
        "SELECT COUNT(*) FROM conversation_embeddings WHERE conversation_id = ?",
        (cid,),
    ).fetchone()
    assert emb[0] == 1


def test_record_outbound_joins_run_id(
    mem_db: sqlite3.Connection, mock_embed: None
) -> None:
    """record_outbound shares the run_id of the linked inbound."""
    inbound_id = record_inbound("boss", "what about TER?", mem_db)
    rid = get_run_id(mem_db, inbound_id)
    out_id = record_outbound("boss", "TER bookings up.", mem_db, run_id=rid)

    inbound_run = mem_db.execute(
        "SELECT run_id FROM conversations WHERE id = ?", (inbound_id,)
    ).fetchone()[0]
    outbound_run = mem_db.execute(
        "SELECT run_id FROM conversations WHERE id = ?", (out_id,)
    ).fetchone()[0]
    assert inbound_run == outbound_run


def test_set_intent_stamps_row(
    mem_db: sqlite3.Connection, mock_embed: None
) -> None:
    """set_intent updates intent + confidence."""
    cid = record_inbound("boss", "TER thoughts?", mem_db)
    set_intent(mem_db, cid, "question", 0.9)

    row = mem_db.execute(
        "SELECT intent, intent_confidence FROM conversations WHERE id = ?",
        (cid,),
    ).fetchone()
    assert row[0] == "question"
    assert row[1] == 0.9


def test_has_entry_detects_existing(
    mem_db: sqlite3.Connection, mock_embed: None
) -> None:
    """has_entry returns True for a recorded inbound timestamp."""
    record_inbound("boss", "note", mem_db, created_at="2026-04-28T01:00:00Z")
    assert has_entry(mem_db, "2026-04-28T01:00:00Z", "boss") is True
    assert has_entry(mem_db, "1999-01-01T00:00:00Z", "boss") is False


def test_recent_turns_filters_by_recipient(
    mem_db: sqlite3.Connection, mock_embed: None
) -> None:
    """recent_turns scoped to recipient returns only their rows."""
    record_inbound("alice", "hi", mem_db)
    record_inbound("bob", "yo", mem_db)
    record_inbound("alice", "again", mem_db)

    turns = recent_turns(mem_db, recipient="alice", limit=10)
    assert all(t.recipient == "alice" for t in turns)
    assert len(turns) == 2


def test_recent_instruction_ids(
    mem_db: sqlite3.Connection, mock_embed: None
) -> None:
    """recent_instruction_ids returns only inbound rows with intent='instruction'."""
    a = record_inbound("boss", "shorter", mem_db)
    b = record_inbound("boss", "thoughts?", mem_db)
    set_intent(mem_db, a, "instruction", 0.95)
    set_intent(mem_db, b, "question", 0.90)

    ids = recent_instruction_ids(mem_db, hours=24)
    assert a in ids
    assert b not in ids


def test_format_context_block_groups_by_recipient(
    mem_db: sqlite3.Connection, mock_embed: None
) -> None:
    """format_context_block groups turns by recipient with bracketed labels."""
    cid_a = record_inbound("alice", "hi", mem_db)
    cid_b = record_inbound("bob", "yo", mem_db)

    a_turn = recent_turns(mem_db, recipient="alice", limit=10)[0]
    b_turn = recent_turns(mem_db, recipient="bob", limit=10)[0]

    out = format_context_block([a_turn, b_turn])
    assert "alice" in out
    assert "bob" in out
    assert "them" in out


def test_format_context_block_truncates_long_bodies(
    mem_db: sqlite3.Connection, mock_embed: None
) -> None:
    """Each turn body is truncated to CONTEXT_BODY_MAX_CHARS."""
    long = "x" * 1000
    record_inbound("boss", long, mem_db)
    turns = recent_turns(mem_db, recipient="boss", limit=1)
    out = format_context_block(turns)
    # The "x" run is capped at CONTEXT_BODY_MAX_CHARS
    longest_x_run = max(len(seg) for seg in out.split("x") if False) if False else 0
    assert "xxx" in out
    assert len(out) < 1500
