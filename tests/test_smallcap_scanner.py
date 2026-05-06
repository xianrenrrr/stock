"""tests.test_smallcap_scanner -- F38 'find before it explodes' scanner."""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from stock import db
from stock.smallcap_scanner import (
    SmallCapCandidate,
    _UniverseRow,
    _composite_score,
    _flag_reason,
    _mkt_cap_score,
    _news_sparsity_score,
    _revenue_inflection_score,
    format_smallcap_block,
    persist,
    scan_universe,
    score_one,
    top_per_sector,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Schema-applied in-memory DB."""
    return db.get_conn(":memory:")


# ---- score-component unit tests --------------------------------------------


def test_mkt_cap_score_curve() -> None:
    assert _mkt_cap_score(200_000_000) == 1.0           # < $500M
    assert _mkt_cap_score(1_000_000_000) == 0.85        # $500M-$2B
    assert _mkt_cap_score(3_000_000_000) == 0.65        # $2B-$5B
    assert _mkt_cap_score(8_000_000_000) == 0.40        # $5B-$15B
    assert _mkt_cap_score(50_000_000_000) == 0.15       # > $15B
    assert _mkt_cap_score(None) == 0.30                 # unknown


def test_revenue_inflection_score_directional() -> None:
    """Acceleration scores higher than deceleration."""
    accel = _revenue_inflection_score(latest_qoq=0.60, prior_4q_mean=0.20)
    decel = _revenue_inflection_score(latest_qoq=0.10, prior_4q_mean=0.40)
    flat = _revenue_inflection_score(latest_qoq=0.30, prior_4q_mean=0.30)
    assert accel > 0.7
    assert decel < 0.3
    assert flat == 0.5
    assert _revenue_inflection_score(None, 0.2) == 0.30  # missing data


def test_news_sparsity_score_inverse() -> None:
    """Less news = higher score."""
    assert _news_sparsity_score(0) == 1.0
    assert _news_sparsity_score(2) == 0.85
    assert _news_sparsity_score(5) == 0.65
    assert _news_sparsity_score(20) == 0.40
    assert _news_sparsity_score(50) == 0.15


def test_composite_weights() -> None:
    """40% mkt cap + 40% rev + 20% news sparsity."""
    assert _composite_score(1.0, 1.0, 1.0) == pytest.approx(1.0)
    assert _composite_score(0.0, 0.0, 0.0) == 0.0
    assert _composite_score(1.0, 0.0, 0.0) == pytest.approx(0.40)
    assert _composite_score(0.0, 0.0, 1.0) == pytest.approx(0.20)


def test_flag_reason_combinations() -> None:
    assert "micro" in _flag_reason(0.95, 0.5, 0.5)
    assert "acceleration" in _flag_reason(0.5, 0.80, 0.5)
    assert "hidden" in _flag_reason(0.5, 0.5, 0.95)
    assert "WIDELY" in _flag_reason(0.5, 0.5, 0.20)


# ---- scan + persist + render -----------------------------------------------


def _row(ticker: str = "BE", sector: str = "ai_dc_energy_smallcap") -> _UniverseRow:
    return _UniverseRow(
        ticker=ticker, name=f"{ticker} Inc",
        sector=sector, mkt_cap_target_usd=2_000_000_000,
        niche_bottleneck="solves a thing",
        inflection_signal="customer X",
    )


def test_score_one_assembles_candidate() -> None:
    cand = score_one(
        _row("VKTX", "biopharma_smallcap"),
        market_cap_usd=4_000_000_000,
        latest_qoq=0.50, prior_4q_mean=0.10,
        news_count_90d=4,
    )
    assert cand.ticker == "VKTX"
    assert cand.sector == "biopharma_smallcap"
    assert cand.market_cap_usd == 4_000_000_000
    assert cand.revenue_inflection == pytest.approx(0.40)
    assert cand.score > 0.5  # mid-cap + acceleration + low coverage


def test_scan_universe_isolates_provider_failures(conn: sqlite3.Connection) -> None:
    """One ticker's provider error doesn't crash the whole scan."""
    rows = [_row("OK"), _row("BAD"), _row("ALSO_OK")]

    def provider(t: str):
        if t == "BAD":
            raise RuntimeError("yfinance down")
        return (1_000_000_000, 0.30, 0.10)

    cands = scan_universe(conn, universe=rows, market_data_provider=provider)
    assert len(cands) == 3
    by_t = {c.ticker: c for c in cands}
    assert by_t["BAD"].market_cap_usd is None
    # OK + ALSO_OK got real data
    assert by_t["OK"].market_cap_usd == 1_000_000_000


def test_persist_skips_below_min_score(conn: sqlite3.Connection) -> None:
    """Garbage-low scores don't pollute the table."""
    candidates = [
        SmallCapCandidate(
            ticker="JUNK", sector="x", name="J",
            market_cap_usd=200e9, revenue_inflection=-0.50,
            news_sparsity_score=0.15, score=0.10,  # below threshold
            niche_bottleneck="-", inflection_signal=None, flag_reason="-",
        ),
        SmallCapCandidate(
            ticker="GOOD", sector="ai_semis_smallcap", name="G",
            market_cap_usd=500e6, revenue_inflection=0.30,
            news_sparsity_score=0.85, score=0.75,
            niche_bottleneck="-", inflection_signal=None, flag_reason="-",
        ),
    ]
    n = persist(conn, candidates)
    assert n == 1  # GOOD only
    rows = conn.execute("SELECT ticker FROM smallcap_candidates").fetchall()
    assert rows == [("GOOD",)]


def test_top_per_sector_groups_and_caps(conn: sqlite3.Connection) -> None:
    """Returns {sector: [top-N rows]} sorted by score desc."""
    candidates = [
        SmallCapCandidate(
            ticker=f"AI{i}", sector="ai_semis_smallcap", name=f"AI{i}",
            market_cap_usd=1e9, revenue_inflection=0.0,
            news_sparsity_score=0.85,
            score=0.4 + i * 0.05,  # 0.4, 0.45, 0.5, ..., 0.75
            niche_bottleneck="x", inflection_signal=None, flag_reason="-",
        )
        for i in range(8)
    ]
    persist(conn, candidates)
    by_sector = top_per_sector(conn, days=1, top_n=5)
    assert "ai_semis_smallcap" in by_sector
    rows = by_sector["ai_semis_smallcap"]
    assert len(rows) == 5
    # Highest score first
    assert rows[0]["ticker"] == "AI7"
    assert rows[-1]["ticker"] == "AI3"


def test_format_smallcap_block_empty_when_no_candidates(conn: sqlite3.Connection) -> None:
    assert format_smallcap_block(conn, days=1) == ""


def test_format_smallcap_block_renders_table(conn: sqlite3.Connection) -> None:
    candidates = [
        SmallCapCandidate(
            ticker="VKTX", sector="biopharma_smallcap", name="Viking",
            market_cap_usd=4e9, revenue_inflection=0.40,
            news_sparsity_score=0.65, score=0.72,
            niche_bottleneck="GLP-1 oral next-gen",
            inflection_signal="-", flag_reason="-",
        ),
    ]
    persist(conn, candidates)
    block = format_smallcap_block(conn, days=1)
    assert "Biopharma" in block
    assert "VKTX" in block
    assert "$4.0B" in block
    assert "+40pp" in block
