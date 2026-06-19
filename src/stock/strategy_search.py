"""stock.strategy_search -- the "Amber" strategy-generation agent (#5).

The Amber/Kelly tool's headline trick: an LLM invents NAMED factor strategies
(e.g. "AmberCarson-F031"), backtests each, and keeps only the ones that beat the
benchmark out-of-sample. We do the same on our own stack.

A strategy here is a transparent weighting over signals we already compute per
prediction -- prob_up, expected_return_bps, chart_pattern (画像), momentum --
plus a top_n and a mega-cap toggle. The LLM (Opus 4.8) proposes a slate of named
strategies; we backtest each over prediction history with realistic execution;
we KEEP a strategy only if it clears three gates:

  1. net excess over QQQ > 0,
  2. beats the prob_up-only baseline (must add value over what we already do),
  3. scored over >= MIN_PERIODS periods (not a small-sample fluke).

Kept strategies are persisted to strategy_runs. This is intentionally
conservative: like the ablation loop, we trust nothing that can't out-perform
the incumbent on real out-of-sample data.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from stock.chart_pattern import chart_pattern_score
from stock.models import ChatMessage, get_core_client, get_core_model, parse_llm_json
from stock.portfolio import (
    DEFAULT_BENCHMARK,
    Pick,
    _is_us,
    score_basket,
)
from stock.universe import is_megacap

logger = logging.getLogger(__name__)

MIN_PERIODS: int = 6          # don't trust a strategy scored on fewer periods
SIGNALS: tuple[str, ...] = ("prob_up", "expected_return_bps", "chart_pattern", "momentum")
STRATEGY_PROMPT = """You are Amber, a quant strategy designer. Propose {n} DISTINCT \
long-only ranking strategies for a weekly US-equity basket.

Each strategy ranks candidate stocks by a weighted blend of these per-stock signals \
(each pre-normalized to 0..1 within the day's cross-section):
- prob_up: model's probability the stock rises
- expected_return_bps: model's expected return
- chart_pattern: candlestick/shape momentum-breakout score (画像)
- momentum: trailing price momentum

Return STRICT JSON: a list of objects, each:
{{"name": "Amber-Fxxx", "rationale": "one line", "weights": {{"prob_up": w1, \
"expected_return_bps": w2, "chart_pattern": w3, "momentum": w4}}, "top_n": 5, \
"exclude_megacaps": true}}

Weights are non-negative and need not sum to 1 (we normalize). Make the slate \
diverse: some momentum-led, some pattern-led, some probability-led. Output ONLY the \
JSON list."""


class StrategyDef(BaseModel):
    name: str
    rationale: str = ""
    weights: dict[str, float] = Field(default_factory=dict)
    top_n: int = 5
    exclude_megacaps: bool = True


class StrategyScore(BaseModel):
    name: str
    definition: StrategyDef
    periods: int
    net_excess: float
    baseline_excess: float
    kept: bool
    reason: str


def _momentum(conn: sqlite3.Connection, ticker: str, lookback: int = 10) -> float:
    rows = conn.execute(
        "SELECT c FROM prices WHERE ticker = ? AND c > 0 ORDER BY ts DESC LIMIT ?",
        (ticker.upper(), lookback),
    ).fetchall()
    closes = [float(r[0]) for r in rows]
    if len(closes) < 2 or closes[-1] <= 0:
        return 0.0
    return (closes[0] - closes[-1]) / closes[-1]  # newest vs oldest in window


def _normalize_period(rows: list[dict[str, Any]]) -> None:
    """Min-max normalize each signal to 0..1 within the period (in place)."""
    for sig in SIGNALS:
        vals = [float(r.get(sig, 0.0) or 0.0) for r in rows]
        lo, hi = min(vals), max(vals)
        span = hi - lo
        for r, v in zip(rows, vals):
            r[f"_n_{sig}"] = (v - lo) / span if span > 0 else 0.5


def _rank_weighted(
    rows: list[dict[str, Any]], weights: dict[str, float], *,
    top_n: int, exclude_megacaps: bool,
) -> list[Pick]:
    pool = [r for r in rows if _is_us(r["ticker"])]
    if exclude_megacaps:
        pool = [r for r in pool if not is_megacap(r["ticker"])]
    pool = [r for r in pool if float(r.get("prob_up", 0.0)) > 0.50]
    # Collapse duplicate tickers (multiple batches/day) to the strongest row.
    best: dict[str, dict[str, Any]] = {}
    for r in pool:
        t = r["ticker"].upper()
        cur = best.get(t)
        if cur is None or float(r.get("prob_up", 0.0)) > float(cur.get("prob_up", 0.0)):
            best[t] = r
    pool = list(best.values())
    if not pool:
        return []
    _normalize_period(pool)
    wsum = sum(max(0.0, w) for w in weights.values()) or 1.0

    def score(r: dict[str, Any]) -> float:
        return sum(
            max(0.0, weights.get(sig, 0.0)) / wsum * float(r.get(f"_n_{sig}", 0.0))
            for sig in SIGNALS
        )

    pool.sort(key=score, reverse=True)
    chosen = pool[:top_n]
    w = 1.0 / len(chosen)
    return [
        Pick(ticker=r["ticker"], weight=w, prob_up=float(r.get("prob_up", 0.0)),
             score=round(score(r), 4))
        for r in chosen
    ]


def _periods(conn: sqlite3.Connection, days: int) -> list[list[dict[str, Any]]]:
    """Group scored predictions by day, enriched with chart_pattern + momentum."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT p.ticker, p.prob_up, p.expected_return_bps, p.created_at, p.due_at"
        " FROM predictions p JOIN outcomes o ON p.id = o.prediction_id"
        " WHERE p.created_at >= ? ORDER BY p.created_at ASC",
        (cutoff,),
    ).fetchall()
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pattern_cache: dict[str, float] = {}
    mom_cache: dict[str, float] = {}
    for ticker, prob_up, er, created_at, due_at in rows:
        if ticker not in pattern_cache:
            pattern_cache[ticker] = chart_pattern_score(conn, ticker)
            mom_cache[ticker] = _momentum(conn, ticker)
        by_day[str(created_at)[:10]].append({
            "ticker": ticker, "prob_up": prob_up,
            "expected_return_bps": er or 0.0,
            "chart_pattern": pattern_cache[ticker], "momentum": mom_cache[ticker],
            "created_at": created_at, "due_at": due_at,
        })
    return [by_day[k] for k in sorted(by_day.keys())]


