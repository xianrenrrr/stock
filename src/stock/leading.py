"""stock.leading -- leading-indicator signals for forward-looking equity discovery.

F19: catch the next 10x BEFORE it explodes, not after. Boss complaint: by the
time we report on a 20x mover the alpha is gone. This module computes signals
that historically predate breakouts:

- Opportunistic-cluster insider buying  (Cohen-Malloy-Pomorski 2012, Alldredge 2019)
- 8-K novelty                            (PEAD.txt, JFQA)
- Quiet accumulation pattern             (Wyckoff-lite)
- Reddit / WSB mention acceleration      (ApeWisdom delta -- best-effort, free tier)
- Short-interest decline                 (FINRA -- placeholder; integrated in F19.5)

Every helper is BEST-EFFORT: missing input data returns a neutral score (0.0)
rather than raising, so the discovery engine can run on partial coverage. See
docs/research_notes/2026-05-03_forward_discovery_papers.md for the citation map.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

INSIDER_LOOKBACK_DAYS: int = 30
INSIDER_CLUSTER_WINDOW_DAYS: int = 10
INSIDER_CLUSTER_MIN: int = 3
OPPORTUNISTIC_STDEV_THRESHOLD_DAYS: float = 60.0  # >60d stdev between buys = opportunistic
EIGHT_K_LOOKBACK_DAYS: int = 7
EIGHT_K_BASELINE_COUNT: int = 4  # cosine-distance vs last N filings
QAP_BASE_DAYS: int = 60
QAP_BASELINE_DAYS: int = 180
QAP_MAX_RANGE_OVER_ATR: float = 1.5
QAP_MAX_VOL_RATIO: float = 0.7

APEWISDOM_URL: str = "https://apewisdom.io/api/v1.0/filter/all-stocks"
APEWISDOM_TIMEOUT: float = 8.0

# F21: technical-leadership signals via free APIs
HN_ALGOLIA_URL: str = "https://hn.algolia.com/api/v1/search_by_date"
HN_TIMEOUT: float = 6.0
HN_MAX_HITS: int = 100  # Algolia's hard cap per page is 1000; we only need counts
ARXIV_TIMEOUT: float = 12.0
ARXIV_MAX_RESULTS: int = 50
THEME_LOOKBACK_DAYS: int = 30

# F23: PatentsView (USPTO) free API for patent-activity leading indicator.
# Patents granted in last 12 months vs prior 12 months = R&D pipeline acceleration.
PATENTSVIEW_URL: str = "https://search.patentsview.org/api/v1/patent/"
PATENTSVIEW_TIMEOUT: float = 12.0
PATENTSVIEW_MAX_PER_QUERY: int = 100
PATENT_LOOKBACK_DAYS: int = 365


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


class InsiderSignal(BaseModel):
    """Output of compute_insider_acceleration for one ticker."""

    ticker: str
    raw_score: float                # OCIS in dollars-log-units (0.0 if no buys)
    distinct_filers_30d: int
    cluster_size_max: int
    opportunistic_value_usd: float  # sum of opportunistic buy values in window
    routine_value_usd: float        # sum of routine buys (informational only)


class EightKNoveltySignal(BaseModel):
    """Output of compute_8k_novelty for one ticker."""

    ticker: str
    novelty_score: float            # 0..1, 1 = totally unlike prior filings
    most_recent_8k_ts: str | None
    baseline_count: int


class QAPSignal(BaseModel):
    """Output of compute_quiet_accumulation for one ticker."""

    ticker: str
    qap_gate: bool
    range_over_atr: float | None
    volume_ratio: float | None
    bars_used: int


class RedditSignal(BaseModel):
    """ApeWisdom mention-count delta signal."""

    ticker: str
    mentions_24h: int
    mentions_24h_prior: int
    acceleration: float             # (now - prior) / max(1, prior)


class PatentActivitySignal(BaseModel):
    """USPTO patent-grant count delta as a leading R&D-pipeline signal."""

    ticker: str
    patents_12m: int
    patents_prior_12m: int
    acceleration: float  # (now - prior) / max(1, prior)


class ThemeVelocitySignal(BaseModel):
    """Technical-leadership mention velocity from HN + arXiv (free APIs).

    HN: developer / VC / hacker mindshare. Spike often pre-dates retail / news.
    arXiv: academic mention. Spike pre-dates HN by 6-18 months for AI/QC names.
    Acceleration = (last_30d - prior_30d) / max(1, prior_30d).
    """

    ticker: str
    hn_30d: int
    hn_30d_prior: int
    arxiv_30d: int
    arxiv_30d_prior: int
    hn_acceleration: float
    arxiv_acceleration: float
    composite: float                # weighted blend used by FWP


# ---------------------------------------------------------------------------
# Insider acceleration
# ---------------------------------------------------------------------------


def _filer_is_opportunistic(
    conn: sqlite3.Connection, filer_name: str
) -> bool:
    """Heuristic: filer is opportunistic if their buy intervals are irregular.

    Routine filers buy on a predictable cadence (quarterly grant exercises,
    monthly auto-purchases). Opportunistic filers buy at irregular times that
    correlate with private information. We approximate "irregular" as:
    stdev(days_between_buys) > OPPORTUNISTIC_STDEV_THRESHOLD_DAYS over the
    last 3 years of the filer's history.

    No data -> return True (treat unknown filer as potentially informative,
    since CMP show opportunistic-only is the alpha-bearing slice).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3 * 365)).isoformat()
    rows = conn.execute(
        "SELECT filed_at FROM insider_filings"
        " WHERE filer_name = ? AND filed_at >= ?"
        " AND COALESCE(transaction_type, '') IN ('P', 'P-Purchase', 'purchase', 'BUY')"
        " ORDER BY filed_at ASC",
        (filer_name, cutoff),
    ).fetchall()
    if len(rows) < 3:
        return True

    # Compute pairwise gap days between consecutive purchases
    dates: list[datetime] = []
    for (ts,) in rows:
        try:
            dates.append(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
        except (ValueError, TypeError):
            continue
    if len(dates) < 3:
        return True
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    if not gaps:
        return True
    mean = sum(gaps) / len(gaps)
    var = sum((g - mean) ** 2 for g in gaps) / len(gaps)
    stdev = math.sqrt(var)
    return stdev > OPPORTUNISTIC_STDEV_THRESHOLD_DAYS


def compute_insider_acceleration(
    ticker: str, conn: sqlite3.Connection
) -> InsiderSignal:
    """Compute the OCIS (Opportunistic-Cluster Insider Score) for a ticker."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=INSIDER_LOOKBACK_DAYS)
    ).isoformat()

    rows = conn.execute(
        "SELECT filer_name, filed_at, COALESCE(shares, 0), COALESCE(price, 0),"
        " COALESCE(transaction_type, '')"
        " FROM insider_filings WHERE ticker = ? AND filed_at >= ?"
        " ORDER BY filed_at ASC",
        (ticker, cutoff),
    ).fetchall()

    if not rows:
        return InsiderSignal(
            ticker=ticker, raw_score=0.0, distinct_filers_30d=0,
            cluster_size_max=0, opportunistic_value_usd=0.0,
            routine_value_usd=0.0,
        )

    # Filter to PURCHASES only -- a sale is the opposite signal
    purchases: list[tuple[str, datetime, float]] = []
    for filer, ts, shares, price, txn_type in rows:
        if (txn_type or "").upper() not in ("P", "P-PURCHASE", "PURCHASE", "BUY"):
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        value = float(shares) * float(price) if shares and price else 0.0
        purchases.append((str(filer), dt, value))

    if not purchases:
        return InsiderSignal(
            ticker=ticker, raw_score=0.0, distinct_filers_30d=0,
            cluster_size_max=0, opportunistic_value_usd=0.0,
            routine_value_usd=0.0,
        )

    # Cluster size: max number of distinct filers in any 10-day window
    purchases_sorted = sorted(purchases, key=lambda r: r[1])
    cluster_max = 0
    n = len(purchases_sorted)
    for i in range(n):
        window_end = purchases_sorted[i][1] + timedelta(days=INSIDER_CLUSTER_WINDOW_DAYS)
        filers_in_window: set[str] = set()
        for j in range(i, n):
            if purchases_sorted[j][1] > window_end:
                break
            filers_in_window.add(purchases_sorted[j][0])
        cluster_max = max(cluster_max, len(filers_in_window))

    cluster_multiplier = 1.0 + 0.5 * max(0, cluster_max - 1)

    opportunistic_value = 0.0
    routine_value = 0.0
    raw_score = 0.0
    for filer, _dt, value in purchases:
        is_opp = _filer_is_opportunistic(conn, filer)
        if is_opp:
            opportunistic_value += value
            raw_score += math.log1p(value) * cluster_multiplier
        else:
            routine_value += value

    distinct = len({p[0] for p in purchases})
    return InsiderSignal(
        ticker=ticker,
        raw_score=raw_score,
        distinct_filers_30d=distinct,
        cluster_size_max=cluster_max,
        opportunistic_value_usd=opportunistic_value,
        routine_value_usd=routine_value,
    )


# ---------------------------------------------------------------------------
# 8-K novelty
# ---------------------------------------------------------------------------


def _bag_of_words(text: str) -> dict[str, int]:
    """Lowercase whitespace-tokenized bag of words; coarse but cheap."""
    bag: dict[str, int] = {}
    for token in text.lower().split():
        cleaned = "".join(c for c in token if c.isalnum())
        if not cleaned or len(cleaned) < 3:
            continue
        bag[cleaned] = bag.get(cleaned, 0) + 1
    return bag


def _cosine(a: dict[str, int], b: dict[str, int]) -> float:
    """Cosine similarity between two bag-of-words dicts. 0 if either is empty."""
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_8k_novelty(ticker: str, conn: sqlite3.Connection) -> EightKNoveltySignal:
    """Score how unlike its predecessors the most recent 8-K-style news item is.

    PEAD.txt: text features beyond surprise add alpha. We approximate the idea
    by comparing the firm's most recent SEC-source news (or 8-K item-tagged
    news) against the firm's previous N filings using bag-of-words cosine.
    Novelty = 1 - max_cosine. High novelty + positive sentiment is a leading
    signal we surface to the LLM.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=EIGHT_K_LOOKBACK_DAYS)).isoformat()
    recent = conn.execute(
        "SELECT title, body, ts FROM news"
        " WHERE ticker = ? AND ts >= ?"
        " AND (lower(source) LIKE '%sec%' OR lower(source) LIKE '%8-k%'"
        "      OR lower(source) LIKE '%8k%' OR lower(source) LIKE '%edgar%')"
        " ORDER BY ts DESC LIMIT 1",
        (ticker, cutoff),
    ).fetchone()

    if not recent:
        # Fall back to any recent news -- still informative for a novelty proxy
        recent = conn.execute(
            "SELECT title, body, ts FROM news WHERE ticker = ? AND ts >= ?"
            " ORDER BY ts DESC LIMIT 1",
            (ticker, cutoff),
        ).fetchone()

    if not recent:
        return EightKNoveltySignal(
            ticker=ticker, novelty_score=0.0, most_recent_8k_ts=None, baseline_count=0,
        )

    recent_title, recent_body, recent_ts = recent
    recent_bag = _bag_of_words(f"{recent_title or ''} {recent_body or ''}")

    baseline_rows = conn.execute(
        "SELECT title, body FROM news WHERE ticker = ? AND ts < ?"
        " ORDER BY ts DESC LIMIT ?",
        (ticker, recent_ts, EIGHT_K_BASELINE_COUNT),
    ).fetchall()

    if not baseline_rows:
        # No baseline = treat as moderately novel rather than 1.0 (avoid spam)
        return EightKNoveltySignal(
            ticker=ticker, novelty_score=0.5,
            most_recent_8k_ts=str(recent_ts), baseline_count=0,
        )

    max_sim = 0.0
    for title, body in baseline_rows:
        baseline_bag = _bag_of_words(f"{title or ''} {body or ''}")
        sim = _cosine(recent_bag, baseline_bag)
        if sim > max_sim:
            max_sim = sim

    novelty = max(0.0, min(1.0, 1.0 - max_sim))
    return EightKNoveltySignal(
        ticker=ticker, novelty_score=novelty,
        most_recent_8k_ts=str(recent_ts), baseline_count=len(baseline_rows),
    )


