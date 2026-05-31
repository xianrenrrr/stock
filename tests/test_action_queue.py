"""tests.test_action_queue -- F11 action-items extraction + queue runner tests."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from stock import action_queue
from stock.action_queue import (
    enqueue_actions,
    extract_action_items,
    format_previous_followups,
    normalize_topic,
    pending_items,
    recent_completed,
    run_pending,
)
from stock.models import CostCeilingError
from stock.research import ResearchReport


_NOTE_ZH = """\
1. 今日主线 / Theme of the day
   AI capex digest.

6. 行动清单 / Action items
- TER WFE bookings vs Q3 guidance
- 300308.SZ HBM capacity ramp
- 600584.SS OSAT margin trajectory

Not financial advice.
"""

_NOTE_EN = """\
1. Theme: hyperscaler capex digest.

6. Action items
* Pull NVDA Q3 transcript HBM mix
* Compare AVGO vs MRVL DSP bookings

Not financial advice.
"""

_NOTE_F11 = """\
1. Theme.
6. AI 自动跟进 / Auto-queued follow-ups
- HBM3E supplier shortage map
- Lithium niobate modulator runway

Not financial advice.
"""

_NOTE_AGENT_FOLLOWUPS = """\
1. Theme.
8. AI助手自动跟进 / Agent auto-queued follow-ups
- HBM cycle peak-window study through 2027
- Optical 800G/1.6T expansion lead-time audit

