"""stock.self_review -- compile a daily review packet, route to Claude Code or MiniMax."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from stock.config import get_settings
from stock.models import (
    ChatMessage,
    ChatResponse,
    CostCeilingError,
    check_cost_ceiling,
    get_client,
    parse_llm_json,
)

logger = logging.getLogger(__name__)

REVIEW_DIR: str = "pipeline"
REVIEW_PROMPT_PATH: str = "prompts/self_review.txt"
SELF_REVIEW_MODEL: str = "MiniMax-M2.5-highspeed"
SELF_REVIEW_MAX_TOKENS: int = 4000
LOOKBACK_HOURS: int = 24
PROMPT_REWRITES_LOOKBACK_DAYS: int = 7
ALLOWED_BACKENDS: tuple[str, ...] = ("claude_code", "minimax", "both", "off")


class ReviewProposal(BaseModel):
    """One improvement proposal emitted by the self-review LLM."""

    title: str
    rationale: str
    files: list[str]
    diff_or_steps: str
    impact: str = "medium"
    risk: str = "medium"


class ReviewPacketResult(BaseModel):
    """Result of compile_daily_packet."""

    date: str
    path: str
    body: str


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _date_window(date_str: str | None) -> tuple[str, str, str]:
    """Return (date, since_iso, until_iso) — UTC midnights bracketing the day."""
    target = (
        datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
        if date_str
        else _now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    )
    since = target - timedelta(hours=LOOKBACK_HOURS)
    until = target + timedelta(days=1)
    return target.strftime("%Y-%m-%d"), since.isoformat(), until.isoformat()


def _fmt_money(x: float) -> str:
    return f"${x:.4f}"


def _section_header(title: str) -> str:
    return f"\n## {title}\n"


def _section_health(conn: sqlite3.Connection, since: str, until: str) -> str:
    """Operational counters from the last 24h."""
    # LLM cost + call count broken down by model
    rows = conn.execute(
        "SELECT model, COUNT(*), COALESCE(SUM(cost_usd), 0.0),"
        " COALESCE(AVG(duration_ms), 0.0) FROM llm_calls"
        " WHERE created_at >= ? AND created_at < ? GROUP BY model"
        " ORDER BY 3 DESC",
        (since, until),
    ).fetchall()
    total_calls = sum(int(r[1]) for r in rows)
    total_cost = sum(float(r[2]) for r in rows)

    # WeChat delivery
    delivery = conn.execute(
        "SELECT status, COUNT(*) FROM wechat_log"
        " WHERE created_at >= ? AND created_at < ? GROUP BY status",
        (since, until),
    ).fetchall()
    delivery_map = {str(s): int(c) for s, c in delivery}

    # Predictions made + scored
    pred_count = conn.execute(
        "SELECT COUNT(*) FROM predictions WHERE created_at >= ? AND created_at < ?",
        (since, until),
    ).fetchone()[0]
    scored_count = conn.execute(
        "SELECT COUNT(*) FROM outcomes WHERE scored_at >= ? AND scored_at < ?",
        (since, until),
    ).fetchone()[0]

    # Anomalies + web discovery
    anomaly_count = conn.execute(
        "SELECT COUNT(*) FROM price_anomalies WHERE created_at >= ? AND created_at < ?",
        (since, until),
    ).fetchone()[0]
    web_count = conn.execute(
        "SELECT COUNT(*) FROM web_research WHERE created_at >= ? AND created_at < ?",
        (since, until),
    ).fetchone()[0]

    # Format
    out = [_section_header("Operational health (last 24h)")]
    out.append(f"- LLM: {total_calls} calls, total {_fmt_money(total_cost)}")
    for model, count, cost, avg_ms in rows:
        out.append(
            f"  - {model}: {count} calls, {_fmt_money(float(cost))},"
            f" avg {int(float(avg_ms))} ms"
        )
    out.append(
        f"- WeChat delivery: sent={delivery_map.get('sent', 0)}"
        f" failed={delivery_map.get('failed', 0)}"
        f" queued={delivery_map.get('queued', 0)}"
    )
    out.append(f"- Predictions: {pred_count} made, {scored_count} scored")
    out.append(f"- Anomalies flagged: {anomaly_count}")
    out.append(f"- Web research extractions: {web_count}")
    return "\n".join(out) + "\n"


def _section_boss_feedback(conn: sqlite3.Connection, since: str, until: str) -> str:
    """Inbound + outbound conversation turns in the window."""
    rows = conn.execute(
        "SELECT created_at, recipient, direction, intent, body"
        " FROM conversations WHERE created_at >= ? AND created_at < ?"
        " ORDER BY created_at ASC",
        (since, until),
    ).fetchall()

    out = [_section_header("Boss feedback (last 24h)")]
    if not rows:
        out.append("- (no conversations)")
        return "\n".join(out) + "\n"

    for ts, recipient, direction, intent, body in rows:
        body_short = str(body).replace("\n", " ")[:300]
        intent_str = f" intent={intent}" if intent else ""
        out.append(
            f"- [{str(ts)[:16]}] {direction} {recipient}{intent_str}: \"{body_short}\""
        )
    return "\n".join(out) + "\n"


def _section_action_queue(conn: sqlite3.Connection) -> str:
    """Pending + recent action items."""
    pending = conn.execute(
        "SELECT id, topic, queued_at FROM action_queue"
        " WHERE status = 'pending' ORDER BY queued_at DESC LIMIT 20"
    ).fetchall()
    failed = conn.execute(
        "SELECT id, topic, error, queued_at FROM action_queue"
        " WHERE status = 'failed' ORDER BY queued_at DESC LIMIT 10"
    ).fetchall()

    out = [_section_header("Action queue")]
    out.append(f"- Pending: {len(pending)}")
    for aid, topic, queued_at in pending[:10]:
        out.append(f"  - #{aid} ({str(queued_at)[:16]}): {str(topic)[:200]}")
    if failed:
        out.append(f"- Failed: {len(failed)}")
        for aid, topic, error, queued_at in failed:
            out.append(
                f"  - #{aid} ({str(queued_at)[:16]}): {str(topic)[:120]}"
                f" — {str(error)[:200]}"
            )
    return "\n".join(out) + "\n"


def _section_prompt_rewrites(conn: sqlite3.Connection) -> str:
    """Prompt rewrites staged but not applied (F13 byte-mismatch staging)."""
    cutoff = (_now_utc() - timedelta(days=PROMPT_REWRITES_LOOKBACK_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT id, target_path, rationale, created_at FROM prompt_rewrites"
        " WHERE applied = 0 AND created_at >= ?"
        " ORDER BY created_at DESC LIMIT 20",
        (cutoff,),
    ).fetchall()
    out = [_section_header("Prompt rewrites pending review")]
    if not rows:
        out.append("- (none)")
        return "\n".join(out) + "\n"
    for rid, target, rationale, created_at in rows:
        out.append(
            f"- #{rid} {target} ({str(created_at)[:16]}):"
            f" {str(rationale)[:240]}"
        )
    return "\n".join(out) + "\n"


def _section_recent_failures(conn: sqlite3.Connection, since: str, until: str) -> str:
    """Failed WeChat sends + cloud-sync errors."""
    failures = conn.execute(
        "SELECT created_at, recipient, status, detail FROM wechat_log"
        " WHERE status != 'sent' AND created_at >= ? AND created_at < ?"
        " ORDER BY created_at DESC LIMIT 20",
        (since, until),
    ).fetchall()
    out = [_section_header("Recent failures (last 24h)")]
    if not failures:
        out.append("- (none)")
        return "\n".join(out) + "\n"
    for ts, recipient, status, detail in failures:
        out.append(
            f"- [{str(ts)[:16]}] wechat {recipient} {status}:"
            f" {str(detail or '')[:200]}"
        )
    return "\n".join(out) + "\n"


def _section_surprises(conn: sqlite3.Connection, date: str, since: str, until: str) -> str:
    """Flag drift relative to a 7-day baseline."""
    week_ago = (datetime.fromisoformat(since) - timedelta(days=7)).isoformat()

    # Compare 24h cost vs avg of last 7 24h windows
    today_cost = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0) FROM llm_calls"
        " WHERE created_at >= ? AND created_at < ?",
        (since, until),
    ).fetchone()[0]
    week_cost = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0) FROM llm_calls"
        " WHERE created_at >= ? AND created_at < ?",
        (week_ago, since),
    ).fetchone()[0]
    week_daily_avg = float(week_cost) / 7.0 if week_cost else 0.0

    # Anomaly volume
    today_anom = conn.execute(
        "SELECT COUNT(*) FROM price_anomalies WHERE created_at >= ? AND created_at < ?",
        (since, until),
    ).fetchone()[0]
    week_anom = conn.execute(
        "SELECT COUNT(*) FROM price_anomalies WHERE created_at >= ? AND created_at < ?",
        (week_ago, since),
    ).fetchone()[0]
    week_anom_avg = float(week_anom) / 7.0 if week_anom else 0.0

    out = [_section_header("Surprises / drift")]
    if week_daily_avg > 0 and float(today_cost) > 2.0 * week_daily_avg:
        out.append(
            f"- LLM cost spike: today {_fmt_money(float(today_cost))}"
            f" vs 7-day avg {_fmt_money(week_daily_avg)}"
        )
    if week_anom_avg > 0 and float(today_anom) > 2.0 * week_anom_avg:
        out.append(
            f"- Anomaly volume spike: today {today_anom}"
            f" vs 7-day avg {week_anom_avg:.1f}"
        )
    if len(out) == 1:
        out.append("- (no notable drift)")
    return "\n".join(out) + "\n"


def _section_open_questions() -> str:
    """Static prompts to seed the reviewer's thinking."""
    out = [_section_header("Open questions for the reviewer")]
    out.append(
        "1. Are any of the failures above caused by upstream provider changes"
        " (RSS feed format, yfinance API, SEC EDGAR, MiniMax)?\n"
        "2. Do recent boss instructions imply a code change beyond what F13's"
        " prompt-rewriter can do (new feeds, new schedule, new logic)?\n"
        "3. Are pending action-queue items piling up — and if so, is the"
        " runner cron firing? Is there an LLM-call budget issue?\n"
        "4. Any 'pending review' prompt rewrites where the byte-mismatch is"
        " because the prompt template structure has shifted under the rewriter?"
    )
    return "\n".join(out) + "\n"