# ---------------------------------------------------------------------------
# Quiet accumulation pattern (Wyckoff-lite gate)
# ---------------------------------------------------------------------------


def compute_quiet_accumulation(
    ticker: str, conn: sqlite3.Connection
) -> QAPSignal:
    """Wyckoff-lite gate: tight base + dried-up volume = quiet accumulation.

    The gate fires when:
      (a) range / ATR over last 60 trading days < QAP_MAX_RANGE_OVER_ATR
      (b) avg volume last 60d / avg volume prior 180d < QAP_MAX_VOL_RATIO

    We don't compute OBV slope here (would require intraday data we don't have
    for A-shares); the two-component gate is the conservative version. False
    negatives are OK -- this is a precision filter.
    """
    rows = conn.execute(
        "SELECT ts, h, l, c, v FROM prices WHERE ticker = ?"
        " ORDER BY ts DESC LIMIT ?",
        (ticker, QAP_BASE_DAYS + QAP_BASELINE_DAYS),
    ).fetchall()

    if len(rows) < QAP_BASE_DAYS + 30:
        return QAPSignal(
            ticker=ticker, qap_gate=False,
            range_over_atr=None, volume_ratio=None, bars_used=len(rows),
        )

    rows = list(reversed(rows))  # oldest first
    base = rows[-QAP_BASE_DAYS:]
    prior = rows[:-QAP_BASE_DAYS][-QAP_BASELINE_DAYS:]

    # Range over ATR
    highs = [float(r[1]) for r in base]
    lows = [float(r[2]) for r in base]
    closes = [float(r[3]) for r in base]
    span = max(highs) - min(lows)
    # ATR = mean true range (simplified: high-low only since we don't have prev_close handy)
    atr = sum(h - l for h, l in zip(highs, lows)) / len(highs)
    if atr <= 0:
        return QAPSignal(
            ticker=ticker, qap_gate=False, range_over_atr=None,
            volume_ratio=None, bars_used=len(rows),
        )
    range_over_atr = span / atr

    # Volume ratio
    base_vol = sum(int(r[4]) for r in base) / len(base)
    if not prior:
        return QAPSignal(
            ticker=ticker, qap_gate=False, range_over_atr=range_over_atr,
            volume_ratio=None, bars_used=len(rows),
        )
    prior_vol = sum(int(r[4]) for r in prior) / len(prior)
    if prior_vol <= 0:
        return QAPSignal(
            ticker=ticker, qap_gate=False, range_over_atr=range_over_atr,
            volume_ratio=None, bars_used=len(rows),
        )
    vol_ratio = base_vol / prior_vol

    gate = (
        range_over_atr < QAP_MAX_RANGE_OVER_ATR
        and vol_ratio < QAP_MAX_VOL_RATIO
    )
    return QAPSignal(
        ticker=ticker, qap_gate=gate,
        range_over_atr=range_over_atr, volume_ratio=vol_ratio,
        bars_used=len(rows),
    )