Not financial advice.
"""

# ---- extract_action_items -------------------------------------------------


def test_extract_action_items_chinese_heading() -> None:
    """Chinese-flavored 行动清单 heading is detected and bullets parsed."""
    items = extract_action_items(_NOTE_ZH)
    assert len(items) == 3
    assert "TER" in items[0]


def test_extract_action_items_english_heading() -> None:
    """English 'Action items' heading is detected and bullets parsed."""
    items = extract_action_items(_NOTE_EN)
    assert len(items) == 2
    assert items[0].startswith("Pull NVDA")


def test_extract_action_items_f11_heading() -> None:
    """The renamed 'AI 自动跟进 / Auto-queued follow-ups' heading is also matched."""
    items = extract_action_items(_NOTE_F11)
    assert len(items) == 2
    assert "HBM3E" in items[0]


def test_extract_action_items_agent_heading() -> None:
    """The AI助手 / Agent heading is matched after the boss rename request."""
    items = extract_action_items(_NOTE_AGENT_FOLLOWUPS)
    assert len(items) == 2
    assert "peak-window" in items[0]


def test_extract_action_items_no_heading() -> None:
    """Body without a recognized heading returns empty list."""
    items = extract_action_items("just a paragraph with no heading.\n")
    assert items == []


def test_extract_action_items_empty_body() -> None:
    """Empty body returns empty list."""
    assert extract_action_items("") == []


def test_normalize_topic_truncates() -> None:
    """Topics over the configured cap are truncated."""
    long = "x" * 200
    out = normalize_topic(long)
    assert len(out) <= action_queue.TOPIC_MAX_CHARS


def test_normalize_topic_strips_quotes_and_bullets() -> None:
    """Leading bullet markers and quotes are removed."""
    assert normalize_topic("- 'TER bookings'") == "TER bookings"


# ---- enqueue_actions ------------------------------------------------------


def test_enqueue_actions_inserts_rows(mem_db: sqlite3.Connection) -> None:
    """Each non-empty raw item becomes a pending row."""
    items = enqueue_actions(
        mem_db, source_research_id=None,
        raw_items=["topic A", "topic B", ""],
    )
    assert len(items) == 2
    pending = pending_items(mem_db)
    assert {p.topic for p in pending} == {"topic A", "topic B"}


def test_enqueue_actions_dedups_within_window(mem_db: sqlite3.Connection) -> None:
    """Re-enqueueing the same topic in the dedup window inserts no new row."""
    enqueue_actions(mem_db, source_research_id=None, raw_items=["dup"])
    again = enqueue_actions(mem_db, source_research_id=None, raw_items=["dup"])
    assert again == []
    rows = mem_db.execute(
        "SELECT COUNT(*) FROM action_queue WHERE topic = ?", ("dup",)
    ).fetchone()
    assert rows[0] == 1


# ---- run_pending ----------------------------------------------------------


def _stub_research(research_id: int = 999) -> ResearchReport:
    """Return a fake ResearchReport for the deep-dive stub."""
    now = datetime.now(timezone.utc).isoformat()
    return ResearchReport(
        research_id=research_id, kind="deep_dive", topic="t",
        layer_focus=None, body="body text excerpt",
        cost_usd=0.001, created_at=now,
    )


def test_run_pending_marks_done(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful generate_deep_dive flips status -> done with deep_dive_id."""
    enqueue_actions(mem_db, source_research_id=None, raw_items=["topic_x"])

    # Persist a fake research_reports row so the deep_dive_id reference is real
    mem_db.execute(
        "INSERT INTO research_reports (kind, topic, body, layer_focus, cost_usd, created_at)"
        " VALUES ('deep_dive', 't', 'fake body', NULL, 0.0, ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    fake_id = mem_db.execute("SELECT last_insert_rowid()").fetchone()[0]
    mem_db.commit()

    fake = _stub_research(research_id=int(fake_id))
    monkeypatch.setattr(
        "stock.research.generate_deep_dive",
        lambda conn, **kw: fake,
    )

    completed = run_pending(mem_db, max_items=4)

    assert len(completed) == 1
    assert completed[0].status == "done"
    assert completed[0].deep_dive_id == int(fake_id)
    assert pending_items(mem_db) == []


def test_run_pending_cost_ceiling_requeues(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CostCeilingError re-marks the row as pending and re-raises."""
    enqueue_actions(mem_db, source_research_id=None, raw_items=["over_budget"])

    def _raise(conn: sqlite3.Connection, **kw: object) -> None:
        raise CostCeilingError("over")

    monkeypatch.setattr("stock.research.generate_deep_dive", _raise)

    with pytest.raises(CostCeilingError):
        run_pending(mem_db, max_items=4)

    # Row should be back to pending so the next runner picks it up
    pend = pending_items(mem_db)
    assert len(pend) == 1
    assert pend[0].topic == "over_budget"


def test_run_pending_failure_marks_failed(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-cost runtime error marks the row failed but does not raise."""
    enqueue_actions(mem_db, source_research_id=None, raw_items=["broken"])

    def _raise(conn: sqlite3.Connection, **kw: object) -> None:
        raise RuntimeError("network glitch")

    monkeypatch.setattr("stock.research.generate_deep_dive", _raise)

    completed = run_pending(mem_db, max_items=4)

    assert len(completed) == 1
    assert completed[0].status == "failed"
    assert completed[0].error is not None
    assert "network glitch" in completed[0].error


# ---- format_previous_followups -------------------------------------------


def test_format_previous_followups_empty(mem_db: sqlite3.Connection) -> None:
    """Empty list yields a stable placeholder."""
    out = format_previous_followups([], mem_db)
    assert "no completed" in out.lower()


def test_format_previous_followups_reads_body(mem_db: sqlite3.Connection) -> None:
    """Each completed item shows topic + truncated deep-dive body excerpt."""
    mem_db.execute(
        "INSERT INTO research_reports (kind, topic, body, layer_focus, cost_usd, created_at)"
        " VALUES ('deep_dive', 't', 'A long body that should be truncated.', NULL, 0.0, ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    rid = int(mem_db.execute("SELECT last_insert_rowid()").fetchone()[0])
    mem_db.commit()

    items = enqueue_actions(mem_db, source_research_id=None, raw_items=["alpha"])
    items[0].deep_dive_id = rid
    items[0].status = "done"

    out = format_previous_followups(items, mem_db)
    assert "alpha" in out
    assert "long body" in out


# ---- recent_completed ----------------------------------------------------


def test_recent_completed_filters_by_window(mem_db: sqlite3.Connection) -> None:
    """Only rows with completed_at within the lookback are returned."""
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO action_queue (raw_text, topic, status, queued_at, completed_at)"
        " VALUES ('r', 'fresh', 'done', ?, ?)",
        (now, now),
    )
    mem_db.execute(
        "INSERT INTO action_queue (raw_text, topic, status, queued_at, completed_at)"
        " VALUES ('r', 'old', 'done', '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z')",
    )
    mem_db.commit()

    items = recent_completed(mem_db, hours=18)
    topics = {item.topic for item in items}
    assert "fresh" in topics
    assert "old" not in topics

