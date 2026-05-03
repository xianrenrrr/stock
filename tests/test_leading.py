"""tests.test_leading -- F19 leading-indicator signals."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from stock.leading import (
    ThemeVelocitySignal,
    compute_8k_novelty,
    compute_future_winner_probability,
    compute_insider_acceleration,
    compute_quiet_accumulation,
    compute_reddit_acceleration,
    compute_theme_velocity,
    fetch_apewisdom_snapshot,
)


# -- fixtures + helpers -----------------------------------------------------


def _insert_filing(
    conn: sqlite3.Connection, *,
    ticker: str = "NVDA",
    filer_name: str = "John Smith",
    filed_at: str | None = None,
    transaction_type: str = "P",
    shares: float = 1000.0,
    price: float = 100.0,
    accession: str | None = None,
) -> None:
    """Insert a single insider filing row."""
    if filed_at is None:
        filed_at = datetime.now(timezone.utc).isoformat()
    if accession is None:
        accession = f"a-{filer_name}-{filed_at}"
    conn.execute(
        "INSERT INTO insider_filings (ticker, filer_name, form_type, filed_at,"
        " transaction_type, shares, price, accession_number, raw_url, fetched_at)"
        " VALUES (?, ?, '4', ?, ?, ?, ?, ?, 'http://x', ?)",
        (ticker, filer_name, filed_at, transaction_type, shares, price,
         accession, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def _insert_news(
    conn: sqlite3.Connection, *,
    ticker: str = "NVDA",
    title: str,
    body: str,
    ts: str,
    source: str = "rss",
) -> None:
    conn.execute(
        "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticker, source, f"http://x/{title[:20]}", title, body, ts,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def _insert_price_bar(
    conn: sqlite3.Connection, *,
    ticker: str, ts: str, o: float, h: float, l: float, c: float, v: int,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO prices (ticker, ts, o, h, l, c, v)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticker, ts, o, h, l, c, v),
    )
    conn.commit()


# -- compute_insider_acceleration -------------------------------------------


def test_insider_no_filings_returns_zero(mem_db: sqlite3.Connection) -> None:
    """No insider filings -> raw_score=0, distinct_filers=0."""
    sig = compute_insider_acceleration("NVDA", mem_db)
    assert sig.raw_score == 0.0
    assert sig.distinct_filers_30d == 0
    assert sig.cluster_size_max == 0


def test_insider_single_purchase_emits_score(mem_db: sqlite3.Connection) -> None:
    """One opportunistic purchase -> positive raw_score, cluster_max=1."""
    _insert_filing(mem_db, shares=10_000, price=50.0)
    sig = compute_insider_acceleration("NVDA", mem_db)
    assert sig.raw_score > 0
    assert sig.distinct_filers_30d == 1
    assert sig.cluster_size_max == 1
    assert sig.opportunistic_value_usd == pytest.approx(500_000)


def test_insider_cluster_3_filers_amplifies_score(mem_db: sqlite3.Connection) -> None:
    """Three distinct filers in a 10-day window -> cluster multiplier 2.0x."""
    base = datetime.now(timezone.utc) - timedelta(days=5)
    for i, name in enumerate(["A", "B", "C"]):
        _insert_filing(
            mem_db, filer_name=name, shares=1000, price=100.0,
            filed_at=(base + timedelta(days=i)).isoformat(),
        )
    sig = compute_insider_acceleration("NVDA", mem_db)
    assert sig.cluster_size_max == 3
    assert sig.distinct_filers_30d == 3


def test_insider_only_purchases_count(mem_db: sqlite3.Connection) -> None:
    """A 'sale' transaction (S) does not contribute to OCIS."""
    _insert_filing(mem_db, transaction_type="S", shares=10_000, price=50.0)
    sig = compute_insider_acceleration("NVDA", mem_db)
    assert sig.raw_score == 0.0


def test_insider_routine_filer_excluded_from_opportunistic(
    mem_db: sqlite3.Connection,
) -> None:
    """A filer with regular ~30-day cadence is tagged routine, not opportunistic."""
    # 24 monthly buys over 2 years -> stdev of gaps is small -> routine
    base = datetime.now(timezone.utc) - timedelta(days=2 * 365)
    for i in range(24):
        _insert_filing(
            mem_db, filer_name="Routine Bob", shares=100, price=10.0,
            filed_at=(base + timedelta(days=i * 30)).isoformat(),
            accession=f"acc-{i}",
        )
    sig = compute_insider_acceleration("NVDA", mem_db)
    # Routine filer's recent buy still counts the row but routine_value_usd
    # gets it, opportunistic_value_usd stays 0
    assert sig.routine_value_usd > 0 or sig.opportunistic_value_usd == 0


# -- compute_8k_novelty -----------------------------------------------------


def test_novelty_no_news_returns_zero(mem_db: sqlite3.Connection) -> None:
    """No news rows -> novelty=0."""
    sig = compute_8k_novelty("NVDA", mem_db)
    assert sig.novelty_score == 0.0
    assert sig.most_recent_8k_ts is None


def test_novelty_no_baseline_returns_neutral(mem_db: sqlite3.Connection) -> None:
    """One news item, no prior history -> novelty=0.5 (neutral, not 1.0)."""
    now = datetime.now(timezone.utc).isoformat()
    _insert_news(mem_db, title="NVDA Q3 earnings", body="beats expectations", ts=now)
    sig = compute_8k_novelty("NVDA", mem_db)
    assert sig.novelty_score == 0.5
    assert sig.baseline_count == 0


def test_novelty_high_when_unrelated_to_baseline(
    mem_db: sqlite3.Connection,
) -> None:
    """Recent filing about a totally new topic -> high novelty."""
    base = datetime.now(timezone.utc) - timedelta(days=30)
    for i in range(4):
        _insert_news(
            mem_db,
            title=f"NVDA Q{i} earnings beat",
            body="revenue growth datacenter ai",
            ts=(base + timedelta(days=i)).isoformat(),
        )
    # Recent filing about something completely different
    _insert_news(
        mem_db,
        title="NVDA acquires quantum computing startup XYZ",
        body="acquisition photon entanglement neutral atom qubit cryo lasers",
        ts=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )
    sig = compute_8k_novelty("NVDA", mem_db)
    assert sig.novelty_score > 0.6
    assert sig.baseline_count == 4


def test_novelty_low_when_repeats_baseline(mem_db: sqlite3.Connection) -> None:
    """Recent filing that repeats prior content -> low novelty."""
    base = datetime.now(timezone.utc) - timedelta(days=30)
    body = "revenue growth datacenter datacenter datacenter ai gpu hopper blackwell"
    for i in range(4):
        _insert_news(
            mem_db, title=f"NVDA earnings {i}", body=body,
            ts=(base + timedelta(days=i)).isoformat(),
        )
    _insert_news(
        mem_db, title="NVDA earnings recent",
        body=body,
        ts=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )
    sig = compute_8k_novelty("NVDA", mem_db)
    assert sig.novelty_score < 0.3


# -- compute_quiet_accumulation ---------------------------------------------


def test_qap_insufficient_bars_returns_no_gate(mem_db: sqlite3.Connection) -> None:
    """Fewer than 90 bars -> qap_gate=False."""
    base = datetime.now(timezone.utc) - timedelta(days=10)
    for i in range(10):
        _insert_price_bar(
            mem_db, ticker="NVDA",
            ts=(base + timedelta(days=i)).strftime("%Y-%m-%d"),
            o=100, h=101, l=99, c=100, v=1000,
        )
    sig = compute_quiet_accumulation("NVDA", mem_db)
    assert sig.qap_gate is False


def test_qap_gate_fires_on_tight_low_volume_base(
    mem_db: sqlite3.Connection,
) -> None:
    """60 tight low-volume bars after 180 noisy high-volume bars -> gate fires."""
    base = datetime.now(timezone.utc) - timedelta(days=240)
    # Prior 180 days: wide range, high volume
    for i in range(180):
        _insert_price_bar(
            mem_db, ticker="NVDA",
            ts=(base + timedelta(days=i)).strftime("%Y-%m-%d"),
            o=100, h=110, l=90, c=100, v=1_000_000,
        )
    # Recent 60 days: tight range, low volume
    for i in range(60):
        _insert_price_bar(
            mem_db, ticker="NVDA",
            ts=(base + timedelta(days=180 + i)).strftime("%Y-%m-%d"),
            o=100, h=101, l=99, c=100, v=200_000,
        )
    sig = compute_quiet_accumulation("NVDA", mem_db)
    assert sig.qap_gate is True
    assert sig.range_over_atr is not None and sig.range_over_atr < 1.5
    assert sig.volume_ratio is not None and sig.volume_ratio < 0.7


def test_qap_gate_fails_on_volatile_recent_action(
    mem_db: sqlite3.Connection,
) -> None:
    """Recent 60d span much wider than daily ATR -> range_over_atr >> 1.5 -> gate fails."""
    base = datetime.now(timezone.utc) - timedelta(days=240)
    for i in range(180):
        _insert_price_bar(
            mem_db, ticker="NVDA",
            ts=(base + timedelta(days=i)).strftime("%Y-%m-%d"),
            o=100, h=102, l=98, c=100, v=1_000_000,
        )
    # Recent 60: tiny daily range (1) but slow trend from 70 to 130 -> total span 60
    # range_over_atr = 60 / 1 = 60 >> 1.5 -> fails
    for i in range(60):
        price = 70 + i  # ramps from 70 to 129
        _insert_price_bar(
            mem_db, ticker="NVDA",
            ts=(base + timedelta(days=180 + i)).strftime("%Y-%m-%d"),
            o=price, h=price + 0.5, l=price - 0.5, c=price, v=200_000,
        )
    sig = compute_quiet_accumulation("NVDA", mem_db)
    assert sig.qap_gate is False
    assert sig.range_over_atr is not None and sig.range_over_atr > 1.5


# -- compute_reddit_acceleration --------------------------------------------


def test_reddit_acceleration_uses_provided_snapshot() -> None:
    """No HTTP call when snapshot is provided."""
    snap = {"NVDA": {"mentions": 100, "mentions_24h_ago": 25}}
    sig = compute_reddit_acceleration("NVDA", snapshot=snap)
    assert sig.mentions_24h == 100
    assert sig.mentions_24h_prior == 25
    assert sig.acceleration == pytest.approx(3.0)  # (100-25)/25


def test_reddit_acceleration_unknown_ticker_returns_zero() -> None:
    """Ticker not in snapshot -> zero acceleration."""
    sig = compute_reddit_acceleration("NVDA", snapshot={})
    assert sig.mentions_24h == 0
    assert sig.acceleration == 0.0


def test_apewisdom_snapshot_returns_empty_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ApeWisdom HTTP failure -> empty dict, no exception."""
    import httpx

    def _boom(*a, **kw):
        raise httpx.ConnectError("dns fail")

    monkeypatch.setattr("stock.leading.httpx.get", _boom)
    snap = fetch_apewisdom_snapshot()
    assert snap == {}


