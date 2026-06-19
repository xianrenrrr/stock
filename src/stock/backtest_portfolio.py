"""stock.backtest_portfolio -- replay our predictions as a Top-N basket vs QQQ.

#3 of the Amber-learning build. The Amber tool's whole value is the backtest:
prove a strategy beats the benchmark on history before trusting it. We replay
our OWN prediction history the same way -- each period, rank the day's
predictions, hold the top-N, score the basket vs QQQ net of execution cost --
and report excess return, Sharpe, drawdown, turnover, win rate.

This is the honest mirror of their +3087% screenshot: same machinery, but run
over our real out-of-sample predictions so the number means something.
"""
from __future__ import annotations

import logging
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

from stock.portfolio import (
    DEFAULT_BENCHMARK,
    DEFAULT_TOP_N,
    ROUND_TRIP_COST_BPS,
    rank_picks,
    score_basket,
)

logger = logging.getLogger(__name__)


class BacktestResult(BaseModel):
    periods: int
    top_n: int
    benchmark: str
    port_total_return: float
    bench_total_return: float
    total_excess: float
    sharpe_excess: float | None     # annualized Sharpe of per-period excess
    max_drawdown: float
    avg_turnover: float
    win_rate: float                 # % of periods the basket beat the benchmark
    avg_cost_drag: float
    note: str


def _period_predictions(
    conn: sqlite3.Connection, *, days: int, weekly: bool,
) -> dict[str, list[dict[str, Any]]]:
    """Group scored predictions into periods keyed by date (or ISO week)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT p.ticker, p.prob_up, p.expected_return_bps, p.created_at, p.due_at"
        " FROM predictions p JOIN outcomes o ON p.id = o.prediction_id"
        " WHERE p.created_at >= ? ORDER BY p.created_at ASC",
        (cutoff,),
    ).fetchall()
    periods: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ticker, prob_up, er, created_at, due_at in rows:
        if weekly:
            d = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            iso = d.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        else:
            key = str(created_at)[:10]
        periods[key].append({
            "ticker": ticker, "prob_up": prob_up, "expected_return_bps": er,
            "created_at": created_at, "due_at": due_at,
        })
    return periods


def backtest_topn(
    conn: sqlite3.Connection, *, days: int = 30, top_n: int = DEFAULT_TOP_N,
    weekly: bool = False, benchmark: str = DEFAULT_BENCHMARK,
    cost_bps: float = ROUND_TRIP_COST_BPS,
) -> BacktestResult:
    """Replay a Top-N long basket over prediction history and score vs benchmark."""
    periods = _period_predictions(conn, days=days, weekly=weekly)
    keys = sorted(periods.keys())

    port_equity = 1.0
    bench_equity = 1.0
    peak = 1.0
    max_dd = 0.0
    excesses: list[float] = []
    turnovers: list[float] = []
    costs: list[float] = []
    wins = 0
    scored_periods = 0
    prior: list[str] = []

    for key in keys:
        preds = periods[key]
        picks = rank_picks(preds, top_n=top_n, us_only=True)
        if not picks:
            continue
        entry = preds[0]["created_at"]
        exit_iso = preds[0]["due_at"]
        result = score_basket(
            conn, picks, entry_iso=entry, exit_iso=exit_iso,
            benchmark=benchmark, prior_picks=prior, cost_bps=cost_bps,
        )
        if result is None:
            continue
        scored_periods += 1
        port_net = result.port_return - result.turnover * (cost_bps / 10000.0)
        port_equity *= (1.0 + port_net)
        bench_equity *= (1.0 + result.bench_return)
        peak = max(peak, port_equity)
        max_dd = max(max_dd, (peak - port_equity) / peak if peak else 0.0)
        excesses.append(result.net_excess)
        turnovers.append(result.turnover)
        costs.append(result.turnover * (cost_bps / 10000.0))
        if result.net_excess > 0:
            wins += 1
        prior = [p.ticker for p in result.picks]

    if scored_periods == 0:
        return BacktestResult(
            periods=0, top_n=top_n, benchmark=benchmark,
            port_total_return=0.0, bench_total_return=0.0, total_excess=0.0,
            sharpe_excess=None, max_drawdown=0.0, avg_turnover=0.0,
            win_rate=0.0, avg_cost_drag=0.0,
            note="no scoreable periods in window",
        )

    mean_ex = sum(excesses) / len(excesses)
    if len(excesses) > 1:
        var = sum((x - mean_ex) ** 2 for x in excesses) / (len(excesses) - 1)
        std = math.sqrt(var)
        # Annualize: ~52 weekly or ~252 daily periods.
        ann = 52 if weekly else 252
        sharpe = (mean_ex / std * math.sqrt(ann)) if std > 0 else None
    else:
        sharpe = None

    return BacktestResult(
        periods=scored_periods, top_n=top_n, benchmark=benchmark,
        port_total_return=round(port_equity - 1.0, 6),
        bench_total_return=round(bench_equity - 1.0, 6),
        total_excess=round((port_equity - 1.0) - (bench_equity - 1.0), 6),
        sharpe_excess=round(sharpe, 3) if sharpe is not None else None,
        max_drawdown=round(max_dd, 6),
        avg_turnover=round(sum(turnovers) / len(turnovers), 4),
        win_rate=round(wins / scored_periods, 4),
        avg_cost_drag=round(sum(costs) / len(costs), 6),
        note=f"{'weekly' if weekly else 'daily'} rebalance, {days}d window",
    )


def format_backtest(r: BacktestResult) -> str:
    """Human-readable backtest report for the CLI."""
    if r.periods == 0:
        return f"Backtest: {r.note}"
    sh = f"{r.sharpe_excess:.2f}" if r.sharpe_excess is not None else "n/a"
    return "\n".join([
        f"Top-{r.top_n} basket backtest vs {r.benchmark} ({r.note})",
        f"  periods scored:   {r.periods}",
        f"  basket return:    {r.port_total_return * 100:+.2f}%",
        f"  benchmark return: {r.bench_total_return * 100:+.2f}%",
        f"  TOTAL EXCESS:     {r.total_excess * 100:+.2f}%   <- the number that matters",
        f"  excess Sharpe:    {sh}",
        f"  max drawdown:     {r.max_drawdown * 100:.2f}%",
        f"  win rate vs bench:{r.win_rate * 100:.0f}%",
        f"  avg turnover:     {r.avg_turnover * 100:.0f}%"
        f"  (cost drag {r.avg_cost_drag * 100:.3f}%/period)",
    ])
