"""tests.test_channel_notes -- Boss dashboard note filters."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock import channel
from stock.db import _ensure_schema


@pytest.fixture
def thread_safe_db() -> Generator[sqlite3.Connection, None, None]:
    import sqlite_vec

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    _ensure_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


def _make_test_app(conn: sqlite3.Connection) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(channel.ChannelHTTPError, channel.channel_exception_handler)
    app.include_router(channel.create_router())

    def _override_conn() -> Generator[sqlite3.Connection, None, None]:
        yield conn

    app.dependency_overrides[channel.get_db_conn] = _override_conn
    return app


def _insert_report(conn: sqlite3.Connection, kind: str, topic: str) -> None:
    conn.execute(
        "INSERT INTO research_reports (kind, topic, body, cost_usd, created_at)"
        " VALUES (?, ?, ?, 0, ?)",
        (kind, topic, f"{topic} body", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def test_notes_filter_by_kinds(thread_safe_db: sqlite3.Connection) -> None:
    token = channel.mint_token(thread_safe_db, "richard")
    _insert_report(thread_safe_db, "daily", "daily")
    _insert_report(thread_safe_db, "deep_dive", "SITM deep")
    _insert_report(thread_safe_db, "dd_checklist", "NVDA DD")
    _insert_report(thread_safe_db, "alert", "risk")

    client = TestClient(_make_test_app(thread_safe_db))
    resp = client.get(
        "/channel/api/notes?kinds=deep_dive,dd_checklist",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    notes = resp.json()["notes"]
    assert [n["kind"] for n in notes] == ["dd_checklist", "deep_dive"]
    assert {n["topic"] for n in notes} == {"SITM deep", "NVDA DD"}


def test_notes_reject_invalid_kind_filter(thread_safe_db: sqlite3.Connection) -> None:
    token = channel.mint_token(thread_safe_db, "richard")
    client = TestClient(_make_test_app(thread_safe_db))

    resp = client.get(
        "/channel/api/notes?kinds=deep_dive,deep-dive",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_kind_filter"
