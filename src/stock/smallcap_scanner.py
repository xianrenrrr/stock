"""stock.smallcap_scanner -- F38 'find before it explodes' scanner.

Boss directive 2026-05-05: the value is finding names BEFORE they re-rate
(the Bloom Energy template -- ~$2B before its 20x run, solving a concrete
near-term bottleneck nobody else was sized for). This scanner walks the
curated multi-field small-cap universe and scores each ticker on:

  * mkt_cap_score      -- smaller = higher (caps below $5B prized)
  * revenue_inflection -- latest QoQ revenue growth vs trailing 4Q mean
  * news_sparsity      -- inverse of how much our DB has been seeing this name
                          (boss explicitly wants the NOT-yet-noticed names)

Composite score = 0.40 * mkt_cap + 0.40 * revenue_inflection + 0.20 * news_sparsity

Persisted to smallcap_candidates table; the daily research note pulls the
top-N per sector. Cron schedule: nightly at 22:30 UTC after FWP discovery.
"""
from __future__ import annotations

import logging
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

UNIVERSE_PATH: str = "data/smallcap_universe.yaml"
NEWS_LOOKBACK_DAYS: int = 90
TOP_PER_SECTOR: int = 5
MIN_SCORE_TO_PERSIST: float = 0.20  # noise floor


class SmallCapCandidate(BaseModel):
    """One candidate row -- ready for DB insert + prompt rendering."""

    ticker: str
    sector: str
    name: str
    market_cap_usd: float | None
    revenue_inflection: float | None
    news_sparsity_score: float | None
    score: float
    niche_bottleneck: str
    inflection_signal: str | None
    flag_reason: str


@dataclass
class _UniverseRow:
    """Raw YAML row reduced to fields the scanner uses."""

    ticker: str
    name: str
    sector: str
    mkt_cap_target_usd: float
    niche_bottleneck: str
    inflection_signal: str | None


def _load_universe(path: str = UNIVERSE_PATH) -> list[_UniverseRow]:
    """Read the YAML universe and flatten across all configured sector buckets."""
    p = Path(path)
    if not p.exists():
        logger.warning("smallcap universe not found at %s", path)
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    rows: list[_UniverseRow] = []
    for sector, entries in (data.get("universe") or {}).items():
        for e in entries:
            rows.append(_UniverseRow(
                ticker=str(e["ticker"]).upper(),
                name=str(e.get("name", e["ticker"])),
                sector=sector,
                mkt_cap_target_usd=float(e.get("mkt_cap_target_usd") or 0),
                niche_bottleneck=str(e.get("niche_bottleneck", "")),
                inflection_signal=e.get("inflection_signal"),
            ))
    return rows


def _mkt_cap_score(market_cap_usd: float | None) -> float:
    """Smaller cap -> higher score. Curve favors $200M-$2B sweet spot.

    < $500M: 1.0  (tiny -- highest reward, highest risk)
    $500M-$2B: 0.85
    $2B-$5B: 0.65
    $5B-$15B: 0.40
    > $15B: 0.15  (already too big to "explode 20x")
    None / 0: 0.30 (uncertain -- middling)
    """
    if not market_cap_usd or market_cap_usd <= 0:
        return 0.30
    cap = market_cap_usd / 1e9  # billions
    if cap < 0.5:
        return 1.0
    if cap < 2.0:
        return 0.85
    if cap < 5.0:
        return 0.65
    if cap < 15.0:
        return 0.40
    return 0.15


def _revenue_inflection_score(latest_qoq: float | None, prior_4q_mean: float | None) -> float:
    """Score = sigmoid of (latest_qoq - prior_4q_mean) / 0.30.

    A 30% acceleration above the trailing-4Q baseline scores 0.73; a 60%
    acceleration scores 0.88. Negative inflection (deceleration) scores
    below 0.5. Returns 0.30 when we have no growth data.
    """
    if latest_qoq is None or prior_4q_mean is None:
        return 0.30
    delta = latest_qoq - prior_4q_mean
    return 1.0 / (1.0 + math.exp(-delta / 0.30))


def _news_sparsity_score(news_count_90d: int) -> float:
    """Inverse of mention frequency -- the LESS noticed the name, the higher.

    0 mentions: 1.0 (hidden gem)
    1-3 mentions: 0.85
    4-10 mentions: 0.65
    11-25 mentions: 0.40
    > 25 mentions: 0.15 (already broadly covered = no edge)
    """
    if news_count_90d <= 0:
        return 1.0
    if news_count_90d <= 3:
        return 0.85
    if news_count_90d <= 10:
        return 0.65
    if news_count_90d <= 25:
        return 0.40
    return 0.15


