"""stock.events -- track named event predictions and verify them against incoming news.

F26: boss asked for "make event predictions tracked over time. With more new
incoming, see if our previous predictions on events are correct or not. Add /
edit / delete main events through time. Improve event predictions over time."

This module provides:

  - `tracked_events` table CRUD (add / list / edit / delete)
  - `extract_events_from_research(...)` -- LLM-driven extraction of named
    catalyst events from a fresh research-note body. Operator can also add
    events manually via CLI.
  - `verify_due_events(conn)` -- iterate pending events whose window has closed
    (or whose window is open and there's fresh news), and ask the LLM whether
    the predicted outcome was met. Verdict: hit / miss / partial / unverified.
  - `recent_events_block(conn)` -- markdown for the daily research-note prompt
    so the LLM sees what events are pending + what verdicts just landed.

Schema (db.py):
  ticker, event_type, title, predicted_outcome, window_start, window_end,
  confidence, status (pending|hit|miss|partial|expired|cancelled),
  actual_outcome, evidence_text, evidence_source, source_research_id,
  verdict_at, notes, created_at, updated_at.
"""
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
    MINIMAX_DEFAULT_MODEL,
    ChatMessage,
    ChatResponse,
    CostCeilingError,
    check_cost_ceiling,
    get_client,
    parse_llm_json,
)

logger = logging.getLogger(__name__)

EXTRACT_PROMPT_PATH: str = "prompts/event_extract.txt"
VERIFY_PROMPT_PATH: str = "prompts/event_verify.txt"
EXTRACT_MAX_TOKENS: int = 1200
VERIFY_MAX_TOKENS: int = 600
VALID_STATUSES: tuple[str, ...] = (
    "pending", "hit", "miss", "partial", "expired", "cancelled",
)
VALID_EVENT_TYPES: tuple[str, ...] = (
    "earnings", "guidance", "product_launch", "regulatory", "contract_win",
    "supply_chain", "macro", "insider_action", "policy", "other",
)


class TrackedEvent(BaseModel):
    """One row of the tracked_events table."""

    id: int | None = None
    ticker: str
    event_type: str
    title: str
    predicted_outcome: str
    window_start: str
    window_end: str
    confidence: float = 0.5
    status: str = "pending"
    actual_outcome: str | None = None
    evidence_text: str | None = None
    evidence_source: str | None = None
    evidence_url: str | None = None
    source_research_id: int | None = None
    verdict_at: str | None = None
    notes: str | None = None
    created_at: str = ""
    updated_at: str = ""


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def _coerce_event_type(raw: str) -> str:
    """Snap an LLM/CLI event_type onto VALID_EVENT_TYPES."""
    cleaned = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    return cleaned if cleaned in VALID_EVENT_TYPES else "other"


def _coerce_status(raw: str) -> str:
    """Snap an event status onto VALID_STATUSES."""
    cleaned = (raw or "").strip().lower()
    return cleaned if cleaned in VALID_STATUSES else "pending"


def _row_to_event(row: tuple) -> TrackedEvent:
    """Convert a SELECT row into a TrackedEvent."""
    return TrackedEvent(
        id=int(row[0]),
        ticker=str(row[1]),
        event_type=str(row[2]),
        title=str(row[3]),
        predicted_outcome=str(row[4]),
        window_start=str(row[5]),
        window_end=str(row[6]),
        confidence=float(row[7]),
        status=str(row[8]),
        actual_outcome=row[9],
        evidence_text=row[10],
        evidence_source=row[11],
        evidence_url=row[12],
        source_research_id=row[13],
        verdict_at=row[14],
        notes=row[15],
        created_at=str(row[16]),
        updated_at=str(row[17]),
    )