def compile_daily_packet(
    conn: sqlite3.Connection, *, date: str | None = None
) -> ReviewPacketResult:
    """Compile the full daily review markdown packet and write to disk."""
    # Compute the time window for the report
    target_date, since, until = _date_window(date)

    # Build the markdown body section by section
    parts: list[str] = [f"# Daily review — {target_date}\n"]
    parts.append(f"_Window: {since} -> {until} (UTC)._\n")
    parts.append(_section_health(conn, since, until))
    parts.append(_section_boss_feedback(conn, since, until))
    parts.append(_section_action_queue(conn))
    parts.append(_section_prompt_rewrites(conn))
    parts.append(_section_recent_failures(conn, since, until))
    parts.append(_section_surprises(conn, target_date, since, until))
    parts.append(_section_open_questions())
    body = "".join(parts)

    # Persist to pipeline/daily_review_YYYY-MM-DD.md
    review_dir = Path(REVIEW_DIR)
    review_dir.mkdir(parents=True, exist_ok=True)
    out_path = review_dir / f"daily_review_{target_date}.md"
    out_path.write_text(body, encoding="utf-8")

    return ReviewPacketResult(date=target_date, path=str(out_path), body=body)


@lru_cache(maxsize=1)
def _load_review_prompt() -> tuple[str, str]:
    """Load the self-review prompt template, split on [USER]."""
    path = Path(REVIEW_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Self-review prompt not found at {REVIEW_PROMPT_PATH}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


def propose_via_minimax(
    packet: ReviewPacketResult, conn: sqlite3.Connection
) -> list[ReviewProposal]:
    """Call MiniMax with the packet, parse strict-JSON proposal list."""
    settings = get_settings()
    try:
        check_cost_ceiling(conn, settings)
    except CostCeilingError:
        logger.warning("propose_via_minimax skipped: cost ceiling reached")
        return []

    # Compose the messages
    system_template, user_template = _load_review_prompt()
    user_message = user_template.format(packet=packet.body)
    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]

    # Call MiniMax
    try:
        client = get_client("minimax")
        response: ChatResponse = client.chat(
            messages=messages,
            model=SELF_REVIEW_MODEL,
            max_tokens=SELF_REVIEW_MAX_TOKENS,
            conn=conn,
            caller="self_review.propose",
            cached_system=system_template,
        )
    except CostCeilingError:
        return []
    except Exception:
        logger.exception("propose_via_minimax LLM call failed")
        return []

    # Parse JSON proposals
    try:
        parsed = parse_llm_json(response.content)
    except Exception:
        logger.exception("propose_via_minimax JSON parse failed")
        return []

    raw_items = parsed.get("proposals") if isinstance(parsed, dict) else None
    if not isinstance(raw_items, list):
        logger.warning("propose_via_minimax: no 'proposals' list in response")
        return []

    proposals: list[ReviewProposal] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            proposals.append(
                ReviewProposal(
                    title=str(item.get("title", "")).strip()[:240],
                    rationale=str(item.get("rationale", "")).strip()[:2000],
                    files=[str(f) for f in (item.get("files") or []) if f],
                    diff_or_steps=str(item.get("diff_or_steps", "")).strip()[:8000],
                    impact=str(item.get("impact", "medium")).strip().lower(),
                    risk=str(item.get("risk", "medium")).strip().lower(),
                )
            )
        except Exception:
            logger.exception("Skipping malformed proposal item")
    return proposals


