"""tests.test_discovery_engine -- F19 universe build, scoring, persistence, promotion."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock import discovery_engine
from stock.discovery_engine import (
    build_discovery_universe,
    dismiss_candidate,
    list_candidates,
    promote_candidate,
    run_discovery_engine,
)
from stock.leading import CandidateScore


def _seed_watchlist(conn: sqlite3.Connection, *tickers: str) -> None:
    """Seed the watchlist table."""
    now = datetime.now(timezone.utc).isoformat()
    for t in tickers:
        conn.execute(
            "INSERT OR REPLACE INTO watchlist (ticker, added_at, active)"
            " VALUES (?, ?, 1)",
            (t, now),
        )
    conn.commit()


def _seed_news(
    conn: sqlite3.Connection, *, ticker: str, ts: str, title: str = "x",
) -> None:
    conn.execute(
        "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at)"
        " VALUES (?, 'rss', ?, ?, '', ?, ?)",
        (ticker, f"http://x/{ticker}/{ts}", title, ts,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


# -- build_discovery_universe -----------------------------------------------


def test_universe_includes_active_watchlist(mem_db: sqlite3.Connection) -> None:
    """Active watchlist tickers always make the universe."""
    _seed_watchlist(mem_db, "NVDA", "AMD")
    universe = build_discovery_universe(mem_db)
    assert "NVDA" in universe
    assert "AMD" in universe


def test_universe_dedupes(mem_db: sqlite3.Connection) -> None:
    """Same ticker on watchlist and via news only appears once."""
    _seed_watchlist(mem_db, "NVDA")
    _seed_news(mem_db, ticker="NVDA", ts=datetime.now(timezone.utc).isoformat())
    universe = build_discovery_universe(mem_db)
    assert universe.count("NVDA") == 1


def test_universe_includes_recent_news_tickers(mem_db: sqlite3.Connection) -> None:
    """Tickers that appeared in news in the last N days are added."""
    fresh = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    _seed_news(mem_db, ticker="SMCI", ts=fresh)
    _seed_news(mem_db, ticker="DUOL", ts=fresh)
    universe = build_discovery_universe(mem_db)
    assert "SMCI" in universe
    assert "DUOL" in universe


def test_universe_excludes_old_news(mem_db: sqlite3.Connection) -> None:
    """News older than NEWS_LOOKBACK_DAYS is excluded."""
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    _seed_news(mem_db, ticker="OLDCO", ts=old)
    universe = build_discovery_universe(mem_db)
    assert "OLDCO" not in universe


# -- run_discovery_engine ---------------------------------------------------


def test_run_discovery_engine_persists_candidates(mem_db: sqlite3.Connection) -> None:
    """One pass creates discovery_candidates rows for every scored ticker."""
    _seed_watchlist(mem_db, "NVDA", "AMD")

    def _fake_score(ticker, conn, *, apewisdom_snapshot=None,
                    population_means=None, population_stdevs=None, **kw):
        return CandidateScore(
            ticker=ticker, fwp=0.20, fwp_pre_gate=0.20, qap_gate=False,
            components={"ocis_raw": 0.0, "ocis_cluster_max": 0,
                        "novelty_raw": 0.0, "reddit_accel": 0.0},
            score_at=datetime.now(timezone.utc).isoformat(),
        )

    with (
        patch("stock.discovery_engine.fetch_apewisdom_snapshot", return_value={}),
        patch("stock.discovery_engine.build_discovery_universe",
              return_value=["NVDA", "AMD"]),
        patch("stock.discovery_engine.compute_future_winner_probability",
              side_effect=_fake_score),
    ):
        result = run_discovery_engine(mem_db)

    rows = mem_db.execute(
        "SELECT ticker FROM discovery_candidates"
    ).fetchall()
    assert {r[0] for r in rows} == {"NVDA", "AMD"}
    assert result.scored == 2
    assert result.new_candidates == 2


def test_run_discovery_engine_promotes_above_threshold(
    mem_db: sqlite3.Connection,
) -> None:
    """Ticker above threshold + QAP gate + not on watchlist -> promoted."""
    fresh_news = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    _seed_news(mem_db, ticker="GEMHIDDEN", ts=fresh_news)

    fake_score = CandidateScore(
        ticker="GEMHIDDEN", fwp=0.80, fwp_pre_gate=0.80, qap_gate=True,
        components={"ocis_raw": 50.0, "ocis_cluster_max": 4, "novelty_raw": 0.7,
                    "reddit_accel": 4.0},
        score_at=datetime.now(timezone.utc).isoformat(),
    )

    with (
        patch("stock.discovery_engine.fetch_apewisdom_snapshot", return_value={}),
        patch("stock.discovery_engine.build_discovery_universe",
              return_value=[fake_score.ticker]),
        patch("stock.discovery_engine.compute_future_winner_probability",
              return_value=fake_score),
    ):
        result = run_discovery_engine(mem_db, auto_promote=True)

    assert "GEMHIDDEN" in result.promoted_tickers
    on_wl = mem_db.execute(
        "SELECT 1 FROM watchlist WHERE ticker = 'GEMHIDDEN' AND active = 1"
    ).fetchone()
    assert on_wl is not None
    cand_status = mem_db.execute(
        "SELECT status FROM discovery_candidates WHERE ticker = 'GEMHIDDEN'"
    ).fetchone()
    assert cand_status[0] == "promoted"


def test_run_discovery_engine_does_not_promote_no_gate(
    mem_db: sqlite3.Connection,
) -> None:
    """High score but QAP gate false -> not promoted."""
    fresh = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    _seed_news(mem_db, ticker="HIGHFWPNOGATE", ts=fresh)

    fake_score = CandidateScore(
        ticker="HIGHFWPNOGATE", fwp=0.90, fwp_pre_gate=0.90, qap_gate=False,
        components={"ocis_raw": 100.0, "ocis_cluster_max": 5, "novelty_raw": 0.9,
                    "reddit_accel": 10.0},
        score_at=datetime.now(timezone.utc).isoformat(),
    )

    with (
        patch("stock.discovery_engine.fetch_apewisdom_snapshot", return_value={}),
        patch("stock.discovery_engine.build_discovery_universe",
              return_value=[fake_score.ticker]),
        patch("stock.discovery_engine.compute_future_winner_probability",
              return_value=fake_score),
    ):
        result = run_discovery_engine(mem_db, auto_promote=True)

    assert "HIGHFWPNOGATE" not in result.promoted_tickers


def test_run_discovery_engine_does_not_promote_dismissed(
    mem_db: sqlite3.Connection,
) -> None:
    """Recently-dismissed ticker is not auto-promoted even with strong score."""
    fresh = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    _seed_news(mem_db, ticker="DISMISSED", ts=fresh)
    # Pre-dismiss
    mem_db.execute(
        "INSERT INTO discovery_candidates ("
        "  ticker, score, components_json, qap_gate, first_flagged_at,"
        "  last_score_at, last_score, status, dismissed_at)"
        " VALUES (?, 0.5, '{}', 1, ?, ?, 0.5, 'dismissed', ?)",
        ("DISMISSED",
         (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
         (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
         (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()),
    )
    mem_db.commit()

    fake_score = CandidateScore(
        ticker="DISMISSED", fwp=0.85, fwp_pre_gate=0.85, qap_gate=True,
        components={"ocis_raw": 50.0, "ocis_cluster_max": 4, "novelty_raw": 0.7,
                    "reddit_accel": 5.0},
        score_at=datetime.now(timezone.utc).isoformat(),
    )

    with (
        patch("stock.discovery_engine.fetch_apewisdom_snapshot", return_value={}),
        patch("stock.discovery_engine.build_discovery_universe",
              return_value=[fake_score.ticker]),
        patch("stock.discovery_engine.compute_future_winner_probability",
              return_value=fake_score),
    ):
        result = run_discovery_engine(mem_db, auto_promote=True)

    assert "DISMISSED" not in result.promoted_tickers


def test_run_discovery_engine_caps_promotions(mem_db: sqlite3.Connection) -> None:
    """At most AUTO_PROMOTE_MAX_PER_RUN tickers promoted per pass."""
    fresh = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    for t in ["WIN1", "WIN2", "WIN3", "WIN4", "WIN5"]:
        _seed_news(mem_db, ticker=t, ts=fresh)

    fake_scores = {
        t: CandidateScore(
            ticker=t, fwp=0.90 - i * 0.01, fwp_pre_gate=0.90, qap_gate=True,
            components={"ocis_raw": 50.0, "ocis_cluster_max": 3, "novelty_raw": 0.6,
                        "reddit_accel": 2.0},
            score_at=datetime.now(timezone.utc).isoformat(),
        ) for i, t in enumerate(["WIN1", "WIN2", "WIN3", "WIN4", "WIN5"])
    }

    def _fake(ticker, conn, *, apewisdom_snapshot=None,
              population_means=None, population_stdevs=None, **kw):
        return fake_scores[ticker]

    with (
        patch("stock.discovery_engine.fetch_apewisdom_snapshot", return_value={}),
        patch("stock.discovery_engine.build_discovery_universe",
              return_value=list(fake_scores.keys())),
        patch("stock.discovery_engine.compute_future_winner_probability",
              side_effect=_fake),
    ):
        result = run_discovery_engine(mem_db, auto_promote=True)

    assert len(result.promoted_tickers) == discovery_engine.AUTO_PROMOTE_MAX_PER_RUN


# -- dismiss + list ---------------------------------------------------------


def test_dismiss_marks_status(mem_db: sqlite3.Connection) -> None:
    """dismiss_candidate flips status + stamps dismissed_at."""
    mem_db.execute(
        "INSERT INTO discovery_candidates ("
        "  ticker, score, components_json, qap_gate, first_flagged_at,"
        "  last_score_at, last_score, status)"
        " VALUES ('TEMP', 0.5, '{}', 1, ?, ?, 0.5, 'candidate')",
        (datetime.now(timezone.utc).isoformat(),
         datetime.now(timezone.utc).isoformat()),
    )
    mem_db.commit()
    ok = dismiss_candidate(mem_db, "TEMP", reason="too illiquid")
    assert ok
    row = mem_db.execute(
        "SELECT status, notes FROM discovery_candidates WHERE ticker = 'TEMP'"
    ).fetchone()
    assert row[0] == "dismissed"
    assert "too illiquid" in row[1]


def test_promote_candidate_auto_thesis_called_when_components_provided(
    mem_db: sqlite3.Connection,
) -> None:
    """F22: promote_candidate(auto_thesis=True, components=...) calls generate_discovery_thesis."""
    mem_db.execute(
        "INSERT INTO discovery_candidates ("
        "  ticker, score, components_json, qap_gate, first_flagged_at,"
        "  last_score_at, last_score, status)"
        " VALUES ('FOOBAR', 0.7, '{}', 1, ?, ?, 0.7, 'candidate')",
        (datetime.now(timezone.utc).isoformat(),
         datetime.now(timezone.utc).isoformat()),
    )
    mem_db.commit()

    fake_report = MagicMock(research_id=42, cost_usd=0.005)
    with patch("stock.research.generate_discovery_thesis",
               return_value=fake_report) as mock_thesis:
        promote_candidate(
            mem_db, "FOOBAR", score=0.7,
            components={"ocis_raw": 5.0, "ocis_cluster_max": 3},
            auto_thesis=True,
        )
    mock_thesis.assert_called_once()


def test_promote_candidate_auto_thesis_skipped_when_no_components(
    mem_db: sqlite3.Connection,
) -> None:
    """No components -> no thesis call (caller forgot, don't fabricate one)."""
    mem_db.execute(
        "INSERT INTO discovery_candidates ("
        "  ticker, score, components_json, qap_gate, first_flagged_at,"
        "  last_score_at, last_score, status)"
        " VALUES ('FOOBAR2', 0.7, '{}', 1, ?, ?, 0.7, 'candidate')",
        (datetime.now(timezone.utc).isoformat(),
         datetime.now(timezone.utc).isoformat()),
    )
    mem_db.commit()

    with patch("stock.research.generate_discovery_thesis") as mock_thesis:
        promote_candidate(mem_db, "FOOBAR2", score=0.7,
                          components=None, auto_thesis=True)
    mock_thesis.assert_not_called()


def test_promote_candidate_auto_thesis_failure_is_non_fatal(
    mem_db: sqlite3.Connection,
) -> None:
    """If generate_discovery_thesis raises, promotion still succeeds."""
    mem_db.execute(
        "INSERT INTO discovery_candidates ("
        "  ticker, score, components_json, qap_gate, first_flagged_at,"
        "  last_score_at, last_score, status)"
        " VALUES ('FOOBAR3', 0.7, '{}', 1, ?, ?, 0.7, 'candidate')",
        (datetime.now(timezone.utc).isoformat(),
         datetime.now(timezone.utc).isoformat()),
    )
    mem_db.commit()
    with patch("stock.research.generate_discovery_thesis",
               side_effect=RuntimeError("LLM exploded")):
        ok = promote_candidate(
            mem_db, "FOOBAR3", score=0.7,
            components={"ocis_raw": 5.0}, auto_thesis=True,
        )
    assert ok is True
    on_wl = mem_db.execute(
        "SELECT 1 FROM watchlist WHERE ticker = 'FOOBAR3' AND active = 1"
    ).fetchone()
    assert on_wl is not None


def test_list_candidates_orders_by_score(mem_db: sqlite3.Connection) -> None:
    """list_candidates returns highest-FWP first."""
    now = datetime.now(timezone.utc).isoformat()
    for t, s in [("LOW", 0.20), ("HIGH", 0.85), ("MID", 0.50)]:
        mem_db.execute(
            "INSERT INTO discovery_candidates ("
            "  ticker, score, components_json, qap_gate, first_flagged_at,"
            "  last_score_at, last_score, status)"
            " VALUES (?, ?, '{}', 1, ?, ?, ?, 'candidate')",
            (t, s, now, now, s),
        )
    mem_db.commit()
    rows = list_candidates(mem_db, status="candidate")
    assert [r.ticker for r in rows] == ["HIGH", "MID", "LOW"]
