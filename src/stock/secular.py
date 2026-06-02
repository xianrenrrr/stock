"""stock.secular -- non-AI long-horizon (5-10y) themes for portfolio diversification.

F25: boss explicitly asked for "hidden gems not driven by AI but by things you
believe gonna happen in the next 5-10 years -- China aging crisis, US wealth
inequality, AI displacement / consumer crisis."

The default research note is AI-supply-chain-focused (data/ai_supply_chain.yaml).
This module loads data/secular_themes.yaml in parallel and rotates which secular
theme is the focus for any given day. The daily research generator pulls a
`secular_block` alongside the AI focus layer so every note has BOTH:
  - AI capex layer of the day
  - One secular megatrend with 2-3 names + leading indicators

Themes are intentionally broad (China aging, US inequality, AI displacement,
India demographic). Each names beneficiaries + losers + 3-5 leading indicators
the operator can monitor manually.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SECULAR_THEMES_PATH: str = "data/secular_themes.yaml"


class SecularPick(BaseModel):
    """One ticker within a secular theme (beneficiary or loser)."""

    ticker: str
    name: str
    thesis: str


class SecularTheme(BaseModel):
    """One long-horizon megatrend with beneficiaries + losers + leading indicators."""

    theme: str
    horizon_years: int
    thesis: str
    leading_indicators: list[str]
    beneficiaries: list[SecularPick]
    losers: list[SecularPick]


def load_themes(path: str | None = None) -> list[SecularTheme]:
    """Load all secular themes from data/secular_themes.yaml.

    Returns [] if the file is missing -- the daily research falls back to its
    AI-only behaviour. Schema mismatches log a warning but don't raise.
    """
    p = Path(path or SECULAR_THEMES_PATH)
    if not p.exists():
        logger.warning("secular themes file missing at %s", p)
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("themes"), list):
        logger.warning("secular themes file malformed at %s", p)
        return []

    themes: list[SecularTheme] = []
    for entry in raw["themes"]:
        try:
            themes.append(SecularTheme(
                theme=str(entry["theme"]),
                horizon_years=int(entry.get("horizon_years", 5)),
                thesis=str(entry.get("thesis", "")).strip(),
                leading_indicators=[
                    str(s) for s in (entry.get("leading_indicators") or []) if s
                ],
                beneficiaries=[
                    SecularPick(
                        ticker=str(p.get("ticker", "")),
                        name=str(p.get("name", "")),
                        thesis=str(p.get("thesis", "")),
                    )
                    for p in (entry.get("beneficiaries") or [])
                    if p.get("ticker")
                ],
                losers=[
                    SecularPick(
                        ticker=str(p.get("ticker", "")),
                        name=str(p.get("name", "")),
                        thesis=str(p.get("thesis", "")),
                    )
                    for p in (entry.get("losers") or [])
                    if p.get("ticker")
                ],
            ))
        except Exception:
            logger.exception("secular theme parse failed for entry: %r", entry)
    return themes


def pick_focus_theme(
    themes: list[SecularTheme], *, now: datetime | None = None,
) -> SecularTheme | None:
    """Rotate by day-of-year so each theme gets approximately equal airtime.

    With N themes and ~365 days, each theme is the secular focus ~73 days/yr.
    Returns None if no themes are configured.
    """
    if not themes:
        return None
    moment = now or datetime.now(timezone.utc)
    idx = moment.timetuple().tm_yday % len(themes)
    return themes[idx]


def format_theme_block(theme: SecularTheme | None, *, max_picks: int = 4) -> str:
    """Render one focus theme as a markdown block for the research-note prompt.

    max_picks caps each side (beneficiaries + losers) so the prompt stays tight.
    """
    if theme is None:
        return "(no secular themes configured)"

    lines: list[str] = []
    lines.append(f"**主题 / Theme**: {theme.theme} (horizon {theme.horizon_years}y)")
    lines.append("")
    lines.append("**论点 / Thesis**:")
    lines.append(theme.thesis.strip())
    lines.append("")

    if theme.leading_indicators:
        lines.append("**领先指标 / Leading indicators to monitor**:")
        for ind in theme.leading_indicators:
            lines.append(f"- {ind}")
        lines.append("")

    if theme.beneficiaries:
        lines.append("**长持候选 / Long beneficiaries**:")
        for p in theme.beneficiaries[:max_picks]:
            lines.append(f"- `{p.ticker}` {p.name} -- {p.thesis}")
        lines.append("")

    if theme.losers:
        lines.append("**潜在做空 / Avoid / short candidates**:")
        for p in theme.losers[:max_picks]:
            lines.append(f"- `{p.ticker}` {p.name} -- {p.thesis}")
        lines.append("")

    return "\n".join(lines).rstrip()


def all_secular_tickers(themes: list[SecularTheme] | None = None) -> list[str]:
    """Return every ticker mentioned across all secular themes (for stop-loss precompute)."""
    themes = themes if themes is not None else load_themes()
    seen: list[str] = []
    for theme in themes:
        for p in theme.beneficiaries + theme.losers:
            t = (p.ticker or "").upper()
            if t and t not in seen:
                seen.append(t)
    return seen