def store_proposals(
    conn: sqlite3.Connection,
    *,
    review_date: str,
    backend: str,
    proposals: list[ReviewProposal],
    cost_usd: float = 0.0,
) -> list[int]:
    """Insert proposals into self_review_proposals and return their IDs."""
    now = _now_utc().isoformat()
    out_ids: list[int] = []
    for p in proposals:
        cursor = conn.execute(
            "INSERT INTO self_review_proposals"
            " (review_date, backend, title, rationale, files_json,"
            " diff_or_steps, impact, risk, cost_usd, applied, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (
                review_date,
                backend,
                p.title,
                p.rationale,
                json.dumps(p.files),
                p.diff_or_steps,
                p.impact,
                p.risk,
                cost_usd,
                now,
            ),
        )
        out_ids.append(int(cursor.lastrowid or 0))
    conn.commit()
    return out_ids


def list_proposals(
    conn: sqlite3.Connection,
    *,
    review_date: str | None = None,
    only_unapplied: bool = True,
    limit: int = 50,
) -> list[dict[str, object]]:
    """List recent self-review proposals as dicts."""
    where: list[str] = []
    args: list[object] = []
    if review_date:
        where.append("review_date = ?")
        args.append(review_date)
    if only_unapplied:
        where.append("applied = 0")
    sql = (
        "SELECT id, review_date, backend, title, rationale, files_json,"
        " diff_or_steps, impact, risk, applied, created_at"
        " FROM self_review_proposals"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, tuple(args)).fetchall()
    out: list[dict[str, object]] = []
    for r in rows:
        out.append(
            {
                "id": int(r[0]),
                "review_date": str(r[1]),
                "backend": str(r[2]),
                "title": str(r[3]),
                "rationale": str(r[4]),
                "files": json.loads(str(r[5])),
                "diff_or_steps": str(r[6]),
                "impact": str(r[7]),
                "risk": str(r[8]),
                "applied": bool(r[9]),
                "created_at": str(r[10]),
            }
        )
    return out