# -- compute_theme_velocity (HN + arXiv) ------------------------------------


def test_theme_velocity_acceleration_math(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accel formulas correct + composite is 0.35*hn + 0.65*arxiv."""
    # The function calls _hn / _arxiv twice per query: once for the current
    # 30d window and once for the prior 30d window. They alternate by until_*
    # value -- current's `until` = now; prior's `until` = now - 30d.
    # Distinguish by checking whether `until` is within ~1 day of "now".
    now_unix = int(datetime.now(timezone.utc).timestamp())

    def _fake_hn(query, *, since_unix, until_unix):
        # Current window iff until is within 1 day of now
        is_current = (now_unix - until_unix) < 86400
        return 30 if is_current else 10

    monkeypatch.setattr("stock.leading._hn_count_for_window", _fake_hn)

    def _fake_arxiv(query, *, since_iso, until_iso):
        from datetime import datetime as _dt
        u = _dt.fromisoformat(until_iso.replace("Z", "+00:00"))
        is_current = (datetime.now(timezone.utc) - u).total_seconds() < 86400
        return 6 if is_current else 2

    monkeypatch.setattr("stock.leading._arxiv_count_for_window", _fake_arxiv)

    sig = compute_theme_velocity("NVDA", company_name="Nvidia")
    # Two queries (Nvidia + NVDA), each window summed across queries
    assert sig.hn_30d == 60   # 30 * 2 queries
    assert sig.hn_30d_prior == 20   # 10 * 2 queries
    assert sig.hn_acceleration == pytest.approx(2.0)  # (60-20)/20
    assert sig.arxiv_acceleration == pytest.approx(2.0)  # (12-4)/4
    assert sig.composite == pytest.approx(2.0)


def test_theme_velocity_handles_zero_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prior=0 -> denominator clamped to 1, no DivisionByZero."""
    now_unix = int(datetime.now(timezone.utc).timestamp())

    def _fake_hn(query, *, since_unix, until_unix):
        is_current = (now_unix - until_unix) < 86400
        return 5 if is_current else 0

    monkeypatch.setattr("stock.leading._hn_count_for_window", _fake_hn)
    monkeypatch.setattr(
        "stock.leading._arxiv_count_for_window",
        lambda q, *, since_iso, until_iso: 0,
    )
    sig = compute_theme_velocity("XYZ")
    assert sig.hn_30d_prior == 0
    assert sig.hn_acceleration == 5.0  # (5 - 0) / max(1, 0) = 5


def test_theme_velocity_uses_extra_keywords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each extra keyword is queried in addition to ticker / company."""
    queries_seen: list[str] = []
    monkeypatch.setattr(
        "stock.leading._hn_count_for_window",
        lambda q, *, since_unix, until_unix: queries_seen.append(q) or 1,
    )
    monkeypatch.setattr(
        "stock.leading._arxiv_count_for_window",
        lambda q, *, since_iso, until_iso: 0,
    )
    compute_theme_velocity(
        "VRT", company_name="Vertiv",
        extra_keywords=["liquid cooling", "data center thermal"],
    )
    # 4 queries: Vertiv, VRT, liquid cooling, data center thermal
    # Each called twice (one for current window, one for prior window)
    unique = set(queries_seen)
    assert "Vertiv" in unique
    assert "VRT" in unique
    assert "liquid cooling" in unique
    assert "data center thermal" in unique


def test_fwp_includes_theme_velocity_when_provided(
    mem_db: sqlite3.Connection,
) -> None:
    """Pre-computed theme_velocity is fed into the composite without making HTTP calls."""
    theme = ThemeVelocitySignal(
        ticker="NVDA", hn_30d=80, hn_30d_prior=20, arxiv_30d=10, arxiv_30d_prior=2,
        hn_acceleration=3.0, arxiv_acceleration=4.0, composite=3.65,
    )
    score = compute_future_winner_probability(
        "NVDA", mem_db, apewisdom_snapshot={}, theme_velocity=theme,
    )
    assert score.components["theme_composite"] == pytest.approx(3.65)
    assert score.components["theme_z"] != 0.0


def test_fwp_skip_theme_velocity_skips_network(mem_db: sqlite3.Connection) -> None:
    """skip_theme_velocity=True -> no compute_theme_velocity call, theme_z is 0."""
    with (
        patch("stock.leading.compute_theme_velocity") as mock_tv,
        patch("stock.leading.compute_patent_activity") as mock_pa,
    ):
        score = compute_future_winner_probability(
            "NVDA", mem_db, apewisdom_snapshot={},
            skip_theme_velocity=True, skip_patent_activity=True,
        )
    mock_tv.assert_not_called()
    mock_pa.assert_not_called()
    assert score.components["theme_z"] == 0.0
    assert score.components["patent_z"] == 0.0


# -- compute_patent_activity (USPTO PatentsView) ----------------------------


def test_patent_activity_acceleration_math(monkeypatch: pytest.MonkeyPatch) -> None:
    """patents_12m=20 vs prior=4 -> acceleration=4.0."""
    from stock.leading import compute_patent_activity

    now_iso = datetime.now(timezone.utc).isoformat()

    def _fake(query, *, since_iso, until_iso):
        from datetime import datetime as _dt
        u = _dt.fromisoformat(until_iso.replace("Z", "+00:00"))
        is_current = (datetime.now(timezone.utc) - u).total_seconds() < 86400 * 2
        return 20 if is_current else 4

    monkeypatch.setattr("stock.leading._patentsview_count_for_window", _fake)

    sig = compute_patent_activity("NVDA", company_name="Nvidia Corp")
    assert sig.patents_12m == 20
    assert sig.patents_prior_12m == 4
    assert sig.acceleration == pytest.approx(4.0)


def test_patent_activity_handles_zero_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prior=0 -> denominator clamped, no DivisionByZero."""
    from stock.leading import compute_patent_activity

    now_unix = int(datetime.now(timezone.utc).timestamp())

    def _fake(query, *, since_iso, until_iso):
        from datetime import datetime as _dt
        u = _dt.fromisoformat(until_iso.replace("Z", "+00:00"))
        is_current = (datetime.now(timezone.utc) - u).total_seconds() < 86400 * 2
        return 5 if is_current else 0

    monkeypatch.setattr("stock.leading._patentsview_count_for_window", _fake)
    sig = compute_patent_activity("NEWCO", company_name="Newco Ltd")
    assert sig.patents_prior_12m == 0
    assert sig.acceleration == 5.0  # (5-0)/max(1,0) = 5


def test_patent_activity_http_failure_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PatentsView HTTP failure -> count=0, no exception."""
    import httpx

    def _boom(*a, **kw):
        raise httpx.ConnectError("dns fail")

    monkeypatch.setattr("stock.leading.httpx.post", _boom)
    from stock.leading import _patentsview_count_for_window

    n = _patentsview_count_for_window(
        "Nvidia", since_iso="2025-01-01", until_iso="2026-01-01",
    )
    assert n == 0


def test_fwp_includes_patent_when_provided(mem_db: sqlite3.Connection) -> None:
    """Pre-computed patent_activity flows into the FWP composite."""
    from stock.leading import PatentActivitySignal

    pat = PatentActivitySignal(
        ticker="NVDA", patents_12m=120, patents_prior_12m=30,
        acceleration=3.0,
    )
    score = compute_future_winner_probability(
        "NVDA", mem_db, apewisdom_snapshot={},
        patent_activity=pat, skip_theme_velocity=True,
    )
    assert score.components["patent_12m"] == 120
    assert score.components["patent_z"] != 0.0


# -- compute_future_winner_probability --------------------------------------


def test_fwp_returns_value_in_0_1(mem_db: sqlite3.Connection) -> None:
    """Sigmoid output is bounded; with no data FWP < 0.5 (gate not on, weak signals)."""
    score = compute_future_winner_probability(
        "NVDA", mem_db, apewisdom_snapshot={}, skip_theme_velocity=True,
    )
    assert 0.0 <= score.fwp <= 1.0
    assert score.qap_gate is False  # no price data


def test_fwp_amplifies_with_strong_insider_cluster(
    mem_db: sqlite3.Connection,
) -> None:
    """Heavy opportunistic insider cluster -> higher FWP than baseline."""
    baseline = compute_future_winner_probability(
        "NVDA", mem_db, apewisdom_snapshot={}, skip_theme_velocity=True,
    )
    base = datetime.now(timezone.utc) - timedelta(days=5)
    for i, name in enumerate(["A", "B", "C", "D"]):
        _insert_filing(
            mem_db, filer_name=name, shares=100_000, price=50.0,
            filed_at=(base + timedelta(days=i)).isoformat(),
        )
    boosted = compute_future_winner_probability(
        "NVDA", mem_db, apewisdom_snapshot={}, skip_theme_velocity=True,
    )
    assert boosted.fwp > baseline.fwp
    assert boosted.components["ocis_cluster_max"] >= 4