def _backtest_weights(
    conn: sqlite3.Connection, periods: list[list[dict[str, Any]]],
    weights: dict[str, float], *, top_n: int, exclude_megacaps: bool,
    benchmark: str,
) -> tuple[int, float]:
    """Return (periods_scored, summed_net_excess) for a weight vector."""
    scored = 0
    total_excess = 0.0
    prior: list[str] = []
    for preds in periods:
        picks = _rank_weighted(
            preds, weights, top_n=top_n, exclude_megacaps=exclude_megacaps)
        if not picks:
            continue
        result = score_basket(
            conn, picks, entry_iso=preds[0]["created_at"],
            exit_iso=preds[0]["due_at"], benchmark=benchmark, prior_picks=prior)
        if result is None:
            continue
        scored += 1
        total_excess += result.net_excess
        prior = [p.ticker for p in result.picks]
    return scored, round(total_excess, 6)


def propose_strategies(conn: sqlite3.Connection, *, n: int = 4) -> list[StrategyDef]:
    """Ask the core LLM (Opus 4.8) to invent a slate of named strategies."""
    messages: list[ChatMessage] = [
        {"role": "user", "content": STRATEGY_PROMPT.format(n=n)}]
    client = get_core_client()
    response = client.chat(
        messages=messages, model=get_core_model(), max_tokens=1200,
        conn=conn, caller="strategy_search.propose",
    )
    try:
        raw = parse_llm_json(response.content)
    except Exception:
        logger.warning("strategy_search: could not parse LLM proposal")
        return []
    if isinstance(raw, dict):
        raw = raw.get("strategies", [])
    out: list[StrategyDef] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            out.append(StrategyDef(**item))
        except Exception:
            continue
    return out


def search_and_store(
    conn: sqlite3.Connection, *, n: int = 4, days: int = 45,
    benchmark: str = DEFAULT_BENCHMARK,
) -> list[StrategyScore]:
    """Propose strategies, backtest each vs the prob_up baseline, keep winners."""
    periods = _periods(conn, days)
    if len(periods) < MIN_PERIODS:
        logger.info("strategy_search: only %d periods, need %d -- skipping",
                    len(periods), MIN_PERIODS)
        return []

    # Baseline = pure prob_up ranking (what we already do live).
    base_n, base_excess = _backtest_weights(
        conn, periods, {"prob_up": 1.0}, top_n=5, exclude_megacaps=False,
        benchmark=benchmark)

    results: list[StrategyScore] = []
    for sd in propose_strategies(conn, n=n):
        scored, excess = _backtest_weights(
            conn, periods, sd.weights, top_n=sd.top_n,
            exclude_megacaps=sd.exclude_megacaps, benchmark=benchmark)
        if scored < MIN_PERIODS:
            kept, reason = False, f"only {scored} periods (<{MIN_PERIODS})"
        elif excess <= 0:
            kept, reason = False, f"net excess {excess:+.4f} <= 0"
        elif excess <= base_excess:
            kept, reason = False, (
                f"excess {excess:+.4f} <= baseline {base_excess:+.4f}")
        else:
            kept, reason = True, (
                f"beats baseline: {excess:+.4f} vs {base_excess:+.4f}")
        score = StrategyScore(
            name=sd.name, definition=sd, periods=scored, net_excess=excess,
            baseline_excess=base_excess, kept=kept, reason=reason)
        results.append(score)
        conn.execute(
            "INSERT INTO strategy_runs (name, definition_json, backtest_json,"
            " score, kept, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (sd.name, json.dumps(sd.model_dump()),
             json.dumps({"periods": scored, "net_excess": excess,
                         "baseline_excess": base_excess, "reason": reason}),
             excess, 1 if kept else 0,
             datetime.now(timezone.utc).isoformat()),
        )
    conn.commit()
    kept_names = [r.name for r in results if r.kept]
    logger.info("strategy_search: %d proposed, %d kept (%s); baseline excess %+.4f",
                len(results), len(kept_names), ", ".join(kept_names) or "none",
                base_excess)
    return results


def format_strategy_block(conn: sqlite3.Connection, limit: int = 5) -> str:
    """Render recent strategy-search results for the weekly review note."""
    rows = conn.execute(
        "SELECT name, score, kept, backtest_json FROM strategy_runs"
        " ORDER BY id DESC LIMIT ?", (limit,),
    ).fetchall()
    if not rows:
        return "(no strategies searched yet)"
    lines = ["Amber 策略搜索 / strategy search (recent):"]
    for name, score, kept, bt in rows:
        bt_d = json.loads(bt) if bt else {}
        flag = "KEPT" if kept else "rejected"
        lines.append(
            f"  [{flag}] {name}: net excess {score * 100:+.2f}%"
            f" over {bt_d.get('periods', '?')} periods")
    return "\n".join(lines)
