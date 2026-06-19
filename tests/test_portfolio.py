"""Tests for the Amber-learning build: portfolio, backtest, universe, chart_pattern."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from stock.backtest_portfolio import backtest_topn, format_backtest
from stock.chart_pattern import chart_pattern_score
from stock.portfolio import (
    Pick,
    rank_picks,
    score_basket,
)
from stock.universe import MEGA_CAPS, is_megacap, ranking_universe


@pytest.fixture()
def conn() -> sqlite3.Connection:
    from stock.db import get_conn

    c = get_conn(":memory:")
    yield c
    c.close()


def _add_price(c: sqlite3.Connection, ticker: str, ts: str, o: float, close: float) -> None:
    c.execute(
        "INSERT OR REPLACE INTO prices (ticker, ts, o, h, l, c, v)"
        " VALUES (?, ?, ?, ?, ?, ?, 1000)",
        (ticker, ts, o, max(o, close), min(o, close), close),
    )


# ---- #1 ranking ---------------------------------------------------------

def test_rank_picks_takes_top_n_up_leaning():
    rows = [
        {"ticker": "AAA", "prob_up": 0.70, "expected_return_bps": 50},
        {"ticker": "BBB", "prob_up": 0.62, "expected_return_bps": 10},
        {"ticker": "CCC", "prob_up": 0.45, "expected_return_bps": 99},  # down-leaning
        {"ticker": "DDD", "prob_up": 0.55, "expected_return_bps": 5},
    ]
    picks = rank_picks(rows, top_n=2)
    assert [p.ticker for p in picks] == ["AAA", "BBB"]
    assert all(p.prob_up > 0.5 for p in picks)
    assert abs(sum(p.weight for p in picks) - 1.0) < 1e-9


def test_rank_picks_excludes_cn_when_us_only():
    rows = [
        {"ticker": "600519.SS", "prob_up": 0.90},
        {"ticker": "AAA", "prob_up": 0.60},
    ]
    picks = rank_picks(rows, top_n=5, us_only=True)
    assert [p.ticker for p in picks] == ["AAA"]


def test_rank_picks_dedupes_repeated_ticker():
    # Same name predicted in three batches the same day -> held once, best row.
    rows = [
        {"ticker": "AMAT", "prob_up": 0.60},
        {"ticker": "AMAT", "prob_up": 0.72},
        {"ticker": "AMAT", "prob_up": 0.65},
        {"ticker": "CEG", "prob_up": 0.58},
    ]
    picks = rank_picks(rows, top_n=5)
    tickers = [p.ticker for p in picks]
    assert tickers.count("AMAT") == 1
    amat = next(p for p in picks if p.ticker == "AMAT")
    assert amat.prob_up == 0.72  # kept the strongest row


def test_rank_picks_excludes_taiwan_and_other_foreign():
    rows = [
        {"ticker": "6488.TWO", "prob_up": 0.95},  # Taiwan OTC
        {"ticker": "7203.T", "prob_up": 0.90},    # Tokyo
        {"ticker": "AAA", "prob_up": 0.55},
    ]
    picks = rank_picks(rows, top_n=5, us_only=True)
    assert [p.ticker for p in picks] == ["AAA"]


def test_rank_picks_empty_when_all_down():
    rows = [{"ticker": "AAA", "prob_up": 0.40}, {"ticker": "BBB", "prob_up": 0.30}]
    assert rank_picks(rows) == []


# ---- #2 / #4 scoring ----------------------------------------------------

def test_score_basket_excess_and_cost(conn):
    # entry day open, exit day close for two longs + benchmark
    _add_price(conn, "AAA", "2026-06-01", o=100.0, close=110.0)  # +10%
    _add_price(conn, "BBB", "2026-06-01", o=100.0, close=100.0)  # 0%
    _add_price(conn, "QQQ", "2026-06-01", o=100.0, close=102.0)  # +2%
    _add_price(conn, "AAA", "2026-06-08", o=110.0, close=110.0)
    _add_price(conn, "BBB", "2026-06-08", o=100.0, close=100.0)
    _add_price(conn, "QQQ", "2026-06-08", o=102.0, close=102.0)

    picks = [Pick(ticker="AAA", weight=0.5, prob_up=0.7, score=0.7),
             Pick(ticker="BBB", weight=0.5, prob_up=0.6, score=0.6)]
    r = score_basket(conn, picks, entry_iso="2026-06-01", exit_iso="2026-06-08")
    assert r is not None
    assert r.port_return == pytest.approx(0.05, abs=1e-6)   # (10% + 0%)/2
    assert r.bench_return == pytest.approx(0.02, abs=1e-6)
    assert r.excess_return == pytest.approx(0.03, abs=1e-6)
    assert r.turnover == 1.0                                # first basket fully bought
    assert r.net_excess < r.excess_return                  # cost drag applied


def test_score_basket_turnover_vs_prior(conn):
    _add_price(conn, "AAA", "2026-06-01", o=100.0, close=105.0)
    _add_price(conn, "QQQ", "2026-06-01", o=100.0, close=100.0)
    _add_price(conn, "AAA", "2026-06-08", o=105.0, close=105.0)
    _add_price(conn, "QQQ", "2026-06-08", o=100.0, close=100.0)
    picks = [Pick(ticker="AAA", weight=1.0, prob_up=0.7, score=0.7)]
    r = score_basket(conn, picks, entry_iso="2026-06-01", exit_iso="2026-06-08",
                     prior_picks=["AAA"])
    assert r is not None
    assert r.turnover == 0.0  # held the same name -> no turnover


def test_score_basket_none_when_unpriced(conn):
    picks = [Pick(ticker="ZZZ", weight=1.0, prob_up=0.7, score=0.7)]
    assert score_basket(conn, picks, entry_iso="2026-06-01", exit_iso="2026-06-08") is None


# ---- #3 backtest --------------------------------------------------------

def test_backtest_topn_replays_and_beats_benchmark(conn):
    now = datetime.now(timezone.utc)
    # two daily periods, AAA rips, QQQ flat -> basket should beat benchmark
    for i, day in enumerate(["2026-06-01", "2026-06-08"]):
        created = (now - timedelta(days=20 - i * 5)).isoformat()
        due = (now - timedelta(days=18 - i * 5)).isoformat()
        pid = conn.execute(
            "INSERT INTO predictions (ticker, horizon_minutes, direction, prob_up,"
            " confidence, rationale, key_factors_json, model_used, created_at, due_at)"
            " VALUES ('AAA', 390, 'up', 0.7, 0.6, 'r', '[]', 'm', ?, ?)",
            (created, due),
        ).lastrowid
        conn.execute(
            "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier,"
            " scored_at) VALUES (?, 0.05, 1, 0.1, ?)", (pid, due))
        _add_price(conn, "AAA", created[:10], o=100.0, close=110.0)
        _add_price(conn, "AAA", due[:10], o=110.0, close=110.0)
        _add_price(conn, "QQQ", created[:10], o=100.0, close=100.0)
        _add_price(conn, "QQQ", due[:10], o=100.0, close=100.0)
    conn.commit()
    r = backtest_topn(conn, days=30, top_n=3)
    assert r.periods == 2
    assert r.total_excess > 0
    assert "TOTAL EXCESS" in format_backtest(r)


def test_backtest_empty_window(conn):
    r = backtest_topn(conn, days=30)
    assert r.periods == 0
    assert "no scoreable" in r.note


# ---- #6 universe --------------------------------------------------------

def test_megacap_blacklist():
    assert is_megacap("AAPL") and is_megacap("nvda")
    assert not is_megacap("PLTR")
    assert "MSFT" in MEGA_CAPS


def test_ranking_universe_excludes_megacaps(conn):
    conn.execute("INSERT INTO watchlist (ticker, added_at, active) VALUES ('AAPL', 't', 1)")
    conn.execute("INSERT INTO watchlist (ticker, added_at, active) VALUES ('PLTR', 't', 1)")
    conn.commit()
    uni = ranking_universe(conn)
    assert "PLTR" in uni
    assert "AAPL" not in uni
    assert "AAPL" in ranking_universe(conn, include_megacaps=True)


# ---- #7 chart pattern ---------------------------------------------------

def test_chart_pattern_rising_beats_falling(conn):
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    for i in range(20):
        ts = (base + timedelta(days=i)).isoformat()
        _add_price(conn, "UP", ts, o=100.0 + i, close=100.0 + i)      # steady rise
        _add_price(conn, "DN", ts, o=120.0 - i, close=120.0 - i)      # steady fall
    conn.commit()
    up = chart_pattern_score(conn, "UP")
    dn = chart_pattern_score(conn, "DN")
    assert up > 0.6
    assert dn < 0.4
    assert up > dn


def test_chart_pattern_neutral_without_history(conn):
    assert chart_pattern_score(conn, "NOPE") == 0.5
