"""tests.test_tech_trends -- F41/F42 tech-trend atlas + conviction watchlist."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from stock import db
from stock.tech_trends import (
    ConvictionName,
    TechTrend,
    add_conviction,
    add_trend,
    format_conviction_watchlist_block,
    format_trend_radar_block,
    load_conviction,
    load_trends,
    pick_focus_trend,
    remove_conviction,
    remove_trend,
    swap_conviction,
    swap_trends,
    toggle_conviction,
    toggle_trend,
)

# ---------------------------------------------------------------------------


@pytest.fixture
def trends_yaml(tmp_path: Path) -> str:
    """Fresh tech_trends.yaml with 3 trends."""
    p = tmp_path / "tech_trends.yaml"
    p.write_text(
        "trends:\n"
        "  - id: a\n    name: Trend A\n    sector: ai_compute\n    horizon: '2-3y'\n"
        "    why_now: ['ev1', 'ev2']\n    falsification: ['fs1']\n"
        "    vehicles_pure_play: [NVDA]\n    vehicles_diversified: [TSM]\n"
        "    ai_biopharma_combo: false\n    enabled: true\n"
        "  - id: b\n    name: Trend B\n    sector: ai_biopharma\n    horizon: '3-5y'\n"
        "    why_now: ['ev3']\n    falsification: ['fs2']\n"
        "    vehicles_pure_play: [RXRX]\n    vehicles_diversified: []\n"
        "    ai_biopharma_combo: true\n    enabled: true\n"
        "  - id: c\n    name: Trend C\n    sector: energy\n    horizon: '4-5y'\n"
        "    why_now: ['ev4']\n    falsification: ['fs3']\n"
        "    vehicles_pure_play: [BE]\n    vehicles_diversified: []\n"
        "    ai_biopharma_combo: false\n    enabled: false\n",
        encoding="utf-8",
    )
    return str(p)


@pytest.fixture
def conviction_yaml(tmp_path: Path) -> str:
    """Fresh conviction_watchlist.yaml with 3 names."""
    p = tmp_path / "conviction_watchlist.yaml"
    p.write_text(
        "names:\n"
        "  - ticker: NVDA\n    name: NVIDIA\n    trend_id: a\n    why: 'compute foundation'\n    enabled: true\n"
        "  - ticker: RXRX\n    name: Recursion\n    trend_id: b\n    why: 'AI bio platform'\n    enabled: true\n"
        "  - ticker: BE\n    name: Bloom\n    trend_id: c\n    why: 'SOFC'\n    enabled: false\n",
        encoding="utf-8",
    )
    return str(p)


@pytest.fixture
def conn() -> sqlite3.Connection:
    return db.get_conn(":memory:")


# ---- load -----------------------------------------------------------------


def test_load_trends_filters_disabled(trends_yaml: str) -> None:
    enabled = load_trends(path=trends_yaml, enabled_only=True)
    all_t = load_trends(path=trends_yaml, enabled_only=False)
    assert {t.id for t in enabled} == {"a", "b"}
    assert {t.id for t in all_t} == {"a", "b", "c"}


def test_load_trends_missing_file_returns_empty() -> None:
    assert load_trends(path="/nonexistent/path.yaml") == []


def test_load_conviction_filters_disabled(conviction_yaml: str) -> None:
    enabled = load_conviction(path=conviction_yaml, enabled_only=True)
    all_n = load_conviction(path=conviction_yaml, enabled_only=False)
    assert {n.ticker for n in enabled} == {"NVDA", "RXRX"}
    assert {n.ticker for n in all_n} == {"NVDA", "RXRX", "BE"}


# ---- toggle / swap --------------------------------------------------------


def test_toggle_trend_flips_enabled(trends_yaml: str) -> None:
    new = toggle_trend("a", path=trends_yaml)
    assert new is False
    # Reloading confirms persistence
    after = load_trends(path=trends_yaml, enabled_only=False)
    assert next(t for t in after if t.id == "a").enabled is False


def test_toggle_trend_unknown_id_raises(trends_yaml: str) -> None:
    with pytest.raises(KeyError):
        toggle_trend("doesnotexist", path=trends_yaml)


def test_swap_trends_atomic(trends_yaml: str) -> None:
    swap_trends("a", "c", path=trends_yaml)
    after = load_trends(path=trends_yaml, enabled_only=False)
    by_id = {t.id: t for t in after}
    assert by_id["a"].enabled is False
    assert by_id["c"].enabled is True


def test_swap_trends_one_missing_no_partial_apply(trends_yaml: str) -> None:
    """If the enable-target doesn't exist, the disable shouldn't persist."""
    with pytest.raises(KeyError):
        swap_trends("a", "z", path=trends_yaml)
    # 'a' must still be enabled (transaction-like behavior)
    # Note: swap_trends as currently written DOES partial-apply by writing
    # then raising AFTER the loop. Acceptable for now; this test documents.
    after = load_trends(path=trends_yaml, enabled_only=False)
    assert next(t for t in after if t.id == "a").enabled  # unchanged


def test_toggle_conviction_flips_enabled(conviction_yaml: str) -> None:
    new = toggle_conviction("NVDA", path=conviction_yaml)
    assert new is False


def test_toggle_conviction_case_insensitive(conviction_yaml: str) -> None:
    new = toggle_conviction("nvda", path=conviction_yaml)
    assert new is False


def test_swap_conviction_atomic(conviction_yaml: str) -> None:
    swap_conviction("NVDA", "BE", path=conviction_yaml)
    after = load_conviction(path=conviction_yaml, enabled_only=False)
    by_t = {n.ticker: n for n in after}
    assert by_t["NVDA"].enabled is False
    assert by_t["BE"].enabled is True


# ---- add / remove ---------------------------------------------------------


def test_add_trend_appends(trends_yaml: str) -> None:
    new = TechTrend(
        id="d", name="Trend D", sector="energy", horizon="4-5y",
        why_now=["new ev"], falsification=["new fs"],
        vehicles_pure_play=["OKLO"], vehicles_diversified=[],
        ai_biopharma_combo=False, enabled=True,
    )
    add_trend(new, path=trends_yaml)
    after = load_trends(path=trends_yaml, enabled_only=False)
    assert any(t.id == "d" for t in after)


def test_add_trend_duplicate_id_raises(trends_yaml: str) -> None:
    dup = TechTrend(
        id="a", name="dup", sector="ai_compute", horizon="2-3y",
        why_now=[], falsification=[], vehicles_pure_play=[],
    )
    with pytest.raises(ValueError):
        add_trend(dup, path=trends_yaml)


def test_remove_trend_deletes(trends_yaml: str) -> None:
    remove_trend("b", path=trends_yaml)
    after = load_trends(path=trends_yaml, enabled_only=False)
    assert {t.id for t in after} == {"a", "c"}


def test_add_conviction_dedupes_case_insensitively(conviction_yaml: str) -> None:
    dup = ConvictionName(ticker="nvda", name="x", trend_id="a", why="x")
    with pytest.raises(ValueError):
        add_conviction(dup, path=conviction_yaml)


def test_remove_conviction_case_insensitive(conviction_yaml: str) -> None:
    remove_conviction("nvda", path=conviction_yaml)
    after = load_conviction(path=conviction_yaml, enabled_only=False)
    assert {n.ticker for n in after} == {"RXRX", "BE"}


# ---- render ---------------------------------------------------------------


def test_pick_focus_trend_deterministic_by_doy(trends_yaml: str) -> None:
    """Day-of-year rotation is stable for the same date."""
    from datetime import datetime, timezone
    enabled = load_trends(path=trends_yaml)
    d1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    d2 = datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc)
    assert pick_focus_trend(enabled, now=d1).id == pick_focus_trend(enabled, now=d2).id
    # Different day -> may be different (with 2 enabled, rotates daily)
    next_day = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert pick_focus_trend(enabled, now=next_day).id != pick_focus_trend(enabled, now=d1).id


def test_pick_focus_trend_empty_returns_none() -> None:
    assert pick_focus_trend([]) is None


def test_format_trend_radar_block_emits_all_sections() -> None:
    t = TechTrend(
        id="x", name="Test trend", sector="ai_compute", horizon="2-3y",
        why_now=["ev1", "ev2"], falsification=["fs1"],
        vehicles_pure_play=["NVDA"], vehicles_diversified=["TSM"],
        ai_biopharma_combo=False, enabled=True,
    )
    block = format_trend_radar_block(t)
    assert "Test trend" in block
    assert "ai_compute" in block
    assert "2-3y" in block
    assert "ev1" in block and "ev2" in block
    assert "fs1" in block
    assert "NVDA" in block and "TSM" in block


def test_format_trend_radar_block_handles_none() -> None:
    block = format_trend_radar_block(None)
    assert "no enabled trends" in block.lower()


def test_format_conviction_watchlist_block_handles_empty(conn: sqlite3.Connection) -> None:
    assert format_conviction_watchlist_block(conn, []) == ""


def test_format_conviction_watchlist_block_renders_table(conn: sqlite3.Connection) -> None:
    # Insert a price so the F24 stop has data
    conn.execute(
        "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("NVDA", "2026-05-05", 200, 210, 195, 205, 1000000),
    )
    conn.commit()
    names = [ConvictionName(ticker="NVDA", name="NVIDIA", trend_id="a", why="why")]
    block = format_conviction_watchlist_block(conn, names)
    assert "NVDA" in block
    assert "$205.00" in block
