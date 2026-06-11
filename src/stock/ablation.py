"""stock.ablation -- do the new signals actually predict? (plan H phase H4)

We keep adding context to predictions (knowledge base, macro, market tape).
Each addition is instrumented (knowledge_item_count, context_manifest, ship
dates), but instrumentation without measurement is decoration. This module
compares hit rate / Brier for scored predictions WITH vs WITHOUT each signal:

- knowledge: predictions whose feature_context_json recorded knowledge items
  vs those with none.
- macro / market tape / H1 manifest: before vs after each block's ship date,
  plus presence of context_manifest for the DAG era.

Small samples are flagged loudly -- a 10-prediction split proves nothing.
Run with `stock ablation [--days N]`.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

# Ship dates of each context block (UTC). Predictions created after the date
# carry the signal; before, they cannot have.
SHIP_DATES: dict[str, str] = {
    "knowledge_base": "2026-06-03",
    "macro_block": "2026-06-06",
    "market_tape_h0": "2026-06-11",
    "context_dag_h1": "2026-06-11",
}

MIN_GROUP_N: int = 20  # below this, the split is anecdote, not evidence


def _scored_rows(
    conn: sqlite3.Connection, *, days: int
) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT p.id, p.created_at, p.feature_context_json,"
        " o.direction_hit, o.brier"
        " FROM predictions p JOIN outcomes o ON o.prediction_id = p.id"
        " WHERE p.created_at >= ?",
        (cutoff,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for pid, created_at, fc_json, hit, brier in rows:
        try:
            fc = json.loads(fc_json) if fc_json else {}
        except (TypeError, json.JSONDecodeError):
            fc = {}
        out.append({
            "id": int(pid), "created_at": str(created_at), "fc": fc,
            "hit": bool(hit), "brier": float(brier) if brier is not None else None,
        })
    return out


def _group_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0, "hit_rate": None, "brier": None}
    hits = sum(1 for r in rows if r["hit"])
    briers = [r["brier"] for r in rows if r["brier"] is not None]
    return {
        "n": n,
        "hit_rate": hits / n,
        "brier": sum(briers) / len(briers) if briers else None,
    }


def _split(
    rows: list[dict[str, Any]], predicate
) -> tuple[dict[str, Any], dict[str, Any]]:
    with_signal = [r for r in rows if predicate(r)]
    without = [r for r in rows if not predicate(r)]
    return _group_stats(with_signal), _group_stats(without)


def compute_ablation(
    conn: sqlite3.Connection, *, days: int = 45
) -> dict[str, Any]:
    """Per-signal WITH/WITHOUT stats over scored predictions of the last N days."""
    rows = _scored_rows(conn, days=days)
    report: dict[str, Any] = {"days": days, "total_scored": len(rows), "signals": {}}

    report["signals"]["knowledge_base"] = _split(
        rows, lambda r: int(r["fc"].get("knowledge_item_count") or 0) > 0,
    )
    report["signals"]["context_dag_h1"] = _split(
        rows, lambda r: bool(r["fc"].get("context_manifest")),
    )
    for name in ("macro_block", "market_tape_h0"):
        ship = SHIP_DATES[name]
        report["signals"][name] = _split(
            rows, lambda r, s=ship: str(r["created_at"])[:10] >= s,
        )
    return report


def format_ablation(report: dict[str, Any]) -> str:
    lines = [
        f"Signal ablation -- scored predictions, last {report['days']} day(s)"
        f" (n={report['total_scored']})",
        "",
        f"{'signal':<18} {'':>10} {'n':>5} {'hit rate':>9} {'brier':>7}",
    ]
    for name, (with_s, without_s) in report["signals"].items():
        for label, stats in (("WITH", with_s), ("without", without_s)):
            hr = f"{stats['hit_rate'] * 100:.1f}%" if stats["hit_rate"] is not None else "--"
            br = f"{stats['brier']:.3f}" if stats["brier"] is not None else "--"
            small = "  (small sample!)" if 0 < stats["n"] < MIN_GROUP_N else ""
            lines.append(
                f"{name:<18} {label:>10} {stats['n']:>5} {hr:>9} {br:>7}{small}"
            )
        delta_ok = (
            with_s["hit_rate"] is not None and without_s["hit_rate"] is not None
        )
        if delta_ok:
            delta = (with_s["hit_rate"] - without_s["hit_rate"]) * 100
            verdict = "helps" if delta > 0 else ("hurts" if delta < 0 else "flat")
            lines.append(f"{'':<18} {'delta':>10} {delta:>+14.1f}pp  -> {verdict}")
        lines.append("")
    lines.append(
        f"Groups under n={MIN_GROUP_N} are anecdote, not evidence -- re-run as"
        " outcomes accumulate. Date-based splits also absorb regime change;"
        " treat them as weaker than the per-prediction knowledge split."
    )
    return "\n".join(lines)
