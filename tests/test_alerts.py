"""tests.test_alerts -- F28 news-driven sell-trigger alerts."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from stock import alerts


def _seed_holding(conn: sqlite3.Connection, ticker: str = "SMCI") -> None:
    """Insert one active holding."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO holdings (ticker, qty, cost_basis, opened_at, notes,"
        " active, updated_at) VALUES (?, ?, ?, ?, '', 1, ?)",
        (ticker, 1.0, 0.0, now[:10], now),
    )
    conn.commit()


def _seed_news(
    conn: sqlite3.Connection, *, ticker: str, title: str, body: str = "",
    ts: str | None = None,
) -> int:
    """Insert one news row, return its id. Defaults ingested_at = now."""
    now = datetime.now(timezone.utc).isoformat()
    ts = ts or now
    cur = conn.execute(
        "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at)"
        " VALUES (?, 'rss', ?, ?, ?, ?, ?)",
        (ticker, f"http://x/{title[:30]}", title, body, ts, now),
    )
    conn.commit()
    return int(cur.lastrowid)


def test_no_holdings_no_alerts(mem_db: sqlite3.Connection) -> None:
    """No active holdings -> scan returns empty, no rows written."""
    _seed_news(mem_db, ticker="NVDA", title="NVDA earnings beat", body="")
    out = alerts.scan_all_holdings(mem_db)
    assert out == {}


def test_clean_news_does_not_alert(mem_db: sqlite3.Connection) -> None:
    """Positive headline doesn't fire any keyword."""
    _seed_holding(mem_db, "SMCI")
    _seed_news(mem_db, ticker="SMCI", title="SMCI raises FY guidance, beats Q3",
               body="Server vendor crushed estimates")
    out = alerts.scan_all_holdings(mem_db)
    assert out.get("SMCI", 0) == 0


def test_margin_compression_fires(mem_db: sqlite3.Connection) -> None:
    """Margin-compression keyword writes a kind='alert' row."""
    _seed_holding(mem_db, "SMCI")
    _seed_news(
        mem_db, ticker="SMCI",
        title="SMCI Q3 disappointment as margin compression deepens",
        body="Liquid-cooling unit margins fell 200bps QoQ",
    )
    out = alerts.scan_all_holdings(mem_db)
    assert out.get("SMCI", 0) == 1
    row = mem_db.execute(
        "SELECT topic, body FROM research_reports WHERE kind = 'alert'"
    ).fetchone()
    assert row is not None
    assert "SMCI" in row[0]
    assert "margin_compression" in row[0]
    assert "持仓警报" in row[1] or "Holding alert" in row[1]


def test_multi_category_fires_one_alert(mem_db: sqlite3.Connection) -> None:
    """One headline matching two categories produces ONE row with both flagged."""
    _seed_holding(mem_db, "SMCI")
    _seed_news(
        mem_db, ticker="SMCI",
        title="SMCI auditor resignation triggers SEC investigation amid margin warning",
        body="Material weakness disclosed",
    )
    out = alerts.scan_all_holdings(mem_db)
    assert out.get("SMCI", 0) == 1   # one headline
    rows = mem_db.execute(
        "SELECT topic FROM research_reports WHERE kind = 'alert'"
    ).fetchall()
    assert len(rows) == 1
    topic = rows[0][0]
    # All three categories should appear in the topic summary
    assert "compliance_audit" in topic
    assert "margin_compression" in topic or "guidance_cut" in topic


def test_dedup_on_rerun(mem_db: sqlite3.Connection) -> None:
    """Re-running the scan doesn't re-alert on already-scanned news."""
    _seed_holding(mem_db, "SMCI")
    _seed_news(
        mem_db, ticker="SMCI",
        title="SMCI margin compression update", body="",
    )
    first = alerts.scan_all_holdings(mem_db)
    second = alerts.scan_all_holdings(mem_db)
    # First run alerts; second sees no fresh ingest -> no new alert
    assert first.get("SMCI", 0) == 1
    assert second.get("SMCI", 0) == 0


def test_chinese_keywords_fire(mem_db: sqlite3.Connection) -> None:
    """Chinese sell-trigger phrases match against headline/body."""
    _seed_holding(mem_db, "SMCI")
    _seed_news(
        mem_db, ticker="SMCI",
        title="SMCI 毛利率下降幅度超预期", body="单季毛利率压缩",
    )
    out = alerts.scan_all_holdings(mem_db)
    assert out.get("SMCI", 0) == 1


def test_only_active_holdings_scanned(mem_db: sqlite3.Connection) -> None:
    """Inactive / non-holdings tickers don't get scanned."""
    _seed_holding(mem_db, "SMCI")
    # Make SMCI inactive after seeding to test the active filter
    mem_db.execute("UPDATE holdings SET active = 0 WHERE ticker = 'SMCI'")
    mem_db.commit()
    _seed_news(mem_db, ticker="SMCI",
               title="SMCI margin compression alert", body="")
    out = alerts.scan_all_holdings(mem_db)
    assert "SMCI" not in out
