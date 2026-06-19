"""stock.chart_pattern -- candlestick/shape ("画像") similarity factor (#7).

The Amber tool scores a name partly by how much its recent chart SHAPE resembles
historical setups that preceded a strong move ("形态/画像" matching). This is a
v1: we describe the last N daily bars as a normalized shape vector and score how
closely it matches a momentum-breakout template (steady rise, accelerating,
closing near the window high, contained pullbacks).

It is deliberately deterministic and bounded [0,1] so it can be (a) used as a
ranking factor and (b) validated by the same ablation harness as every other
signal -- we keep it only if WITH-vs-WITHOUT shows it adds hit rate. No
overfit template library is claimed; the template is an explicit, inspectable
prior that strategy_search can re-weight or drop.
"""
from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

WINDOW: int = 20  # daily bars used to describe the shape


def _recent_closes(conn: sqlite3.Connection, ticker: str, n: int) -> list[float]:
    rows = conn.execute(
        "SELECT c FROM prices WHERE ticker = ? AND c > 0 ORDER BY ts DESC LIMIT ?",
        (ticker.upper(), n),
    ).fetchall()
    closes = [float(r[0]) for r in rows][::-1]  # chronological
    return closes


def _normalize(closes: list[float]) -> list[float]:
    """Scale to [0,1] over the window so only the SHAPE matters, not the level."""
    lo, hi = min(closes), max(closes)
    if hi <= lo:
        return [0.5] * len(closes)
    return [(c - lo) / (hi - lo) for c in closes]


def chart_pattern_score(conn: sqlite3.Connection, ticker: str, *, window: int = WINDOW) -> float:
    """Momentum-breakout shape score in [0,1]. 0.5 == neutral / insufficient data.

    Combines four shape traits, each in [0,1]:
      trend     -- fraction of up-days (monotone rise)
      position  -- where the last close sits in the window range (near highs)
      accel     -- recent half steeper than the earlier half
      tightness -- shallow pullbacks (low downside volatility), 1 == very tight
    """
    closes = _recent_closes(conn, ticker, window)
    if len(closes) < max(8, window // 2):
        return 0.5  # not enough history to judge a shape

    norm = _normalize(closes)
    diffs = [b - a for a, b in zip(norm, norm[1:])]

    up_days = sum(1 for d in diffs if d > 0)
    trend = up_days / len(diffs)

    position = norm[-1]  # already 0..1 within the window range

    half = len(norm) // 2
    early_slope = (norm[half] - norm[0]) / max(half, 1)
    late_slope = (norm[-1] - norm[half]) / max(len(norm) - 1 - half, 1)
    # accel in [0,1]: 0.5 == equal slopes, >0.5 == late half steeper
    accel = max(0.0, min(1.0, 0.5 + (late_slope - early_slope)))

    downs = [d for d in diffs if d < 0]
    avg_drawdown = (sum(-d for d in downs) / len(downs)) if downs else 0.0
    tightness = max(0.0, 1.0 - avg_drawdown * 4.0)  # scale: ~25% avg down-step -> 0

    score = 0.35 * trend + 0.30 * position + 0.20 * accel + 0.15 * tightness
    return round(max(0.0, min(1.0, score)), 4)


def attach_chart_pattern(
    conn: sqlite3.Connection, rows: list[dict], *, window: int = WINDOW,
) -> list[dict]:
    """Add a 'chart_pattern' key to each prediction row (for ranking/strategies)."""
    for r in rows:
        r["chart_pattern"] = chart_pattern_score(conn, r["ticker"], window=window)
    return rows
