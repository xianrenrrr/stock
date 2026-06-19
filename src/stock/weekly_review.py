"""stock.weekly_review -- Saturday review of the Sunday weekly predictions.

Boss 2026-06-18: every Sunday the system makes 1-week-horizon predictions; the
following Saturday we check whether they were right. This module builds that
review note from the scored weekly predictions (horizon_minutes =
WEEKLY_HORIZON_MINUTES) and persists it as research_reports(kind='weekly_review')
so it syncs to the boss app / email like any other note.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from stock.predict import WEEKLY_HORIZON_MINUTES

logger = logging.getLogger(__name__)

CHINA_SUFFIXES: tuple[str, ...] = (".SS", ".SZ", ".HK")
REVIEW_LOOKBACK_DAYS: int = 8  # cover the Sunday->Saturday week with slack


def _market(ticker: str) -> str:
    return "CN" if (ticker or "").upper().endswith(CHINA_SUFFIXES) else "US"


def _scored_weekly(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT p.ticker, p.direction, p.prob_up, o.actual_return, o.direction_hit,"
        " p.created_at FROM predictions p JOIN outcomes o ON p.id = o.prediction_id"
        " WHERE p.horizon_minutes = ?"
        "   AND o.scored_at >= datetime('now', ?)"
        " ORDER BY o.direction_hit ASC, ABS(o.actual_return) DESC",
        (WEEKLY_HORIZON_MINUTES, f"-{REVIEW_LOOKBACK_DAYS} days"),
    ).fetchall()
    return [
        {"ticker": r[0], "direction": r[1], "prob_up": r[2],
         "actual": r[3], "hit": bool(r[4]), "created_at": r[5]}
        for r in rows
    ]


def _bucket_line(label: str, rows: list[dict]) -> str:
    if not rows:
        return f"- {label}: 本周无评分 / none scored"
    n = len(rows)
    hits = sum(1 for r in rows if r["hit"])
    avg = sum(r["actual"] for r in rows) / n * 100
    return f"- {label}: {hits}/{n} = {hits / n:.0%} 命中, 平均周收益 {avg:+.2f}%"


def build_weekly_review_body(rows: list[dict]) -> str:
    """Render the Saturday review markdown from scored weekly predictions."""
    if not rows:
        return (
            "# 每周预测复盘 / Weekly prediction review\n\n"
            "本周无到期的周度预测可评分（周日批次可能尚未运行或价格未刷新）。\n\n"
            "Not financial advice."
        )
    cn = [r for r in rows if _market(r["ticker"]) == "CN"]
    us = [r for r in rows if _market(r["ticker"]) == "US"]
    week_of = str(rows[0]["created_at"])[:10]

    lines = [
        "# 每周预测复盘 / Weekly prediction review",
        f"_周日批次 {week_of} → 本周五收盘评分 / Sunday batch, scored at Friday close_",
        "",
        "## 命中 / Hit summary",
        _bucket_line("全部 / All", rows),
        _bucket_line("🇺🇸 美股 / US", us),
        _bucket_line("🇨🇳 中国 (A股/港股) / China", cn),
        "",
        "## 最佳 / 最差 / Best & worst weekly calls",
    ]
    hits = [r for r in rows if r["hit"]]
    misses = [r for r in rows if not r["hit"]]
    if hits:
        b = max(hits, key=lambda r: abs(r["actual"]))
        lines.append(
            f"- ✅ 最佳: {b['ticker']} 看{b['direction']} (p={b['prob_up']:.2f})"
            f" → 周收益 {b['actual'] * 100:+.2f}%"
        )
    if misses:
        w = max(misses, key=lambda r: abs(r["actual"]))
        lines.append(
            f"- ❌ 最差: {w['ticker']} 看{w['direction']} (p={w['prob_up']:.2f})"
            f" → 周收益 {w['actual'] * 100:+.2f}% (方向错)"
        )
    lines += ["", "Not financial advice."]
    return "\n".join(lines)


def generate_weekly_review(conn: sqlite3.Connection) -> int | None:
    """Build + persist the weekly review note. Returns research_id or None."""
    rows = _scored_weekly(conn)
    if not rows:
        logger.info("weekly review: no scored weekly predictions in window")
        return None
    body = build_weekly_review_body(rows)
    cursor = conn.execute(
        "INSERT INTO research_reports (kind, topic, layer_focus, body, cost_usd, created_at)"
        " VALUES ('weekly_review', ?, NULL, ?, 0, ?)",
        ("每周预测复盘 / Weekly prediction review", body,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return int(cursor.lastrowid or 0) or None
