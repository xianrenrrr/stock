"""tests.test_events -- F26 tracked-events CRUD + verification + calibration."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock.events import (
    add_event,
    delete_event,
    edit_event,
    event_calibration_summary,
    list_events,
    recent_events_block,
    verify_due_events,
    verify_event,
)


def _add(mem_db: sqlite3.Connection, **kwargs):
    """Default event factory."""
    base = {
        "ticker": "NVDA",
        "event_type": "earnings",
        "title": "NVDA fiscal Q3 earnings",
        "predicted_outcome": "Revenue beat by 5% and FY guidance raise",
        "window_start": "2026-04-01T00:00:00+00:00",
        "window_end": "2026-05-01T00:00:00+00:00",
        "confidence": 0.65,
    }
    base.update(kwargs)
    return add_event(mem_db, **base)


def test_add_and_list(mem_db: sqlite3.Connection) -> None:
    """Newly-added event lands in list_events with status='pending'."""
    ev = _add(mem_db)
    rows = list_events(mem_db)
    assert any(r.id == ev.id and r.status == "pending" for r in rows)


def test_event_type_coerced(mem_db: sqlite3.Connection) -> None:
    """Bogus event_type snaps to 'other'."""
    ev = _add(mem_db, event_type="banana")
    assert ev.event_type == "other"


def test_edit_event_updates_fields(mem_db: sqlite3.Connection) -> None:
    """edit_event writes through and returns True."""
    ev = _add(mem_db)
    ok = edit_event(
        mem_db, ev.id, title="UPDATED TITLE", confidence=0.9, status="hit",
        actual_outcome="Q3 revenue $35B beat",
    )
    assert ok is True
    rows = list_events(mem_db)
    found = next(r for r in rows if r.id == ev.id)
    assert found.title == "UPDATED TITLE"
    assert found.confidence == pytest.approx(0.9)
    assert found.status == "hit"


def test_edit_invalid_field_no_op(mem_db: sqlite3.Connection) -> None:
    """edit_event with no allowed fields returns False, no DB change."""
    ev = _add(mem_db)
    ok = edit_event(mem_db, ev.id, secret_field="hax")
    assert ok is False


def test_delete_event(mem_db: sqlite3.Connection) -> None:
    """delete_event hard-removes the row."""
    ev = _add(mem_db)
    ok = delete_event(mem_db, ev.id)
    assert ok is True
    assert all(r.id != ev.id for r in list_events(mem_db))


def test_list_filters_by_status_and_ticker(mem_db: sqlite3.Connection) -> None:
    """status + ticker filters compose."""
    a = _add(mem_db, ticker="NVDA")
    b = _add(mem_db, ticker="AMD")
    edit_event(mem_db, b.id, status="hit", actual_outcome="x")
    only_pending = list_events(mem_db, status="pending")
    only_amd = list_events(mem_db, ticker="AMD")
    assert all(r.status == "pending" for r in only_pending)
    assert all(r.ticker == "AMD" for r in only_amd)


def test_verify_event_with_news_marks_hit(mem_db: sqlite3.Connection) -> None:
    """LLM returns verdict='hit' -> status flips, evidence persisted."""
    ev = _add(mem_db)
    # Insert post-window news so the news block isn't empty
    mem_db.execute(
        "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at)"
        " VALUES (?, 'rss', ?, ?, ?, ?, ?)",
        ("NVDA", "http://x/1", "NVDA Q3 revenue $35B, raises FY guidance",
         "Beat estimates by 6%, FY26 guidance raised to $200B",
         "2026-04-25T20:00:00+00:00",
         datetime.now(timezone.utc).isoformat()),
    )
    mem_db.commit()

    fake_response = MagicMock(content=json.dumps({
        "verdict": "hit",
        "actual_outcome": "Q3 revenue $35B beat by 6%, FY guidance raised",
        "evidence_text": "NVDA Q3 revenue $35B, raises FY guidance",
        "evidence_source": "news_headline",
        "evidence_url": "http://x/1",
    }), cost_usd=0.0008)
    with (
        patch("stock.events.check_cost_ceiling"),
        patch("stock.events.get_client") as mock_factory,
    ):
        mock_client = MagicMock()
        mock_client.chat.return_value = fake_response
        mock_factory.return_value = mock_client
        verify_event(mem_db, ev.id)

    row = mem_db.execute(
        "SELECT status, actual_outcome, evidence_source FROM tracked_events WHERE id = ?",
        (ev.id,),
    ).fetchone()
    assert row[0] == "hit"
    assert "35B" in row[1]
    assert row[2] == "news_headline"


def test_verify_skips_already_resolved(mem_db: sqlite3.Connection) -> None:
    """Already-resolved events are returned unchanged, no LLM call."""
    ev = _add(mem_db)
    edit_event(mem_db, ev.id, status="hit", actual_outcome="...")
    with patch("stock.events.get_client") as mock_factory:
        verify_event(mem_db, ev.id)
    mock_factory.assert_not_called()


def test_verify_due_events_walks_only_open_window(
    mem_db: sqlite3.Connection,
) -> None:
    """Only events whose window has STARTED get verified."""
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).isoformat()
    tomorrow = (now + timedelta(days=1)).isoformat()
    next_year = (now + timedelta(days=365)).isoformat()
    a = _add(mem_db, window_start=yesterday, window_end=tomorrow)  # in window
    b = _add(mem_db, window_start=tomorrow, window_end=next_year)  # not yet

    fake_response = MagicMock(content=json.dumps({
        "verdict": "pending", "actual_outcome": "",
        "evidence_text": "", "evidence_source": "none", "evidence_url": "",
    }), cost_usd=0.0)
    with (
        patch("stock.events.check_cost_ceiling"),
        patch("stock.events.get_client") as mock_factory,
    ):
        mock_factory.return_value.chat.return_value = fake_response
        verify_due_events(mem_db)
        # Only event A should have been verified
        # mock_factory.return_value.chat is called via the same client mock for both,
        # so we check that get_client was invoked exactly once (per event in window)
        assert mock_factory.call_count == 1


def test_calibration_summary_aggregates_resolved(mem_db: sqlite3.Connection) -> None:
    """Resolved events flow into hit-rate stats."""
    a = _add(mem_db, confidence=0.7)
    b = _add(mem_db, confidence=0.3)
    c = _add(mem_db, confidence=0.5)
    edit_event(mem_db, a.id, status="hit", actual_outcome="x")
    edit_event(mem_db, b.id, status="miss", actual_outcome="x")
    # Stamp verdict_at so the calibration window picks them up
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute("UPDATE tracked_events SET verdict_at = ?", (now,))
    mem_db.commit()
    s = event_calibration_summary(mem_db, lookback_days=90)
    assert s["total_resolved"] == 2
    assert s["hits"] == 1
    assert s["misses"] == 1
    assert s["hit_rate"] == pytest.approx(0.5)


def test_recent_events_block_renders_table(mem_db: sqlite3.Connection) -> None:
    """recent_events_block has the column headers and a row per event."""
    _add(mem_db, ticker="NVDA")
    _add(mem_db, ticker="AMD")
    out = recent_events_block(mem_db)
    assert "Ticker" in out
    assert "NVDA" in out
    assert "AMD" in out