def _composite_score(mkt: float, rev: float, news: float) -> float:
    """Weighted composite: 40% mkt cap, 40% revenue inflection, 20% news sparsity."""
    return 0.40 * mkt + 0.40 * rev + 0.20 * news


def _flag_reason(mkt_score: float, rev_score: float, news_score: float) -> str:
    """Human-readable annotation of why the ticker scored where it did."""
    parts: list[str] = []
    if mkt_score >= 0.85:
        parts.append("micro/small-cap")
    if rev_score >= 0.70:
        parts.append("revenue acceleration")
    if news_score >= 0.85:
        parts.append("hidden (low news)")
    elif news_score <= 0.40:
        parts.append("WIDELY covered")
    return ", ".join(parts) or "baseline"


def _news_count_for_ticker(conn: sqlite3.Connection, ticker: str, days: int = NEWS_LOOKBACK_DAYS) -> int:
    """Count news rows mentioning this ticker in the last N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM news WHERE ticker = ? AND ts >= ?",
        (ticker.upper(), cutoff),
    ).fetchone()
    return int(row[0]) if row else 0


def _yfinance_market_cap_and_rev(ticker: str) -> tuple[float | None, float | None, float | None]:
    """Pull market cap + latest QoQ rev growth + trailing 4Q mean.

    Returns (market_cap_usd, latest_qoq_growth, prior_4q_mean_growth).
    All values can be None if yfinance lacks the data.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}
        mkt_cap = info.get("marketCap")
        # Quarterly revenue history -- compute YoY changes
        q_rev = None
        try:
            df = t.quarterly_income_stmt
            if df is not None and "Total Revenue" in df.index:
                rev_series = df.loc["Total Revenue"].dropna()
                if len(rev_series) >= 5:
                    rev_list = rev_series.tolist()
                    # rev_list is most-recent-first
                    growths = []
                    for i in range(min(5, len(rev_list) - 1)):
                        if rev_list[i + 1]:
                            growths.append((rev_list[i] - rev_list[i + 1]) / abs(rev_list[i + 1]))
                    if growths:
                        latest_qoq = growths[0]
                        prior_4q_mean = sum(growths[1:5]) / max(1, len(growths[1:5]))
                        return float(mkt_cap) if mkt_cap else None, latest_qoq, prior_4q_mean
        except Exception:
            logger.debug("rev parse failed for %s", ticker, exc_info=True)
        return float(mkt_cap) if mkt_cap else None, q_rev, None
    except Exception:
        logger.debug("yfinance lookup failed for %s", ticker, exc_info=True)
        return None, None, None


def score_one(
    row: _UniverseRow, *,
    market_cap_usd: float | None,
    latest_qoq: float | None,
    prior_4q_mean: float | None,
    news_count_90d: int,
) -> SmallCapCandidate:
    """Compute the composite score + return a SmallCapCandidate row."""
    mkt = _mkt_cap_score(market_cap_usd)
    rev = _revenue_inflection_score(latest_qoq, prior_4q_mean)
    news = _news_sparsity_score(news_count_90d)
    score = _composite_score(mkt, rev, news)
    reason = _flag_reason(mkt, rev, news)

    inflection = (latest_qoq - prior_4q_mean) if (latest_qoq is not None and prior_4q_mean is not None) else None

    return SmallCapCandidate(
        ticker=row.ticker, sector=row.sector, name=row.name,
        market_cap_usd=market_cap_usd, revenue_inflection=inflection,
        news_sparsity_score=news, score=score,
        niche_bottleneck=row.niche_bottleneck,
        inflection_signal=row.inflection_signal,
        flag_reason=reason,
    )