def add_event(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    event_type: str,
    title: str,
    predicted_outcome: str,
    window_start: str,
    window_end: str,
    confidence: float = 0.5,
    source_research_id: int | None = None,
    notes: str | None = None,
) -> TrackedEvent:
    """Insert a new tracked event. Returns the inserted row."""
    now = datetime.now(timezone.utc).isoformat()
    confidence = max(0.0, min(1.0, float(confidence)))
    cursor = conn.execute(
        "INSERT INTO tracked_events ("
        "  ticker, event_type, title, predicted_outcome, window_start, window_end,"
        "  confidence, status, source_research_id, notes, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
        (
            ticker.upper(), _coerce_event_type(event_type), title.strip(),
            predicted_outcome.strip(), window_start, window_end,
            confidence, source_research_id, notes, now, now,
        ),
    )
    conn.commit()
    return TrackedEvent(
        id=int(cursor.lastrowid or 0), ticker=ticker.upper(),
        event_type=_coerce_event_type(event_type), title=title.strip(),
        predicted_outcome=predicted_outcome.strip(), window_start=window_start,
        window_end=window_end, confidence=confidence, status="pending",
        source_research_id=source_research_id, notes=notes,
        created_at=now, updated_at=now,
    )


def edit_event(
    conn: sqlite3.Connection, event_id: int, **fields: object,
) -> bool:
    """Update fields on an existing event. Returns True if a row was changed."""
    if not fields:
        return False
    allowed = {
        "title", "predicted_outcome", "window_start", "window_end",
        "confidence", "status", "actual_outcome", "evidence_text",
        "evidence_source", "evidence_url", "notes", "event_type",
    }
    sets: list[str] = []
    args: list[object] = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "event_type" and isinstance(v, str):
            v = _coerce_event_type(v)
        if k == "status" and isinstance(v, str):
            v = _coerce_status(v)
        if k == "confidence" and isinstance(v, (int, float)):
            v = max(0.0, min(1.0, float(v)))
        sets.append(f"{k} = ?")
        args.append(v)
    if not sets:
        return False
    sets.append("updated_at = ?")
    args.append(datetime.now(timezone.utc).isoformat())
    args.append(event_id)
    cursor = conn.execute(
        f"UPDATE tracked_events SET {', '.join(sets)} WHERE id = ?",
        tuple(args),
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_event(conn: sqlite3.Connection, event_id: int) -> bool:
    """Hard-delete an event. Returns True if a row was removed."""
    cursor = conn.execute(
        "DELETE FROM tracked_events WHERE id = ?", (event_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def list_events(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    ticker: str | None = None,
    limit: int = 100,
) -> list[TrackedEvent]:
    """Read events matching optional filters, newest-first."""
    where_clauses: list[str] = []
    args: list[object] = []
    if status:
        where_clauses.append("status = ?")
        args.append(_coerce_status(status))
    if ticker:
        where_clauses.append("ticker = ?")
        args.append(ticker.upper())
    where = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    args.append(limit)
    rows = conn.execute(
        "SELECT id, ticker, event_type, title, predicted_outcome,"
        " window_start, window_end, confidence, status, actual_outcome,"
        " evidence_text, evidence_source, evidence_url, source_research_id,"
        " verdict_at, notes, created_at, updated_at"
        f" FROM tracked_events{where}"
        " ORDER BY window_end DESC, id DESC LIMIT ?",
        tuple(args),
    ).fetchall()
    return [_row_to_event(r) for r in rows]


# ---------------------------------------------------------------------------
# Verification (LLM-driven, against post-window news + filings)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_verify_prompt() -> tuple[str, str]:
    """Load + split the verify prompt on [SYSTEM]/[USER] markers."""
    p = Path(VERIFY_PROMPT_PATH)
    if not p.exists():
        raise FileNotFoundError(f"Event-verify prompt not found at {p}")
    text = p.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    return parts[0].replace("[SYSTEM]", "").strip(), parts[1].strip() if len(parts) > 1 else ""


def _build_post_news_block(
    conn: sqlite3.Connection, ticker: str, since_iso: str, *, limit: int = 10,
) -> str:
    """News for `ticker` after `since_iso`, formatted for the verify prompt."""
    rows = conn.execute(
        "SELECT n.ts, n.title, n.body, COALESCE(f.json, '') FROM news n"
        " LEFT JOIN features f ON n.id = f.news_id"
        " WHERE n.ticker = ? AND n.ts >= ?"
        " ORDER BY n.ts DESC LIMIT ?",
        (ticker, since_iso, limit),
    ).fetchall()
    if not rows:
        return "(no post-window news in DB)"
    lines: list[str] = []
    for ts, title, body, feat_json in rows:
        feat: dict[str, object] = {}
        if feat_json:
            try:
                feat = json.loads(feat_json)
            except (json.JSONDecodeError, TypeError):
                feat = {}
        sentiment = feat.get("sentiment", "?")
        body_short = str(body or "")[:300].replace("\n", " ")
        lines.append(
            f"- [{ts[:16]}] {title[:200]}\n"
            f"    sentiment={sentiment} | {body_short}"
        )
    return "\n".join(lines)


def verify_event(
    conn: sqlite3.Connection, event_id: int,
) -> TrackedEvent | None:
    """Grade one pending event against post-window news. Idempotent on done events."""
    rows = conn.execute(
        "SELECT id, ticker, event_type, title, predicted_outcome,"
        " window_start, window_end, confidence, status, actual_outcome,"
        " evidence_text, evidence_source, evidence_url, source_research_id,"
        " verdict_at, notes, created_at, updated_at"
        " FROM tracked_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    if not rows:
        return None
    event = _row_to_event(rows)
    if event.status not in ("pending", "partial"):
        return event  # already finalized

    settings = get_settings()
    try:
        check_cost_ceiling(conn, settings)
    except CostCeilingError:
        logger.warning("event.verify skipped: cost ceiling reached")
        return event

    system_template, user_template = _load_verify_prompt()
    post_news = _build_post_news_block(conn, event.ticker, event.window_start)
    user_message = user_template.format(
        ticker=event.ticker,
        event_type=event.event_type,
        title=event.title,
        predicted_outcome=event.predicted_outcome,
        window_start=event.window_start,
        window_end=event.window_end,
        post_news_block=post_news,
        now_utc=datetime.now(timezone.utc).isoformat(timespec="minutes"),
    )

    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    try:
        client = get_client("minimax")
        response: ChatResponse = client.chat(
            messages=messages,
            model=MINIMAX_DEFAULT_MODEL,
            max_tokens=VERIFY_MAX_TOKENS,
            conn=conn,
            caller="events.verify",
            cached_system=system_template,
        )
    except CostCeilingError:
        return event
    except Exception:
        logger.exception("event.verify LLM call failed for event %d", event_id)
        return event

    try:
        parsed = parse_llm_json(response.content)
    except Exception:
        logger.warning("event.verify: JSON parse failed for event %d", event_id)
        return event

    verdict_raw = str(parsed.get("verdict", "")).strip().lower()
    if verdict_raw not in ("hit", "miss", "partial", "pending"):
        verdict_raw = "pending"
    actual = str(parsed.get("actual_outcome", "") or "")[:1000]
    evidence = str(parsed.get("evidence_text", "") or "")[:1000]
    src = str(parsed.get("evidence_source", "none") or "none")[:64]
    url = str(parsed.get("evidence_url", "") or "")[:500]

    # If verdict is still pending and the window has closed, mark expired
    new_status = verdict_raw
    if new_status == "pending":
        try:
            window_end_dt = datetime.fromisoformat(
                event.window_end.replace("Z", "+00:00")
            )
            if window_end_dt < datetime.now(timezone.utc):
                new_status = "expired"
        except (ValueError, TypeError):
            pass

    edit_event(
        conn, event_id,
        status=new_status, actual_outcome=actual,
        evidence_text=evidence, evidence_source=src, evidence_url=url,
    )
    conn.execute(
        "UPDATE tracked_events SET verdict_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), event_id),
    )
    conn.commit()
    return list_events(conn, status=None, limit=1) and _row_to_event(
        conn.execute(
            "SELECT id, ticker, event_type, title, predicted_outcome,"
            " window_start, window_end, confidence, status, actual_outcome,"
            " evidence_text, evidence_source, evidence_url, source_research_id,"
            " verdict_at, notes, created_at, updated_at"
            " FROM tracked_events WHERE id = ?",
            (event_id,),
        ).fetchone()
    )


def verify_due_events(
    conn: sqlite3.Connection, *, max_items: int = 30,
) -> list[TrackedEvent]:
    """Verify every pending event whose window has started or whose window-end
    has passed. Skips events that are already hit/miss/cancelled."""
    now_iso = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT id FROM tracked_events"
        " WHERE status IN ('pending', 'partial')"
        " AND window_start <= ?"
        " ORDER BY window_end ASC LIMIT ?",
        (now_iso, max_items),
    ).fetchall()
    out: list[TrackedEvent] = []
    for (eid,) in rows:
        try:
            result = verify_event(conn, int(eid))
        except Exception:
            logger.exception("verify_due_events: event %s raised", eid)
            continue
        if result is not None:
            out.append(result)
    return out


# ---------------------------------------------------------------------------
# Prompt-block formatting
# ---------------------------------------------------------------------------


def recent_events_block(
    conn: sqlite3.Connection, *, lookback_days: int = 30, limit: int = 12,
) -> str:
    """Format pending + recently-verified events as a markdown block.

    Used by the daily research prompt so the LLM:
      1. Sees what events are still pending (avoid double-predicting)
      2. Sees recent hits/misses (calibration feedback for next predictions)
    """
    since_iso = (
        datetime.now(timezone.utc) - timedelta(days=lookback_days)
    ).isoformat()
    rows = conn.execute(
        "SELECT id, ticker, event_type, title, predicted_outcome,"
        " window_start, window_end, status, actual_outcome"
        " FROM tracked_events"
        " WHERE status = 'pending'"
        "    OR (status IN ('hit', 'miss', 'partial', 'expired')"
        "        AND COALESCE(verdict_at, updated_at) >= ?)"
        " ORDER BY"
        "   CASE status WHEN 'pending' THEN 0 ELSE 1 END,"
        "   window_end ASC LIMIT ?",
        (since_iso, limit),
    ).fetchall()

    if not rows:
        return "(no tracked events yet -- add via `stock event add`)"

    lines = ["| ID | 状态 | Ticker | 类型 | 事件 | 预测结果 | 窗口结束 | 实际结果 |",
             "| ---: | --- | --- | --- | --- | --- | --- | --- |"]
    status_label = {
        "pending": "⏳ 等待",
        "hit": "✅ 命中",
        "miss": "❌ 未中",
        "partial": "🟡 部分",
        "expired": "⌛ 过期",
        "cancelled": "🚫 取消",
    }
    for r in rows:
        eid, ticker, etype, title, pred, win_start, win_end, status, actual = r
        actual_short = (str(actual) if actual else "—")[:60]
        lines.append(
            f"| {eid} | {status_label.get(status, status)} | {ticker}"
            f" | {etype} | {title[:50]} | {pred[:60]}"
            f" | {win_end[:10]} | {actual_short} |"
        )
    return "\n".join(lines)


def event_calibration_summary(
    conn: sqlite3.Connection, *, lookback_days: int = 90,
) -> dict[str, float | int]:
    """Aggregate hit-rate stats over the last N days.

    Returned for the daily research prompt so the LLM can self-calibrate
    its confidence on future event predictions.
    """
    since_iso = (
        datetime.now(timezone.utc) - timedelta(days=lookback_days)
    ).isoformat()
    rows = conn.execute(
        "SELECT status, confidence FROM tracked_events"
        " WHERE COALESCE(verdict_at, updated_at) >= ?"
        " AND status IN ('hit', 'miss', 'partial', 'expired')",
        (since_iso,),
    ).fetchall()
    total = len(rows)
    hits = sum(1 for r in rows if r[0] == "hit")
    misses = sum(1 for r in rows if r[0] == "miss")
    partials = sum(1 for r in rows if r[0] == "partial")
    expired = sum(1 for r in rows if r[0] == "expired")
    confs = [float(r[1]) for r in rows if r[1] is not None]
    avg_conf = sum(confs) / len(confs) if confs else 0.0
    hit_rate = hits / total if total else 0.0
    # Brier-like calibration: are high-confidence predictions hitting more often?
    return {
        "total_resolved": total,
        "hits": hits,
        "misses": misses,
        "partials": partials,
        "expired": expired,
        "hit_rate": round(hit_rate, 3),
        "avg_confidence_when_resolved": round(avg_conf, 3),
        "lookback_days": lookback_days,
    }
