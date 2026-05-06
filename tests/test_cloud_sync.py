"""tests.test_cloud_sync -- /sync/notes + /sync/tokens upsert semantics.

Regression test: prior to today's fix, the post_sync_notes / post_sync_tokens
counters only incremented on INSERT, so a routine re-push of existing rows
returned upserted=0 and the operator's log read like the sync had failed.
The endpoint had been UPDATEing the rows correctly, but the misleading 0
masked the real behavior. Counter now includes both INSERT + UPDATE.
"""
from __future__ import annotations

import sqlite3

import pytest

from stock import db
from stock.cloud_sync import (
    NoteRow,
    SyncNotesRequest,
    SyncTokensRequest,
    TokenRow,
    post_sync_notes,
    post_sync_tokens,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    return db.get_conn(":memory:")


def _note(rid: int, body: str = "hello") -> NoteRow:
    return NoteRow(
        research_id=rid, kind="daily", topic="t", layer_focus=None,
        body=body, cost_usd=0.0, created_at="2026-05-05T00:00:00+00:00",
    )


def _token(t: str = "abc") -> TokenRow:
    return TokenRow(
        token=t, recipient="boss", created_at="2026-05-05T00:00:00+00:00",
        last_seen_at="2026-05-05T00:00:00+00:00", revoked=0,
    )


def test_sync_notes_counts_inserts(conn: sqlite3.Connection) -> None:
    """First push -> upserted == len(notes)."""
    body = SyncNotesRequest(notes=[_note(1), _note(2)])
    resp = post_sync_notes(body=body, _auth=None, conn=conn)
    assert resp.upserted == 2


def test_sync_notes_counts_updates_too(conn: sqlite3.Connection) -> None:
    """Re-push of existing rows should still report upserted > 0 -- the row
    HAS been refreshed; reporting 0 lied to the operator."""
    body = SyncNotesRequest(notes=[_note(1, body="v1"), _note(2, body="v1")])
    post_sync_notes(body=body, _auth=None, conn=conn)
    # Re-push with updated bodies
    body2 = SyncNotesRequest(notes=[_note(1, body="v2"), _note(2, body="v2")])
    resp = post_sync_notes(body=body2, _auth=None, conn=conn)
    assert resp.upserted == 2  # both rows touched
    # And the bodies were actually updated
    rows = conn.execute("SELECT id, body FROM research_reports ORDER BY id").fetchall()
    assert rows == [(1, "v2"), (2, "v2")]


def test_sync_notes_mixed_insert_and_update(conn: sqlite3.Connection) -> None:
    """Mixed batch counts both branches."""
    post_sync_notes(body=SyncNotesRequest(notes=[_note(1)]), _auth=None, conn=conn)
    body = SyncNotesRequest(notes=[_note(1, body="updated"), _note(2)])
    resp = post_sync_notes(body=body, _auth=None, conn=conn)
    assert resp.upserted == 2  # 1 update + 1 insert


def test_sync_tokens_counts_inserts_and_updates(conn: sqlite3.Connection) -> None:
    """Tokens endpoint had the same bug -- regression test for that too."""
    resp1 = post_sync_tokens(
        body=SyncTokensRequest(tokens=[_token("a"), _token("b")]),
        _auth=None, conn=conn,
    )
    assert resp1.upserted == 2

    resp2 = post_sync_tokens(
        body=SyncTokensRequest(tokens=[_token("a"), _token("c")]),
        _auth=None, conn=conn,
    )
    assert resp2.upserted == 2  # 1 update (a) + 1 insert (c)
