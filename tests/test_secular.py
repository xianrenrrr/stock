"""tests.test_secular -- F25 secular themes."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from stock.secular import (
    SecularTheme,
    all_secular_tickers,
    format_theme_block,
    load_themes,
    pick_focus_theme,
)


def test_load_themes_from_default_yaml() -> None:
    """The shipped data/secular_themes.yaml parses into >= 3 themes."""
    themes = load_themes()
    assert len(themes) >= 3
    # Each theme must have the boss-asked-for axes
    titles = {t.theme for t in themes}
    assert "china_aging_crisis" in titles
    assert "us_wealth_inequality_divergence" in titles
    assert "ai_displacement_consumer_crisis" in titles


def test_each_theme_has_picks_and_indicators() -> None:
    """Every theme has at least 3 beneficiaries, 1 loser, 2 leading indicators."""
    for theme in load_themes():
        assert len(theme.beneficiaries) >= 3
        assert len(theme.losers) >= 1
        assert len(theme.leading_indicators) >= 2


def test_pick_focus_rotates_by_day(tmp_path: Path) -> None:
    """Different day-of-year picks different theme."""
    themes = load_themes()
    if len(themes) < 2:
        pytest.skip("Need at least 2 themes to test rotation")
    day1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    day_after = datetime(2026, 1, 2, tzinfo=timezone.utc)
    one = pick_focus_theme(themes, now=day1)
    two = pick_focus_theme(themes, now=day_after)
    assert one is not None and two is not None
    # Two adjacent days should land on different themes (modulo collisions if N=1)
    assert one.theme != two.theme


def test_format_theme_block_contains_thesis_and_picks() -> None:
    """Rendered block has thesis text + at least one beneficiary line."""
    themes = load_themes()
    block = format_theme_block(themes[0])
    assert "Theme" in block or "主题" in block
    assert "Thesis" in block or "论点" in block
    assert "Long beneficiaries" in block or "长持候选" in block


def test_format_theme_block_handles_none() -> None:
    """None input -> placeholder string, never crashes."""
    assert "no secular themes" in format_theme_block(None)


def test_all_secular_tickers_dedupes() -> None:
    """Same ticker appearing in multiple themes appears only once."""
    tickers = all_secular_tickers()
    assert len(tickers) == len(set(tickers))