def scan_universe(
    conn: sqlite3.Connection, *,
    universe: list[_UniverseRow] | None = None,
    market_data_provider=None,
) -> list[SmallCapCandidate]:
    """Walk the universe, score each ticker, return the list.

    market_data_provider is a callable taking (ticker) -> (mkt_cap, qoq, 4q_mean);
    defaults to _yfinance_market_cap_and_rev. Tests inject a stub.
    """
    rows = universe if universe is not None else _load_universe()
    provider = market_data_provider or _yfinance_market_cap_and_rev
    candidates: list[SmallCapCandidate] = []
    for row in rows:
        try:
            mkt_cap, latest_qoq, prior_4q_mean = provider(row.ticker)
        except Exception:  # noqa: BLE001 -- per-ticker isolation
            logger.debug("provider failed for %s", row.ticker, exc_info=True)
            mkt_cap, latest_qoq, prior_4q_mean = None, None, None
        news_count = _news_count_for_ticker(conn, row.ticker)
        cand = score_one(
            row,
            market_cap_usd=mkt_cap,
            latest_qoq=latest_qoq,
            prior_4q_mean=prior_4q_mean,
            news_count_90d=news_count,
        )
        candidates.append(cand)
    return candidates


def persist(conn: sqlite3.Connection, candidates: list[SmallCapCandidate]) -> int:
    """Insert candidates above MIN_SCORE_TO_PERSIST; UNIQUE keeps intra-day dedup."""
    if not candidates:
        return 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inserted = 0
    for c in candidates:
        if c.score < MIN_SCORE_TO_PERSIST:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO smallcap_candidates"
            " (ticker, sector, market_cap_usd, revenue_inflection,"
            " news_sparsity_score, score, niche_bottleneck, inflection_signal,"
            " flag_reason, detected_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                c.ticker, c.sector, c.market_cap_usd, c.revenue_inflection,
                c.news_sparsity_score, c.score, c.niche_bottleneck,
                c.inflection_signal, c.flag_reason, now,
            ),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


def top_per_sector(
    conn: sqlite3.Connection, *, days: int = 1, top_n: int = TOP_PER_SECTOR,
) -> dict[str, list[dict]]:
    """Return {sector: [top-N rows]} from the last `days` days."""
    rows = conn.execute(
        "SELECT ticker, sector, market_cap_usd, revenue_inflection,"
        " news_sparsity_score, score, niche_bottleneck, inflection_signal,"
        " flag_reason, detected_at"
        " FROM smallcap_candidates"
        " WHERE detected_at >= datetime('now', ?)"
        " ORDER BY sector, score DESC",
        (f"-{int(days)} days",),
    ).fetchall()
    by_sector: dict[str, list[dict]] = {}
    keys = [
        "ticker", "sector", "market_cap_usd", "revenue_inflection",
        "news_sparsity_score", "score", "niche_bottleneck",
        "inflection_signal", "flag_reason", "detected_at",
    ]
    for r in rows:
        d = dict(zip(keys, r))
        by_sector.setdefault(d["sector"], []).append(d)
    return {s: lst[:top_n] for s, lst in by_sector.items()}


def format_smallcap_block(conn: sqlite3.Connection, *, days: int = 2) -> str:
    """Render the markdown block for the daily research prompt.

    Empty-string fallback when no candidates so the prompt section can be
    suppressed gracefully.
    """
    by_sector = top_per_sector(conn, days=days, top_n=TOP_PER_SECTOR)
    if not by_sector:
        return ""
    sector_titles = {
        "ai_biology_smallcap": "AI biology / AI-bio platforms",
        "space_tech_smallcap": "Space tech / Space infrastructure",
        "ai_semis_smallcap": "AI semis / 半导体小盘",
        "biopharma_smallcap": "生物制药 / Biopharma",
        "ai_dc_energy_smallcap": "AI DC 能源 / Energy for AI infra",
    }
    lines: list[str] = []
    for sector_key, rows in by_sector.items():
        if not rows:
            continue
        title = sector_titles.get(sector_key, sector_key)
        lines.append(f"### {title}")
        lines.append("")
        lines.append("| Ticker | Mkt Cap | Score | Inflection | News? | Niche bottleneck |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in rows:
            cap = f"${(r['market_cap_usd'] or 0)/1e9:.1f}B" if r["market_cap_usd"] else "?"
            inflect = (
                f"{(r['revenue_inflection'] or 0) * 100:+.0f}pp"
                if r["revenue_inflection"] is not None else "-"
            )
            news_tag = (
                "hidden" if (r["news_sparsity_score"] or 0) >= 0.85
                else "covered" if (r["news_sparsity_score"] or 0) <= 0.40
                else "moderate"
            )
            lines.append(
                f"| {r['ticker']} | {cap} | {r['score']:.2f} | "
                f"{inflect} | {news_tag} | {r['niche_bottleneck'][:80]} |"
            )
        lines.append("")
    return "\n".join(lines)
