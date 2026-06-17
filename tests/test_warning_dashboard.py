"""tests.test_warning_dashboard -- boss-facing risk warning rollup."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from stock import job_runs
from stock.warning_dashboard import (
    _broker_sync_staleness_items,
    build_warning_dashboard,
    publish_warning_dashboard,
)


def _add_broker_holding(
    conn: sqlite3.Connection, ticker: str, updated_at: str
) -> None:
    conn.execute(
        "INSERT INTO holdings"
        " (ticker, qty, cost_basis, opened_at, notes, active, updated_at)"
        " VALUES (?, 10, 100.0, '2026-06-01', ?, 1, ?)",
        (ticker, "[broker:robinhood account=1] synced from Robinhood MCP"
         " filled position snapshot", updated_at),
    )
    conn.commit()


# 2026-06-09 is a Tuesday; 2026-06-08 Monday; 2026-06-06/07 the weekend.
_TUESDAY = datetime(2026, 6, 9, 15, 0, tzinfo=timezone.utc)
_MONDAY = datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc)
_SATURDAY = datetime(2026, 6, 6, 15, 0, tzinfo=timezone.utc)


def test_broker_staleness_warns_on_old_weekday_sync(
    mem_db: sqlite3.Connection,
) -> None:
    _add_broker_holding(mem_db, "SMCI", (_TUESDAY - timedelta(hours=120)).isoformat())
    job_runs.record_run(
        mem_db, "broker_positions_pull", job_runs.ERROR,
        error="pull skipped: RH MCP returned no positions",
    )

    items = _broker_sync_staleness_items(mem_db, now=_TUESDAY)

    assert len(items) == 1
    assert items[0].severity == "high"
    assert "stale" in items[0].title
    assert "RH MCP returned no positions" in items[0].detail


def test_broker_staleness_quiet_when_fresh(mem_db: sqlite3.Connection) -> None:
    _add_broker_holding(mem_db, "SMCI", (_TUESDAY - timedelta(hours=2)).isoformat())
    assert _broker_sync_staleness_items(mem_db, now=_TUESDAY) == []


def test_broker_staleness_monday_allows_weekend_gap(
    mem_db: sqlite3.Connection,
) -> None:
    # Friday-evening sync is ~66h old on Monday afternoon: still fine.
    _add_broker_holding(mem_db, "SMCI", (_MONDAY - timedelta(hours=66)).isoformat())
    assert _broker_sync_staleness_items(mem_db, now=_MONDAY) == []
    # But a week-old sync on Monday is not.
    mem_db.execute("DELETE FROM holdings")
    _add_broker_holding(mem_db, "SMCI", (_MONDAY - timedelta(hours=168)).isoformat())
    assert len(_broker_sync_staleness_items(mem_db, now=_MONDAY)) == 1


def test_broker_staleness_quiet_on_weekend_and_without_broker_holdings(
    mem_db: sqlite3.Connection,
) -> None:
    _add_broker_holding(mem_db, "SMCI", (_SATURDAY - timedelta(hours=120)).isoformat())
    assert _broker_sync_staleness_items(mem_db, now=_SATURDAY) == []

    mem_db.execute("DELETE FROM holdings")
    mem_db.commit()
    assert _broker_sync_staleness_items(mem_db, now=_TUESDAY) == []


def test_warning_dashboard_surfaces_recent_alerts(mem_db: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO research_reports (kind, topic, body, cost_usd, created_at)"
        " VALUES ('alert', 'AMBA intraday drop: -20%', 'Active holding moved hard.', 0, ?)",
        (now,),
    )
    mem_db.commit()

    dashboard = build_warning_dashboard(mem_db)

    assert dashboard.items
    assert dashboard.items[0].severity == "high"
    assert "AMBA" in dashboard.items[0].title


def test_warning_dashboard_surfaces_ai_loop_crash_risk(
    mem_db: sqlite3.Connection,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for i in range(5):
        mem_db.execute(
            "INSERT INTO ai_loop_health"
            " (ticker, measured_at, revenue_decel, margin_compression, risk_flag)"
            " VALUES (?, ?, -0.20, -0.06, 'severe')",
            (f"AI{i}", now),
        )
    mem_db.commit()

    dashboard = build_warning_dashboard(mem_db)

    assert any(i.category == "cycle_crash" for i in dashboard.items)
    item = next(i for i in dashboard.items if i.category == "cycle_crash")
    assert item.severity == "high"


def test_warning_dashboard_surfaces_put_call_crash_risk(
    mem_db: sqlite3.Connection,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO option_ratio_snapshots"
        " (ticker, call_volume, put_volume, call_open_interest, put_open_interest,"
        " call_put_volume_ratio, put_call_volume_ratio, expiries_scanned,"
        " contracts_scanned, detected_at)"
        " VALUES ('NVDA', 1000, 5000, 0, 0, 0.2, 5.0, 3, 200, ?)",
        (now,),
    )
    mem_db.commit()

    dashboard = build_warning_dashboard(mem_db)

    assert any(i.category == "options_crash" and i.ticker == "NVDA" for i in dashboard.items)


def test_publish_warning_dashboard_dedupes_unchanged_content(
    mem_db: sqlite3.Connection,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO research_reports (kind, topic, body, cost_usd, created_at)"
        " VALUES ('alert', 'AMBA intraday drop: -20%', 'Active holding moved hard.', 0, ?)",
        (now,),
    )
    mem_db.commit()

    first = publish_warning_dashboard(mem_db)
    first_created = mem_db.execute(
        "SELECT created_at FROM research_reports WHERE kind = 'warning_dashboard'"
    ).fetchone()[0]
    second = publish_warning_dashboard(mem_db)

    # Unchanged content does not re-trigger the high-risk email...
    assert first.changed is True
    assert first.research_id is not None
    assert second.changed is False
    # ...but the stored row IS still refreshed in place (same id) so its
    # generated_at header never goes stale, and the table stays a single row.
    assert second.research_id == first.research_id
    second_created = mem_db.execute(
        "SELECT created_at FROM research_reports WHERE kind = 'warning_dashboard'"
    ).fetchone()[0]
    assert second_created >= first_created
    rows = mem_db.execute(
        "SELECT COUNT(*) FROM research_reports WHERE kind = 'warning_dashboard'"
    ).fetchone()
    assert rows[0] == 1


def test_build_warning_dashboard_dedupes_per_ticker(
    mem_db: sqlite3.Connection,
) -> None:
    """Multiple warnings for the same ticker collapse to one (+N more signals)."""
    now = datetime.now(timezone.utc).isoformat()
    for topic in ("GOOGL sell-trigger: fraud_legal", "GOOGL sell-trigger: macro_negative",
                  "GOOGL 异常期权"):
        mem_db.execute(
            "INSERT INTO research_reports (kind, topic, body, cost_usd, created_at)"
            " VALUES ('alert', ?, 'news flag', 0, ?)",
            (topic, now),
        )
    mem_db.commit()

    dash = build_warning_dashboard(mem_db)
    googl = [i for i in dash.items if i.ticker == "GOOGL"]
    assert len(googl) == 1  # collapsed to one
    assert "more signals" in googl[0].detail  # the rest are folded into a note


def test_publish_warning_dashboard_updates_in_place_on_change(
    mem_db: sqlite3.Connection,
) -> None:
    """Changed warning content updates the SAME row -- never accumulates dupes."""
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO research_reports (kind, topic, body, cost_usd, created_at)"
        " VALUES ('alert', 'AMBA drop -20%', 'moved', 0, ?)",
        (now,),
    )
    mem_db.commit()
    first = publish_warning_dashboard(mem_db)

    # New warning content arrives -> digest changes -> publish again.
    mem_db.execute(
        "INSERT INTO research_reports (kind, topic, body, cost_usd, created_at)"
        " VALUES ('alert', 'SMCI sell-trigger: fraud_legal', 'flag', 0, ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    mem_db.commit()
    second = publish_warning_dashboard(mem_db)

    assert second.changed is True
    # Same row reused, not a second warning_dashboard row.
    assert second.research_id == first.research_id
    count = mem_db.execute(
        "SELECT COUNT(*) FROM research_reports WHERE kind = 'warning_dashboard'"
    ).fetchone()[0]
    assert count == 1
