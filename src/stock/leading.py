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
FWP_WEIGHTS: dict[str, float] = {
    "ocis": 0.40,           # opportunistic-cluster insider
    "novelty": 0.20,        # 8-K novelty
    "short_decline": 0.15,  # placeholder (FINRA integration F19.5)
    "reddit": 0.15,         # ApeWisdom acceleration
    "supplier_chain": 0.10, # placeholder (LLM-driven, F19.5)
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
) -> CandidateScore:
    """Combine the leading signals into a single 0..1 future-winner score.

    population_means/stdevs let the caller normalize against the universe; if
    omitted, we fall back to fixed reference scales so a single-ticker call
    still returns a sensible number.
    """
    insider = compute_insider_acceleration(ticker, conn)
    novelty = compute_8k_novelty(ticker, conn)
    qap = compute_quiet_accumulation(ticker, conn)
    reddit = compute_reddit_acceleration(ticker, snapshot=apewisdom_snapshot)

    # Fixed reference scales when no population data: tuned from a few hundred
    # historical examples in the lit -- conservative defaults that won't
    # dominate the score on their own.
    means = population_means or {
        "ocis": 0.0, "novelty": 0.5, "short_decline": 0.0,
        "reddit": 0.0, "supplier_chain": 0.0,
    }
    stdevs = population_stdevs or {
        "ocis": 5.0, "novelty": 0.25, "short_decline": 0.05,
        "reddit": 1.0, "supplier_chain": 1.0,
    }

    z_ocis = _safe_z(insider.raw_score, means["ocis"], stdevs["ocis"])
    z_nov = _safe_z(novelty.novelty_score, means["novelty"], stdevs["novelty"])
    z_red = _safe_z(reddit.acceleration, means["reddit"], stdevs["reddit"])
    z_short = 0.0     # placeholder until FINRA integration
    z_supply = 0.0    # placeholder until LLM-driven supplier-chain

    logit = (
        FWP_WEIGHTS["ocis"] * z_ocis
        + FWP_WEIGHTS["novelty"] * z_nov
        + FWP_WEIGHTS["short_decline"] * z_short
        + FWP_WEIGHTS["reddit"] * z_red
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
    }

    return CandidateScore(
        ticker=ticker,
        fwp=fwp,
        fwp_pre_gate=fwp_pre,
        qap_gate=qap.qap_gate,
        components=components,
        score_at=datetime.now(timezone.utc).isoformat(),
    )
