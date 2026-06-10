"""stock.usage -- LLM usage reporting over the llm_calls ledger.

Every LLM call is already logged to `llm_calls` (provider, model, tokens, cost,
duration, caller), but until now there was no way to READ it back without raw
SQL. Codex CLI and Claude CLI are subscription backends that log cost_usd=0, so
TOKENS are the quota signal that matters -- and a rising claude_cli share means
the codex credit/usage circuit breaker (F17c) is tripping and falling back.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def usage_by_provider(conn: sqlite3.Connection, *, days: int = 7) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT provider, model, COUNT(*), SUM(input_tokens), SUM(output_tokens),"
        " SUM(cost_usd), AVG(duration_ms)"
        " FROM llm_calls WHERE created_at >= ?"
        " GROUP BY provider, model ORDER BY COUNT(*) DESC",
        (_cutoff(days),),
    ).fetchall()
    return [
        {
            "provider": r[0], "model": r[1], "calls": int(r[2]),
            "input_tokens": int(r[3] or 0), "output_tokens": int(r[4] or 0),
            "cost_usd": float(r[5] or 0.0), "avg_duration_ms": float(r[6] or 0.0),
        }
        for r in rows
    ]


def usage_by_day(conn: sqlite3.Connection, *, days: int = 7) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT substr(created_at, 1, 10) AS day, provider, COUNT(*),"
        " SUM(input_tokens), SUM(output_tokens), SUM(cost_usd)"
        " FROM llm_calls WHERE created_at >= ?"
        " GROUP BY day, provider ORDER BY day DESC, provider",
        (_cutoff(days),),
    ).fetchall()
    return [
        {
            "day": r[0], "provider": r[1], "calls": int(r[2]),
            "input_tokens": int(r[3] or 0), "output_tokens": int(r[4] or 0),
            "cost_usd": float(r[5] or 0.0),
        }
        for r in rows
    ]


def usage_by_caller(
    conn: sqlite3.Connection, *, days: int = 7, limit: int = 12
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT caller, COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd)"
        " FROM llm_calls WHERE created_at >= ?"
        " GROUP BY caller ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC LIMIT ?",
        (_cutoff(days), limit),
    ).fetchall()
    return [
        {
            "caller": r[0], "calls": int(r[1]),
            "input_tokens": int(r[2] or 0), "output_tokens": int(r[3] or 0),
            "cost_usd": float(r[4] or 0.0),
        }
        for r in rows
    ]


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def format_usage_report(conn: sqlite3.Connection, *, days: int = 7) -> str:
    """Human-readable usage report for the CLI."""
    providers = usage_by_provider(conn, days=days)
    if not providers:
        return f"No LLM calls in the last {days} day(s)."

    lines: list[str] = [f"LLM usage -- last {days} day(s)", ""]
    lines.append("Provider / model                 calls      in       out    cost$   avg ms")
    for p in providers:
        label = f"{p['provider']} / {p['model']}"[:32]
        lines.append(
            f"{label:<32} {p['calls']:>5}  {_fmt_tokens(p['input_tokens']):>7}"
            f"  {_fmt_tokens(p['output_tokens']):>7}  {p['cost_usd']:>6.2f}"
            f"  {p['avg_duration_ms']:>7.0f}"
        )

    total_calls = sum(p["calls"] for p in providers)
    cli_calls = {p["provider"]: p["calls"] for p in providers}
    codex = cli_calls.get("codex_cli", 0)
    claude = cli_calls.get("claude_cli", 0)
    if codex + claude > 0:
        share = claude / (codex + claude) * 100
        lines.append("")
        lines.append(
            f"claude_cli fallback share: {share:.0f}% of {codex + claude} CLI calls"
            " (rising share = codex credit/usage circuit breaker tripping)"
        )

    lines.append("")
    lines.append("By day:")
    for d in usage_by_day(conn, days=days):
        lines.append(
            f"  {d['day']}  {d['provider']:<12} {d['calls']:>5} calls"
            f"  in {_fmt_tokens(d['input_tokens']):>7}  out {_fmt_tokens(d['output_tokens']):>7}"
            f"  ${d['cost_usd']:.2f}"
        )

    lines.append("")
    lines.append("Top callers by tokens:")
    for c in usage_by_caller(conn, days=days):
        lines.append(
            f"  {c['caller'][:44]:<44} {c['calls']:>5} calls"
            f"  in {_fmt_tokens(c['input_tokens']):>7}  out {_fmt_tokens(c['output_tokens']):>7}"
        )

    lines.append("")
    lines.append(f"Total: {total_calls} calls in {days} day(s).")
    return "\n".join(lines)
