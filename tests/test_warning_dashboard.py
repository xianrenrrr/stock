"""tests.test_warning_dashboard -- boss-facing risk warning rollup."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from stock.warning_dashboard import build_warning_dashboard, publish_warning_dashboard


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
    second = publish_warning_dashboard(mem_db)

    assert first.changed is True
    assert first.research_id is not None
    assert second.changed is False
    assert second.research_id is None
    rows = mem_db.execute(
        "SELECT COUNT(*) FROM research_reports WHERE kind = 'warning_dashboard'"
    ).fetchone()
    assert rows[0] == 1
