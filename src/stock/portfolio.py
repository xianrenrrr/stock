"""stock.portfolio -- cross-sectional Top-N basket + benchmark-relative scoring.

Boss 2026-06-18, learning from the Amber/Kelly quant tool: our orchestrator
predicts each ticker in isolation (absolute up/down, ~50% hit). The Amber tool
instead RANKS a universe and buys the best N each week, scored as EXCESS return
over QQQ with realistic execution. Cross-sectional alpha (which name beats which)
is easier than absolute direction, so this can have edge even when our raw hit
rate is a coin flip.

This module covers:
  #1 Top-N ranking -> weekly long basket
  #2 Benchmark-relative scoring (excess over QQQ)
  #4 Execution realism: close-to-close fills on the SAME basis score.score_due
     uses to grade predictions (so basket returns reconcile with realized
     actual_return), plus slippage+commission and a turnover penalty.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_BENCHMARK: str = "QQQ"
DEFAULT_TOP_N: int = 5
# Execution model: round-trip cost in basis points (slippage + commission),
# charged on the turned-over fraction each rebalance. Returns themselves use the
# close-to-close basis (see _return_between) that matches our grading engine.
ROUND_TRIP_COST_BPS: float = 10.0   # ~5 bps each way; conservative for liquid US names


class Pick(BaseModel):
    ticker: str
    weight: float
    prob_up: float
    score: float


class BasketResult(BaseModel):
    """A scored basket: portfolio vs benchmark, net of execution cost."""

    picks: list[Pick]
    port_return: float
    bench_return: float
    excess_return: float
    turnover: float
    cost_bps: float
    net_excess: float          # excess_return minus turnover*cost
    benchmark: str


# Any exchange suffix means a foreign listing; a real US name has no suffix.
# QQQ-benchmarked baskets must hold US listings only, so Taiwan (.TW/.TWO),
# Japan (.T), Korea (.KS) etc. are excluded alongside China (.SS/.SZ/.HK).
_CN_SUFFIXES: tuple[str, ...] = (".SS", ".SZ", ".HK")


def _market(ticker: str) -> str:
    return "CN" if ticker.upper().endswith(_CN_SUFFIXES) else "US"


def _is_us(ticker: str) -> bool:
    """True only for plain US listings (no foreign exchange suffix)."""
    t = ticker.upper()
    # A '.' segment that isn't a US class-share marker (e.g. BRK.B) is foreign.
    if "." not in t:
        return True
    suffix = "." + t.rsplit(".", 1)[1]
    return suffix in {".A", ".B"}  # class shares stay US; all real exchanges drop


def rank_picks(
    rows: list[dict[str, Any]], *, top_n: int = DEFAULT_TOP_N, us_only: bool = True,
) -> list[Pick]:
    """Rank prediction rows into a top-N equal-weight long basket.

    rows: [{ticker, prob_up, expected_return_bps?}]. Ranked by prob_up first,
    expected_return_bps as tiebreak. Only 'up'-leaning names (prob_up > 0.5) are
    eligible -- a long basket should not hold names the model expects to fall.
    Duplicate rows for the same ticker (multiple prediction batches in a day) are
    collapsed to the single best row, so a name is never held more than once.
    """
    pool = [r for r in rows if (not us_only or _is_us(r["ticker"]))]
    # Keep the strongest row per ticker before ranking.
    best: dict[str, dict[str, Any]] = {}
    for r in pool:
        t = r["ticker"].upper()
        cur = best.get(t)
        if cur is None or float(r.get("prob_up", 0.0)) > float(cur.get("prob_up", 0.0)):
            best[t] = r
    longs = [r for r in best.values() if float(r.get("prob_up", 0.0)) > 0.50]
    longs.sort(
        key=lambda r: (float(r.get("prob_up", 0.0)),
                       float(r.get("expected_return_bps", 0.0) or 0.0)),
        reverse=True,
    )
    chosen = longs[:top_n]
    if not chosen:
        return []
    w = 1.0 / len(chosen)
    return [
        Pick(
            ticker=r["ticker"], weight=w,
            prob_up=float(r.get("prob_up", 0.0)),
            score=float(r.get("prob_up", 0.0)),
        )
        for r in chosen
    ]


def _return_between(
    conn: sqlite3.Connection, ticker: str, entry_iso: str, exit_iso: str,
) -> float | None:
    """Close-to-close return, IDENTICAL to how score.score_due grades predictions:
    entry = last close at/before the signal date, exit = first close at/on/after the
    due date. Using the same basis means a basket's measured return reconciles
    exactly with the realized actual_return of its picks -- no open-fill optimism
    that captures an intraday session the live strategy never traded. None if
    either leg has no price. Turnover/commission are applied on top by the caller."""
    entry = conn.execute(
        "SELECT c FROM prices WHERE ticker = ? AND ts <= substr(?,1,10)"
        " ORDER BY ts DESC LIMIT 1",
        (ticker.upper(), entry_iso),
    ).fetchone()
    exit_row = conn.execute(
        "SELECT c FROM prices WHERE ticker = ? AND ts >= substr(?,1,10)"
        " ORDER BY ts ASC LIMIT 1",
        (ticker.upper(), exit_iso),
    ).fetchone()
    if not entry or not exit_row or not entry[0] or entry[0] <= 0:
        return None
    return (float(exit_row[0]) - float(entry[0])) / float(entry[0])


def score_basket(
    conn: sqlite3.Connection,
    picks: list[Pick],
    *,
    entry_iso: str,
    exit_iso: str,
    benchmark: str = DEFAULT_BENCHMARK,
    prior_picks: list[str] | None = None,
    cost_bps: float = ROUND_TRIP_COST_BPS,
) -> BasketResult | None:
    """Score a basket: weighted T+1 return vs benchmark, net of turnover cost."""
    contribs: list[tuple[Pick, float]] = []
    for p in picks:
        r = _return_between(conn, p.ticker, entry_iso, exit_iso)
        if r is not None:
            contribs.append((p, r))
    if not contribs:
        return None
    # Re-normalize weights over names that actually priced.
    tot_w = sum(p.weight for p, _ in contribs)
    port_return = sum(p.weight / tot_w * r for p, r in contribs)

    bench = _return_between(conn, benchmark, entry_iso, exit_iso)
    if bench is None:
        bench = 0.0

    # Turnover vs the prior basket: fraction of names that changed (one-sided).
    held = {p.ticker.upper() for p, _ in contribs}
    prior = {t.upper() for t in (prior_picks or [])}
    if prior:
        turnover = len(held - prior) / max(len(held), 1)
    else:
        turnover = 1.0  # first basket: fully bought
    cost = turnover * (cost_bps / 10000.0)

    excess = port_return - bench
    return BasketResult(
        picks=[p for p, _ in contribs],
        port_return=round(port_return, 6),
        bench_return=round(bench, 6),
        excess_return=round(excess, 6),
        turnover=round(turnover, 4),
        cost_bps=cost_bps,
        net_excess=round(excess - cost, 6),
        benchmark=benchmark,
    )


def latest_weekly_predictions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Most recent prediction per ticker from the latest weekly batch."""
    from stock.predict import WEEKLY_HORIZON_MINUTES

    rows = conn.execute(
        "SELECT ticker, prob_up, expected_return_bps, created_at, due_at FROM predictions p"
        " WHERE horizon_minutes = ? AND created_at = ("
        "   SELECT MAX(created_at) FROM predictions WHERE horizon_minutes = ?)"
        " GROUP BY ticker",
        (WEEKLY_HORIZON_MINUTES, WEEKLY_HORIZON_MINUTES),
    ).fetchall()
    return [
        {"ticker": r[0], "prob_up": r[1], "expected_return_bps": r[2],
         "created_at": r[3], "due_at": r[4]}
        for r in rows
    ]


