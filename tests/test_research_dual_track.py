"""tests.test_research_dual_track -- CN/US 双轨 daily report split.

Boss spec (2026-06-17): A/H names are both China ('CN'); US-listed (incl. ADRs)
are 'US'. The daily push produces two notes, CN then US, each persisted (== pushed)
as it finishes. History/grading is NOT partitioned -- only the forward-looking
daily notes are split.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

from stock.market_track import CN, US
from stock.models import ChatResponse
from stock.research import (
    _build_watchlist_block,
    _build_watchlist_movers_block,
    _persist_research,
    _track_directive,
    generate_daily_research,
)


def _seed_watchlist_prediction(conn: sqlite3.Connection, ticker: str) -> None:
    """Add an active watchlist ticker with a fresh prediction in the lookback."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES (?, ?, 1)",
        (ticker, now),
    )
    conn.execute(
        "INSERT INTO predictions ("
        "ticker, horizon_minutes, direction, prob_up, prob_up_calibrated,"
        " expected_return_bps, confidence, rationale, key_factors_json,"
        " model_used, strategy_arm, rules_version, retrieved_case_ids,"
        " created_at, due_at, feature_context_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ticker, 1440, "up", 0.61, 0.60, None, 0.70,
            f"{ticker} forward thesis", "[]", "test", None, None, None,
            now, now, None,
        ),
    )
    conn.commit()


# --- _track_directive -------------------------------------------------------

def test_track_directive_none_is_empty() -> None:
    """A legacy combined note gets no track scoping."""
    assert _track_directive(None) == ""


def test_track_directive_cn_scopes_to_china() -> None:
    directive = _track_directive(CN)
    assert "只写中国" in directive
    assert ".SS" in directive and ".HK" in directive


def test_track_directive_us_scopes_to_us() -> None:
    directive = _track_directive(US)
    assert "只写美股" in directive
    assert "ADR" in directive


# --- watchlist block track filtering ----------------------------------------

def test_watchlist_block_filters_by_track(mem_db: sqlite3.Connection) -> None:
    """CN track keeps A/H names; US track keeps US-listed names."""
    _seed_watchlist_prediction(mem_db, "600941.SS")  # A-share -> CN
    _seed_watchlist_prediction(mem_db, "0941.HK")    # H-share -> CN
    _seed_watchlist_prediction(mem_db, "NVDA")       # US-listed -> US

    cn_block = _build_watchlist_block(mem_db, track=CN)
    assert "600941.SS" in cn_block and "0941.HK" in cn_block
    assert "NVDA" not in cn_block

    us_block = _build_watchlist_block(mem_db, track=US)
    assert "NVDA" in us_block
    assert "600941.SS" not in us_block

    both = _build_watchlist_block(mem_db, track=None)
    assert "NVDA" in both and "600941.SS" in both


def test_watchlist_movers_block_filters_by_track(mem_db: sqlite3.Connection) -> None:
    """A US mover is excluded from the CN-track movers block."""
    mem_db.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES (?, ?, 1)",
        ("NVDA", "2026-06-16T00:00:00+00:00"),
    )
    mem_db.execute(
        "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("NVDA", "2026-06-16", 100, 101, 99, 100, 1_000_000),
    )
    mem_db.execute(
        "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("NVDA", "2026-06-17", 100, 120, 99, 118, 3_000_000),
    )
    mem_db.commit()

    us_block = _build_watchlist_movers_block(mem_db, track=US)
    assert "NVDA" in us_block

    cn_block = _build_watchlist_movers_block(mem_db, track=CN)
    assert "NVDA" not in cn_block


# --- persistence ------------------------------------------------------------

def test_persist_research_records_track(mem_db: sqlite3.Connection) -> None:
    rid = _persist_research(
        mem_db, kind="daily", topic=None, layer_focus="L",
        body="body", cost_usd=0.0, track=CN,
    )
    row = mem_db.execute(
        "SELECT track FROM research_reports WHERE id = ?", (rid,)
    ).fetchone()
    assert row[0] == CN


def test_persist_research_track_defaults_null(mem_db: sqlite3.Connection) -> None:
    rid = _persist_research(
        mem_db, kind="reply", topic="t", layer_focus=None, body="b", cost_usd=0.0,
    )
    row = mem_db.execute(
        "SELECT track FROM research_reports WHERE id = ?", (rid,)
    ).fetchone()
    assert row[0] is None


# --- full generate_daily_research, track-scoped -----------------------------

def test_generate_daily_research_cn_track(
    mem_db: sqlite3.Connection, env_settings: object,
) -> None:
    """A CN-track note persists with track='CN' and injects the CN directive."""
    _seed_watchlist_prediction(mem_db, "600941.SS")
    # MU is US-listed (and, unlike NVDA, is not named in the directive text), so it
    # is a clean probe that the US ticker is filtered out of the CN context.
    _seed_watchlist_prediction(mem_db, "MU")

    captured: dict[str, str] = {}

    def fake_core_chat(*, messages, max_tokens, conn, caller, cached_system=None):
        captured["user"] = messages[0]["content"]
        return ChatResponse(
            content="结论:CN note.\n\nNot financial advice.",
            input_tokens=10, output_tokens=10, model="test", cost_usd=0.0,
        )

    with patch("stock.research._core_chat", side_effect=fake_core_chat):
        report = generate_daily_research(mem_db, track=CN)

    assert report.track == CN
    row = mem_db.execute(
        "SELECT track, kind FROM research_reports WHERE id = ?",
        (report.research_id,),
    ).fetchone()
    assert row[0] == CN and row[1] == "daily"
    # CN directive present; CN ticker's signal in context, US ticker's filtered
    # out. Probe on the distinctive seeded rationale so we don't collide with the
    # ticker symbol appearing inside template prose (e.g. "MU" inside "MUST").
    assert "只写中国" in captured["user"]
    assert "600941.SS forward thesis" in captured["user"]
    assert "MU forward thesis" not in captured["user"]
