"""tests.test_alerts -- F28 news-driven sell-trigger alerts."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from stock import alerts


@pytest.fixture(autouse=True)
def _stub_live_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    """scan_all_holdings fetches LIVE yfinance quotes for the intraday-move scan,
    which makes the news-alert tests flaky (they break on days a seeded ticker is
    actually down). Stub it to None so only the news-driven alerts under test fire.
    Tests that pass an explicit `provider=` are unaffected."""
    monkeypatch.setattr("stock.alerts._live_pct_change_yfinance", lambda ticker: None)


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


def _seed_holding_with_cost(
    conn: sqlite3.Connection, *, ticker: str = "SMCI", cost_basis: float = 100.0,
) -> None:
    """Seed an active holding with a real cost basis (not the placeholder $0)."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO holdings (ticker, qty, cost_basis, opened_at, notes,"
        " active, updated_at) VALUES (?, ?, ?, ?, '', 1, ?)",
        (ticker, 1.0, cost_basis, now[:10], now),
    )
    conn.commit()


def _seed_prices(
    conn: sqlite3.Connection, ticker: str, latest_close: float,
) -> None:
    """Insert 30 stable bars at $100 then a final bar at the requested close.

    Stable history makes the F24 ATR + swing-low predictable so the test only
    needs to think about the cost-anchored breach trigger.
    """
    base = datetime.now(timezone.utc) - timedelta(days=30)
    for i in range(29):
        ts = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT OR REPLACE INTO prices (ticker, ts, o, h, l, c, v)"
            " VALUES (?, ?, 100, 102, 98, 100, 1000000)",
            (ticker, ts),
        )
    last_ts = (base + timedelta(days=29)).strftime("%Y-%m-%d")
    conn.execute(
        "INSERT OR REPLACE INTO prices (ticker, ts, o, h, l, c, v)"
        " VALUES (?, ?, 100, 100, ?, ?, 1000000)",
        (ticker, last_ts, latest_close, latest_close),
    )
    conn.commit()


def test_stop_breach_above_cost_15pct_no_alert(mem_db: sqlite3.Connection) -> None:
    """Latest close above cost*0.85 (and above F24 stop) -> no breach."""
    _seed_holding_with_cost(mem_db, cost_basis=100.0)
    _seed_prices(mem_db, "SMCI", latest_close=99.0)  # only -1% from cost
    out = alerts.scan_holdings_for_stop_breach(mem_db)
    assert "SMCI" not in out


def test_stop_breach_below_cost_15pct_fires_alert(
    mem_db: sqlite3.Connection,
) -> None:
    """Latest close < cost*0.85 -> cost-anchored breach fires."""
    _seed_holding_with_cost(mem_db, cost_basis=100.0)
    _seed_prices(mem_db, "SMCI", latest_close=80.0)  # -20%, below cost*0.85=$85
    out = alerts.scan_holdings_for_stop_breach(mem_db)
    assert "SMCI" in out
    rows = mem_db.execute(
        "SELECT topic, body FROM research_reports WHERE kind = 'alert'"
        " AND topic LIKE 'SMCI stop-breach%'"
    ).fetchall()
    assert len(rows) == 1
    assert "-15% from cost" in rows[0][0]
    assert "Stop-loss breach" in rows[0][1]


def test_stop_breach_skipped_when_cost_basis_unset(
    mem_db: sqlite3.Connection,
) -> None:
    """Placeholder cost_basis=0 disables the cost-anchored trigger."""
    _seed_holding(mem_db, "SMCI")  # cost_basis defaults to 0.0
    _seed_prices(mem_db, "SMCI", latest_close=10.0)  # huge "loss" but no anchor
    out = alerts.scan_holdings_for_stop_breach(mem_db)
    # No cost anchor + recommended stop floats with the crash -> no breach
    # (operator must update cost_basis before mechanical breach can fire)
    assert "SMCI" not in out


def test_intraday_holding_drop_alerts_even_without_cost_basis(
    mem_db: sqlite3.Connection,
) -> None:
    """A live -20% holding move alerts even if cost_basis is still unset."""
    _seed_holding(mem_db, "AMBA")

    out = alerts.scan_holdings_for_intraday_moves(
        mem_db,
        provider=lambda ticker: (73.19, 91.84, -0.203),
        as_of=datetime(2026, 5, 29, 17, 0, tzinfo=timezone.utc),
    )

    assert "AMBA" in out
    row = mem_db.execute(
        "SELECT topic, layer_focus, body FROM research_reports WHERE kind = 'alert'"
    ).fetchone()
    assert row is not None
    assert "AMBA intraday DROP" in row[0]
    assert row[1] == "intraday_holding_move"
    assert "Intraday holding DROP alert" in row[2]


def test_intraday_holding_move_dedupes_same_severity_bucket(
    mem_db: sqlite3.Connection,
) -> None:
    """Same-day rerun at the same severity bucket does not spam alerts."""
    _seed_holding(mem_db, "AMBA")
    as_of = datetime(2026, 5, 29, 17, 0, tzinfo=timezone.utc)

    first = alerts.scan_holdings_for_intraday_moves(
        mem_db, provider=lambda ticker: (73.19, 91.84, -0.203), as_of=as_of,
    )
    second = alerts.scan_holdings_for_intraday_moves(
        mem_db, provider=lambda ticker: (73.00, 91.84, -0.205), as_of=as_of,
    )

    assert "AMBA" in first
    assert "AMBA" not in second
    rows = mem_db.execute(
        "SELECT COUNT(*) FROM research_reports WHERE kind = 'alert'"
    ).fetchone()
    assert rows[0] == 1


def test_stop_breach_dedupes_at_same_close(mem_db: sqlite3.Connection) -> None:
    """Re-running scan at the same breached close doesn't re-alert."""
    _seed_holding_with_cost(mem_db, cost_basis=100.0)
    _seed_prices(mem_db, "SMCI", latest_close=80.0)
    first = alerts.scan_holdings_for_stop_breach(mem_db)
    second = alerts.scan_holdings_for_stop_breach(mem_db)
    assert "SMCI" in first
    assert "SMCI" not in second


def test_stop_breach_re_alerts_on_lower_close(mem_db: sqlite3.Connection) -> None:
    """A FRESH lower close after a breach re-alerts."""
    _seed_holding_with_cost(mem_db, cost_basis=100.0)
    _seed_prices(mem_db, "SMCI", latest_close=80.0)
    first = alerts.scan_holdings_for_stop_breach(mem_db)
    # Drop the close further
    last_ts = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    mem_db.execute(
        "UPDATE prices SET c = 70, l = 70 WHERE ticker = 'SMCI' AND ts = ?",
        (last_ts,),
    )
    mem_db.commit()
    second = alerts.scan_holdings_for_stop_breach(mem_db)
    assert "SMCI" in first and "SMCI" in second


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