def build_and_store_weekly_basket(
    conn: sqlite3.Connection, *, top_n: int = DEFAULT_TOP_N,
    benchmark: str = DEFAULT_BENCHMARK,
) -> int | None:
    """Build a Top-N basket from the latest weekly predictions and persist it."""
    preds = latest_weekly_predictions(conn)
    if not preds:
        logger.info("weekly basket: no weekly predictions to rank")
        return None
    picks = rank_picks(preds, top_n=top_n, us_only=True)
    if not picks:
        logger.info("weekly basket: no up-leaning names to hold")
        return None
    formed_at = preds[0]["created_at"]
    due_at = preds[0]["due_at"]
    cursor = conn.execute(
        "INSERT INTO baskets (kind, benchmark, formed_at, due_at, picks_json)"
        " VALUES ('weekly', ?, ?, ?, ?)",
        (benchmark, formed_at, due_at,
         json.dumps([p.model_dump() for p in picks])),
    )
    conn.commit()
    logger.info(
        "Weekly basket #%s: %s", cursor.lastrowid,
        ", ".join(f"{p.ticker}({p.prob_up:.2f})" for p in picks),
    )
    return int(cursor.lastrowid or 0) or None


def score_due_baskets(conn: sqlite3.Connection) -> int:
    """Score any unscored basket whose due_at has passed. Returns count scored."""
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT id, benchmark, formed_at, due_at, picks_json FROM baskets"
        " WHERE scored_at IS NULL AND due_at <= ? ORDER BY id ASC",
        (now,),
    ).fetchall()
    scored = 0
    prior_tickers: list[str] = []
    for bid, benchmark, formed_at, due_at, picks_json in rows:
        picks = [Pick(**p) for p in json.loads(picks_json)]
        result = score_basket(
            conn, picks, entry_iso=formed_at, exit_iso=due_at,
            benchmark=benchmark, prior_picks=prior_tickers,
        )
        if result is None:
            continue
        conn.execute(
            "UPDATE baskets SET scored_at = ?, port_return = ?, bench_return = ?,"
            " excess_return = ?, turnover = ?, cost_bps = ?, net_excess = ?"
            " WHERE id = ?",
            (now, result.port_return, result.bench_return, result.excess_return,
             result.turnover, result.cost_bps, result.net_excess, bid),
        )
        prior_tickers = [p.ticker for p in result.picks]
        scored += 1
    conn.commit()
    return scored


def format_basket_block(conn: sqlite3.Connection) -> str:
    """Render the latest formed basket + last scored result for the review note."""
    latest = conn.execute(
        "SELECT picks_json, formed_at, scored_at, port_return, bench_return,"
        " net_excess, turnover FROM baskets ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not latest:
        return "(no basket formed yet)"
    picks = [Pick(**p) for p in json.loads(latest[0])]
    lines = [
        "本周 Top-N 多头篮子 / Weekly Top-N long basket"
        f" (formed {str(latest[1])[:10]}):",
        "  " + ", ".join(f"{p.ticker}({p.prob_up:.2f})" for p in picks),
    ]
    if latest[2] is not None:  # scored
        lines.append(
            f"  上期结果 / last result: 组合 {latest[3] * 100:+.2f}% vs"
            f" 基准 {latest[4] * 100:+.2f}% -> 净超额 {latest[5] * 100:+.2f}%"
            f" (换手 {latest[6] * 100:.0f}%)"
        )
    return "\n".join(lines)