def mark_applied(conn: sqlite3.Connection, proposal_id: int, *, notes: str = "") -> bool:
    """Mark a proposal as applied. Returns False if not found."""
    now = _now_utc().isoformat()
    cursor = conn.execute(
        "UPDATE self_review_proposals SET applied = 1, applied_at = ?, notes = ?"
        " WHERE id = ? AND applied = 0",
        (now, notes, proposal_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def run_daily_review(conn: sqlite3.Connection) -> ReviewPacketResult:
    """Compile today's packet and route to the configured backend(s)."""
    settings = get_settings()
    backend = (getattr(settings, "self_review_backend", "claude_code") or "claude_code").lower()
    if backend not in ALLOWED_BACKENDS:
        logger.warning(
            "Unknown SELF_REVIEW_BACKEND=%s; falling back to claude_code", backend
        )
        backend = "claude_code"

    if backend == "off":
        logger.info("self_review backend=off; skipping")
        return ReviewPacketResult(date=_date_window(None)[0], path="", body="")

    # Always compile + write the packet
    packet = compile_daily_packet(conn)
    logger.info("self_review packet written: %s (%d bytes)", packet.path, len(packet.body))

    # Route to MiniMax when requested
    if backend in ("minimax", "both"):
        proposals = propose_via_minimax(packet, conn)
        if proposals:
            ids = store_proposals(
                conn,
                review_date=packet.date,
                backend="minimax",
                proposals=proposals,
            )
            logger.info(
                "self_review minimax: stored %d proposals (ids=%s)",
                len(proposals),
                ids,
            )
        else:
            logger.info("self_review minimax: no proposals returned")

    return packet
