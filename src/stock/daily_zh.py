"""stock.daily_zh -- Chinese daily activity report.

Boss directive 2026-05-06: "give me a chinese report of what each day of
what you are doing". Pulls from existing tables -- no LLM cost. Reports:
* What got built/changed (git commits today)
* Tech dives run today
* Conviction watchlist diffs (toggle/swap operations)
* Trade log entries
* Cron job error counts (from llm_calls + research_reports)
* Status of the trends + conviction layers
"""
from __future__ import annotations

import logging
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from stock.tech_trends import load_conviction, load_trends

logger = logging.getLogger(__name__)

REPORT_DIR: str = "pipeline"


def _today_utc() -> str:
    """ISO date string for 'today' in UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _git_commits_today() -> list[tuple[str, str]]:
    """Return [(hash, subject), ...] for today's commits."""
    today = _today_utc()
    try:
        proc = subprocess.run(
            ["git", "log", f"--since={today}T00:00:00", "--pretty=format:%h\t%s"],
            capture_output=True, text=True, check=False,
            cwd=str(Path.cwd()),
        )
        out = (proc.stdout or "").strip()
        if not out:
            return []
        rows: list[tuple[str, str]] = []
        for line in out.splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                rows.append((parts[0], parts[1]))
        return rows
    except Exception:  # noqa: BLE001 -- subprocess flakey
        logger.debug("git log failed", exc_info=True)
        return []


def _today_tech_dives(conn: sqlite3.Connection) -> list[tuple[str, str, int]]:
    """Today's tech_dive runs as (topic, sector, rounds)."""
    today = _today_utc()
    rows = conn.execute(
        "SELECT topic, sector, rounds FROM tech_dive_runs"
        " WHERE created_at >= ? ORDER BY created_at",
        (f"{today}T00:00:00",),
    ).fetchall()
    return [(str(r[0]), str(r[1]), int(r[2])) for r in rows]


def _today_research_kinds(conn: sqlite3.Connection) -> dict[str, int]:
    """Count research_reports rows by kind for today."""
    today = _today_utc()
    rows = conn.execute(
        "SELECT kind, COUNT(*) FROM research_reports"
        " WHERE created_at >= ? GROUP BY kind",
        (f"{today}T00:00:00",),
    ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def _today_trade_log(conn: sqlite3.Connection) -> list[str]:
    """Trade log subjects for today."""
    today = _today_utc()
    rows = conn.execute(
        "SELECT topic FROM research_reports"
        " WHERE kind = 'trade_log' AND created_at >= ?"
        " ORDER BY created_at",
        (f"{today}T00:00:00",),
    ).fetchall()
    return [str(r[0]) for r in rows if r[0]]


def _today_alerts(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Sell-trigger alerts for today: (topic, first 80 chars of body)."""
    today = _today_utc()
    rows = conn.execute(
        "SELECT topic, substr(body, 1, 80) FROM research_reports"
        " WHERE kind = 'alert' AND created_at >= ?"
        " ORDER BY created_at DESC",
        (f"{today}T00:00:00",),
    ).fetchall()
    return [(str(r[0] or "?"), str(r[1] or "")) for r in rows]


def _today_llm_cost(conn: sqlite3.Connection) -> tuple[int, float]:
    """Total LLM calls + cost for today."""
    today = _today_utc()
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(cost_usd), 0) FROM llm_calls"
        " WHERE created_at >= ?",
        (f"{today}T00:00:00",),
    ).fetchone()
    return (int(row[0]), float(row[1])) if row else (0, 0.0)


def generate_daily_zh_report(conn: sqlite3.Connection) -> tuple[str, str]:
    """Build the Chinese daily activity report; return (path, body)."""
    today = _today_utc()
    try:
        commits = _git_commits_today()
    except Exception:  # noqa: BLE001 -- git tooling can be missing/flaky
        logger.debug("git log lookup failed", exc_info=True)
        commits = []
    dives = _today_tech_dives(conn)
    kinds = _today_research_kinds(conn)
    trades = _today_trade_log(conn)
    alerts = _today_alerts(conn)
    n_calls, cost = _today_llm_cost(conn)
    enabled_trends = load_trends(enabled_only=True)
    enabled_conviction = load_conviction(enabled_only=True)

    lines = [
        f"# 每日工作汇报 / Daily activity report -- {today}",
        "",
        "_自动生成 / Auto-generated; 不替代 manual review_",
        "",
        "---",
        "",
        "## 1. 今日新增功能 / What got built today",
        "",
    ]
    if commits:
        for h, subj in commits:
            lines.append(f"- `{h}` {subj}")
    else:
        lines.append("_(no git commits today)_")
    lines.append("")

    lines.append("## 2. 技术深挖 / Tech dives run today (F43)")
    lines.append("")
    if dives:
        for topic, sector, rounds in dives:
            lines.append(f"- [{sector}] **{topic[:70]}** ({rounds} rounds)")
    else:
        lines.append("_(no tech dives run today)_")
    lines.append("")

    lines.append("## 3. 报告产出 / Research reports written today")
    lines.append("")
    if kinds:
        for kind, n in sorted(kinds.items(), key=lambda x: -x[1]):
            lines.append(f"- `{kind}`: {n}")
    else:
        lines.append("_(no reports written)_")
    lines.append("")

    lines.append("## 4. 交易日志 / Trade log")
    lines.append("")
    if trades:
        for t in trades:
            lines.append(f"- {t}")
    else:
        lines.append("_(no trade log entries today)_")
    lines.append("")

    lines.append("## 5. 持仓警报 / Holding alerts")
    lines.append("")
    if alerts:
        for topic, excerpt in alerts:
            lines.append(f"- **{topic}** -- {excerpt}...")
    else:
        lines.append("_(no holding alerts today)_")
    lines.append("")

    lines.append("## 6. 趋势 + 重仓状态 / Trend + conviction state")
    lines.append("")
    lines.append(f"- Enabled tech trends (F41): **{len(enabled_trends)}**")
    by_sector: dict[str, int] = {}
    for t in enabled_trends:
        by_sector[t.sector] = by_sector.get(t.sector, 0) + 1
    for sector, n in by_sector.items():
        lines.append(f"  - {sector}: {n}")
    lines.append(f"- Enabled conviction names (F42): **{len(enabled_conviction)}**")
    if enabled_conviction:
        lines.append("  - " + ", ".join(n.ticker for n in enabled_conviction))
    lines.append("")

    lines.append("## 7. LLM 用量 / LLM usage today")
    lines.append("")
    lines.append(f"- Total calls: **{n_calls}**")
    lines.append(f"- Total cost: **${cost:.4f}**")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_Not financial advice. 不构成投资建议._")

    body = "\n".join(lines)
    out = Path(REPORT_DIR) / f"daily_zh_{today}.md"
    out.write_text(body, encoding="utf-8")
    return str(out), body