# ---------------------------------------------------------------------------
# Reddit / WSB mention acceleration via ApeWisdom (free, no key)
# ---------------------------------------------------------------------------


def fetch_apewisdom_snapshot() -> dict[str, dict[str, int]]:
    """One HTTP call returns the top ~50 mentions across all-stocks; cache the result.

    Caller should hold this snapshot in memory and pass it to
    compute_reddit_acceleration for each ticker -- avoids hammering ApeWisdom
    once per ticker.
    """
    try:
        resp = httpx.get(APEWISDOM_URL, timeout=APEWISDOM_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        logger.warning("ApeWisdom snapshot failed; returning empty dict")
        return {}

    out: dict[str, dict[str, int]] = {}
    for row in payload.get("results", []) or []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker", "")).upper()
        if not ticker:
            continue
        try:
            out[ticker] = {
                "mentions": int(row.get("mentions", 0) or 0),
                "mentions_24h_ago": int(row.get("mentions_24h_ago", 0) or 0),
            }
        except (ValueError, TypeError):
            continue
    return out


def compute_reddit_acceleration(
    ticker: str, snapshot: dict[str, dict[str, int]] | None = None,
) -> RedditSignal:
    """Compute mention acceleration vs 24h ago using a pre-fetched snapshot.

    Snapshot can be None for tests or one-off runs; we'll fetch fresh.
    Acceleration = (mentions_now - mentions_prior) / max(1, mentions_prior).
    A 5x acceleration is the rough WSB-momentum threshold.
    """
    if snapshot is None:
        snapshot = fetch_apewisdom_snapshot()
    row = snapshot.get(ticker.upper(), {})
    now = int(row.get("mentions", 0))
    prior = int(row.get("mentions_24h_ago", 0))
    accel = (now - prior) / max(1, prior)
    return RedditSignal(
        ticker=ticker,
        mentions_24h=now,
        mentions_24h_prior=prior,
        acceleration=accel,
    )


# ---------------------------------------------------------------------------
# Theme velocity (HN + arXiv mention acceleration)
# ---------------------------------------------------------------------------


def _hn_count_for_window(query: str, *, since_unix: int, until_unix: int) -> int:
    """Count HN stories matching `query` between two unix timestamps.

    Algolia's `numericFilters` supports `created_at_i>=...` etc. We only need
    the total hits count (`nbHits`) so we ask for hitsPerPage=1 to keep the
    payload tiny. Best-effort: HTTP failure -> 0 (caller gets a flat signal,
    not an exception).
    """
    if not query.strip():
        return 0
    params = {
        "query": query,
        "hitsPerPage": 1,
        "numericFilters": f"created_at_i>={since_unix},created_at_i<{until_unix}",
        "tags": "story",
    }
    try:
        resp = httpx.get(HN_ALGOLIA_URL, params=params, timeout=HN_TIMEOUT)
        resp.raise_for_status()
        return int(resp.json().get("nbHits", 0) or 0)
    except Exception:
        logger.debug("HN search failed for %r", query, exc_info=True)
        return 0


def _arxiv_count_for_window(query: str, *, since_iso: str, until_iso: str) -> int:
    """Count arXiv submissions whose abstract / title mentions `query` in the window.

    Uses the bundled `arxiv` library. arXiv's API doesn't filter by date in
    the query syntax we need, so we paginate by submittedDate descending and
    stop counting once we cross the lower bound.
    """
    if not query.strip():
        return 0
    try:
        import arxiv

        search = arxiv.Search(
            query=query,
            max_results=ARXIV_MAX_RESULTS,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        until_dt = datetime.fromisoformat(until_iso.replace("Z", "+00:00"))
        since_dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
        count = 0
        for result in search.results():
            submitted = getattr(result, "published", None) or getattr(
                result, "updated", None
            )
            if submitted is None:
                continue
            if submitted.tzinfo is None:
                submitted = submitted.replace(tzinfo=timezone.utc)
            if submitted < since_dt:
                break  # results are descending; we've passed the window
            if submitted >= until_dt:
                continue
            count += 1
        return count
    except Exception:
        logger.debug("arXiv search failed for %r", query, exc_info=True)
        return 0


def compute_theme_velocity(
    ticker: str,
    *,
    company_name: str | None = None,
    extra_keywords: list[str] | None = None,
) -> ThemeVelocitySignal:
    """Compute mention-count acceleration on HN + arXiv for a ticker / company / themes.

    company_name is preferred for HN (people don't write "NVDA" they write
    "Nvidia"); extra_keywords lets the discovery engine pass theme tags from
    the supply-chain map (e.g. ["liquid cooling", "PAM4"]) so the signal
    isn't just about the ticker symbol.
    """
    now = datetime.now(timezone.utc)
    win_start = now - timedelta(days=THEME_LOOKBACK_DAYS)
    prior_start = now - timedelta(days=THEME_LOOKBACK_DAYS * 2)

    now_unix = int(now.timestamp())
    win_start_unix = int(win_start.timestamp())
    prior_start_unix = int(prior_start.timestamp())

    # Build search query: prefer company name, fall back to ticker, blend extras
    queries: list[str] = []
    if company_name and company_name.strip():
        queries.append(company_name.strip())
    queries.append(ticker.strip())
    for kw in extra_keywords or []:
        if kw and kw.strip():
            queries.append(kw.strip())

    # HN counts -- one query each, summed
    hn_30d = sum(
        _hn_count_for_window(q, since_unix=win_start_unix, until_unix=now_unix)
        for q in queries
    )
    hn_30d_prior = sum(
        _hn_count_for_window(q, since_unix=prior_start_unix, until_unix=win_start_unix)
        for q in queries
    )

    # arXiv counts
    arxiv_30d = sum(
        _arxiv_count_for_window(
            q, since_iso=win_start.isoformat(), until_iso=now.isoformat(),
        )
        for q in queries
    )
    arxiv_30d_prior = sum(
        _arxiv_count_for_window(
            q,
            since_iso=prior_start.isoformat(),
            until_iso=win_start.isoformat(),
        )
        for q in queries
    )

    hn_accel = (hn_30d - hn_30d_prior) / max(1, hn_30d_prior)
    arxiv_accel = (arxiv_30d - arxiv_30d_prior) / max(1, arxiv_30d_prior)
    # Weight arXiv higher: academic spikes pre-date HN spikes, which pre-date news.
    composite = 0.35 * hn_accel + 0.65 * arxiv_accel

    return ThemeVelocitySignal(
        ticker=ticker,
        hn_30d=hn_30d, hn_30d_prior=hn_30d_prior,
        arxiv_30d=arxiv_30d, arxiv_30d_prior=arxiv_30d_prior,
        hn_acceleration=hn_accel, arxiv_acceleration=arxiv_accel,
        composite=composite,
    )


# ---------------------------------------------------------------------------
# Patent activity (USPTO PatentsView) -- R&D pipeline leading indicator
# ---------------------------------------------------------------------------


def _patentsview_count_for_window(
    company_query: str, *, since_iso: str, until_iso: str,
) -> int:
    """Count USPTO patent grants where assignee_organization matches in date window.

    Best-effort: API failure -> 0 (no exception). PatentsView is free and
    keyless but rate-limits to ~45 req/min so callers should batch.
    """
    if not company_query.strip():
        return 0
    payload = {
        "q": {
            "_and": [
                {"_text_phrase": {"assignees.assignee_organization": company_query}},
                {"_gte": {"patent_date": since_iso[:10]}},
                {"_lt": {"patent_date": until_iso[:10]}},
            ]
        },
        "f": ["patent_id"],
        "o": {"size": PATENTSVIEW_MAX_PER_QUERY},
    }
    try:
        resp = httpx.post(
            PATENTSVIEW_URL, json=payload, timeout=PATENTSVIEW_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        # PatentsView returns {error: false, count: int, total_hits: int, patents: [...]}
        return int(data.get("total_hits", 0) or data.get("count", 0) or 0)
    except Exception:
        logger.debug("PatentsView search failed for %r", company_query, exc_info=True)
        return 0


def compute_patent_activity(
    ticker: str, *, company_name: str | None = None,
) -> PatentActivitySignal:
    """Compute YoY patent-grant acceleration for a company.

    company_name is critical -- USPTO indexes by assignee_organization, not
    ticker. Discovery engine pulls names from the supply-chain map; tickers
    not in the map fall back to the bare ticker symbol (which usually returns 0).
    """
    query = (company_name or ticker).strip()
    now = datetime.now(timezone.utc)
    win_start = now - timedelta(days=PATENT_LOOKBACK_DAYS)
    prior_start = now - timedelta(days=PATENT_LOOKBACK_DAYS * 2)

    patents_12m = _patentsview_count_for_window(
        query, since_iso=win_start.isoformat(), until_iso=now.isoformat(),
    )
    patents_prior_12m = _patentsview_count_for_window(
        query, since_iso=prior_start.isoformat(), until_iso=win_start.isoformat(),
    )
    accel = (patents_12m - patents_prior_12m) / max(1, patents_prior_12m)
    return PatentActivitySignal(
        ticker=ticker,
        patents_12m=patents_12m,
        patents_prior_12m=patents_prior_12m,
        acceleration=accel,
    )


# ---------------------------------------------------------------------------
# Composite Future-Winner Probability score
# ---------------------------------------------------------------------------


def _safe_z(x: float, mean: float, stdev: float) -> float:
    """Clipped z-score: stdev<=0 -> 0; clipped to [-3, +3] to bound sigmoid input."""
    if stdev <= 0:
        return 0.0
    z = (x - mean) / stdev
    return max(-3.0, min(3.0, z))


def _sigmoid(x: float) -> float:
    """Numerically stable logistic."""
    if x >= 0:
        ex = math.exp(-x)
        return 1.0 / (1.0 + ex)
    ex = math.exp(x)
    return ex / (1.0 + ex)


# Composite weights -- documented in docs/research_notes/2026-05-03_forward_discovery_papers.md
# F23 update: 0.05 each freed from the short_decline + supplier_chain placeholders
# and reallocated to the new patent_activity signal (USPTO grant acceleration).
FWP_WEIGHTS: dict[str, float] = {
    "ocis": 0.30,           # opportunistic-cluster insider
    "novelty": 0.20,        # 8-K novelty
    "theme_velocity": 0.20, # F21: HN + arXiv mention acceleration
    "reddit": 0.15,         # ApeWisdom acceleration
    "patent_activity": 0.10,  # F23: USPTO patent-grant acceleration
    "short_decline": 0.025, # placeholder (FINRA integration F19.5)
    "supplier_chain": 0.025,# placeholder (LLM-driven, F19.5)
}


class CandidateScore(BaseModel):
    """Composite Future-Winner Probability for one ticker."""

    ticker: str
    fwp: float                       # 0..1, gated by qap
    fwp_pre_gate: float              # 0..1, before applying QAP gate
    qap_gate: bool
    components: dict[str, float]     # raw signal values used
    score_at: str


def compute_future_winner_probability(
    ticker: str,
    conn: sqlite3.Connection,
    *,
    apewisdom_snapshot: dict[str, dict[str, int]] | None = None,
    population_means: dict[str, float] | None = None,
    population_stdevs: dict[str, float] | None = None,
    theme_velocity: ThemeVelocitySignal | None = None,
    patent_activity: PatentActivitySignal | None = None,
    company_name: str | None = None,
    extra_keywords: list[str] | None = None,
    skip_theme_velocity: bool = False,
    skip_patent_activity: bool = False,
) -> CandidateScore:
    """Combine the leading signals into a single 0..1 future-winner score.

    population_means/stdevs let the caller normalize against the universe; if
    omitted, we fall back to fixed reference scales so a single-ticker call
    still returns a sensible number.

    F21: theme_velocity arg lets the caller compute HN+arXiv mentions in advance
    (e.g. discovery_engine batches them with rate-limit-aware sleeps). Pass
    `skip_theme_velocity=True` to omit the network call entirely (useful in
    tests + when running discovery on a large universe with limited time).
    """
    insider = compute_insider_acceleration(ticker, conn)
    novelty = compute_8k_novelty(ticker, conn)
    qap = compute_quiet_accumulation(ticker, conn)
    reddit = compute_reddit_acceleration(ticker, snapshot=apewisdom_snapshot)

    if theme_velocity is None and not skip_theme_velocity:
        try:
            theme_velocity = compute_theme_velocity(
                ticker, company_name=company_name, extra_keywords=extra_keywords,
            )
        except Exception:
            logger.debug("theme_velocity compute failed for %s", ticker)
            theme_velocity = None

    if patent_activity is None and not skip_patent_activity:
        try:
            patent_activity = compute_patent_activity(
                ticker, company_name=company_name,
            )
        except Exception:
            logger.debug("patent_activity compute failed for %s", ticker)
            patent_activity = None

    # Fixed reference scales when no population data: tuned from a few hundred
    # historical examples in the lit -- conservative defaults that won't
    # dominate the score on their own.
    means = population_means or {
        "ocis": 0.0, "novelty": 0.5, "short_decline": 0.0,
        "reddit": 0.0, "theme_velocity": 0.0, "supplier_chain": 0.0,
        "patent_activity": 0.0,
    }
    stdevs = population_stdevs or {
        "ocis": 5.0, "novelty": 0.25, "short_decline": 0.05,
        "reddit": 1.0, "theme_velocity": 1.0, "supplier_chain": 1.0,
        "patent_activity": 0.5,
    }

    z_ocis = _safe_z(insider.raw_score, means["ocis"], stdevs["ocis"])
    z_nov = _safe_z(novelty.novelty_score, means["novelty"], stdevs["novelty"])
    z_red = _safe_z(reddit.acceleration, means["reddit"], stdevs["reddit"])
    z_theme = (
        _safe_z(theme_velocity.composite, means["theme_velocity"],
                stdevs["theme_velocity"])
        if theme_velocity is not None else 0.0
    )
    z_patent = (
        _safe_z(patent_activity.acceleration, means["patent_activity"],
                stdevs["patent_activity"])
        if patent_activity is not None else 0.0
    )
    z_short = 0.0     # placeholder until FINRA integration
    z_supply = 0.0    # placeholder until LLM-driven supplier-chain

    logit = (
        FWP_WEIGHTS["ocis"] * z_ocis
        + FWP_WEIGHTS["novelty"] * z_nov
        + FWP_WEIGHTS["theme_velocity"] * z_theme
        + FWP_WEIGHTS["reddit"] * z_red
        + FWP_WEIGHTS["patent_activity"] * z_patent
        + FWP_WEIGHTS["short_decline"] * z_short
        + FWP_WEIGHTS["supplier_chain"] * z_supply
    )
    fwp_pre = _sigmoid(logit)
    fwp = fwp_pre if qap.qap_gate else fwp_pre * 0.5  # half-weight when gate fails

    components = {
        "ocis_raw": insider.raw_score,
        "ocis_z": z_ocis,
        "ocis_distinct_filers": float(insider.distinct_filers_30d),
        "ocis_cluster_max": float(insider.cluster_size_max),
        "ocis_opportunistic_usd": insider.opportunistic_value_usd,
        "novelty_raw": novelty.novelty_score,
        "novelty_z": z_nov,
        "qap_gate": 1.0 if qap.qap_gate else 0.0,
        "qap_range_over_atr": qap.range_over_atr or -1.0,
        "qap_volume_ratio": qap.volume_ratio or -1.0,
        "reddit_now": float(reddit.mentions_24h),
        "reddit_prior": float(reddit.mentions_24h_prior),
        "reddit_accel": reddit.acceleration,
        "reddit_z": z_red,
        "theme_hn_30d": float(theme_velocity.hn_30d) if theme_velocity else 0.0,
        "theme_arxiv_30d": float(theme_velocity.arxiv_30d) if theme_velocity else 0.0,
        "theme_hn_accel": theme_velocity.hn_acceleration if theme_velocity else 0.0,
        "theme_arxiv_accel": theme_velocity.arxiv_acceleration if theme_velocity else 0.0,
        "theme_composite": theme_velocity.composite if theme_velocity else 0.0,
        "theme_z": z_theme,
        "patent_12m": float(patent_activity.patents_12m) if patent_activity else 0.0,
        "patent_prior_12m": float(patent_activity.patents_prior_12m) if patent_activity else 0.0,
        "patent_accel": patent_activity.acceleration if patent_activity else 0.0,
        "patent_z": z_patent,
    }

    return CandidateScore(
        ticker=ticker,
        fwp=fwp,
        fwp_pre_gate=fwp_pre,
        qap_gate=qap.qap_gate,
        components=components,
        score_at=datetime.now(timezone.utc).isoformat(),
    )
