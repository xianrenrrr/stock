"""stock.thesis -- atomic claim extraction + post-hoc verification for predictions.

Implements the F16 reviewing system. Decomposes each prediction's rationale into
typed, decontextualized, falsifiable claims (Trading-R1 schema + Ullrich 2025
metrics), and after the move is in verifies each claim against post-window news,
insider filings, anomalies, and price action (SAFE 2024 verdict trichotomy).

Surfaces "right direction wrong reason" as the headline model-improvement signal.
See docs/research_notes/2026-05-01_thesis_grading_papers.md for the full citation map.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from stock.config import get_settings
from stock.ingest.insiders import format_insider_block, recent_for_ticker
from stock.models import (
    ChatMessage,
    ChatResponse,
    CostCeilingError,
    check_cost_ceiling,
    get_core_client,
    get_core_model,
    parse_llm_json,
)

logger = logging.getLogger(__name__)

THESIS_EXTRACT_PROMPT_PATH: str = "prompts/thesis_extract.txt"
THESIS_VERIFY_PROMPT_PATH: str = "prompts/thesis_verify.txt"
THESIS_EXTRACT_MAX_TOKENS: int = 700
THESIS_VERIFY_MAX_TOKENS: int = 350
POST_NEWS_LOOKBACK_HOURS: int = 96
POST_NEWS_LIMIT: int = 12
ANOMALY_LOOKBACK_DAYS: int = 5
INSIDER_LOOKBACK_DAYS: int = 14
VALID_CLAIM_TYPES: tuple[str, ...] = (
    "catalyst", "valuation", "technical", "macro", "sentiment", "supply_chain",
)
VALID_VERDICTS: tuple[str, ...] = ("supported", "refuted", "unverified")
VALID_CHAIN: tuple[str, ...] = ("supports", "contradicts", "neutral")


class ThesisRow(BaseModel):
    """One row of the prediction_theses table."""

    id: int | None = None
    prediction_id: int
    claim_text: str
    claim_type: str
    verifiable_by: str | None = None
    chain_consistency: str | None = None
    chain_consistency_reason: str | None = None
    verdict: str | None = None
    confidence: float | None = None
    evidence_text: str | None = None
    evidence_source: str | None = None
    graded_at: str | None = None
    created_at: str = ""


class ThesisStats(BaseModel):
    """Aggregated thesis grading stats for a window."""

    total: int
    supported: int
    refuted: int
    unverified: int
    pending: int
    right_direction_wrong_reason: int
    by_type: dict[str, dict[str, int]]


@lru_cache(maxsize=1)
def _load_extract_prompt() -> tuple[str, str]:
    """Load and split the thesis-extract prompt on [SYSTEM]/[USER] markers."""
    path = Path(THESIS_EXTRACT_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Thesis-extract prompt not found at {path}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    return parts[0].replace("[SYSTEM]", "").strip(), parts[1].strip() if len(parts) > 1 else ""


@lru_cache(maxsize=1)
def _load_verify_prompt() -> tuple[str, str]:
    """Load and split the thesis-verify prompt on [SYSTEM]/[USER] markers."""
    path = Path(THESIS_VERIFY_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Thesis-verify prompt not found at {path}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    return parts[0].replace("[SYSTEM]", "").strip(), parts[1].strip() if len(parts) > 1 else ""


def _coerce_claim_type(raw: str) -> str:
    """Snap an LLM-emitted claim_type onto VALID_CLAIM_TYPES, default 'sentiment'."""
    cleaned = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    return cleaned if cleaned in VALID_CLAIM_TYPES else "sentiment"


def _coerce_verdict(raw: str) -> str:
    """Snap an LLM-emitted verdict onto VALID_VERDICTS, default 'unverified'."""
    cleaned = (raw or "").strip().lower()
    return cleaned if cleaned in VALID_VERDICTS else "unverified"


def _coerce_chain(raw: str) -> str:
    """Snap an LLM-emitted chain_consistency onto VALID_CHAIN, default 'neutral'."""
    cleaned = (raw or "").strip().lower()
    return cleaned if cleaned in VALID_CHAIN else "neutral"


def _row_to_thesis(row: tuple[Any, ...]) -> ThesisRow:
    """Convert a SELECT row into a ThesisRow."""
    return ThesisRow(
        id=int(row[0]),
        prediction_id=int(row[1]),
        claim_text=str(row[2]),
        claim_type=str(row[3]),
        verifiable_by=row[4],
        chain_consistency=row[5],
        chain_consistency_reason=row[6],
        verdict=row[7],
        confidence=row[8],
        evidence_text=row[9],
        evidence_source=row[10],
        graded_at=row[11],
        created_at=str(row[12]),
    )


def list_for_prediction(
    conn: sqlite3.Connection, prediction_id: int
) -> list[ThesisRow]:
    """Return all theses tied to a prediction in insertion order."""
    rows = conn.execute(
        "SELECT id, prediction_id, claim_text, claim_type, verifiable_by,"
        " chain_consistency, chain_consistency_reason, verdict, confidence,"
        " evidence_text, evidence_source, graded_at, created_at"
        " FROM prediction_theses WHERE prediction_id = ? ORDER BY id ASC",
        (prediction_id,),
    ).fetchall()
    return [_row_to_thesis(r) for r in rows]


def extract_theses(
    prediction_id: int, conn: sqlite3.Connection
) -> list[ThesisRow]:
    """Decompose a prediction's rationale into atomic claims via MiniMax.

    Idempotent in the sense that if rows already exist for prediction_id, this
    returns them without re-calling the LLM. Failures (cost ceiling, JSON
    parse) are non-fatal: returns an empty list and lets the caller proceed
    with whatever was already persisted.
    """
    existing = list_for_prediction(conn, prediction_id)
    if existing:
        return existing

    pred_row = conn.execute(
        "SELECT ticker, direction, prob_up, rationale, key_factors_json, created_at"
        " FROM predictions WHERE id = ?",
        (prediction_id,),
    ).fetchone()
    if pred_row is None:
        raise ValueError(f"Prediction {prediction_id} not found")
    ticker, direction, prob_up, rationale, key_factors_json, created_at = pred_row

    settings = get_settings()
    try:
        check_cost_ceiling(conn, settings)
    except CostCeilingError:
        logger.warning("thesis.extract skipped: cost ceiling reached")
        return []

    system_template, user_template = _load_extract_prompt()
    user_message = user_template.format(
        ticker=ticker,
        direction=direction,
        prob_up=f"{float(prob_up):.2f}",
        created_at=created_at,
        rationale=str(rationale or "").strip() or "(no rationale)",
        key_factors=str(key_factors_json or "[]"),
    )

    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    try:
        client = get_core_client()
        response: ChatResponse = client.chat(
            messages=messages,
            model=get_core_model(),
            max_tokens=THESIS_EXTRACT_MAX_TOKENS,
            conn=conn,
            caller="thesis.extract",
            cached_system=system_template,
        )
    except CostCeilingError:
        return []
    except Exception:
        logger.exception("thesis.extract LLM call failed")
        return []

    try:
        parsed = parse_llm_json(response.content)
    except Exception:
        logger.warning("thesis.extract: JSON parse failed; raw=%r", response.content[:200])
        return []

    raw_claims = parsed.get("claims") if isinstance(parsed, dict) else None
    if not isinstance(raw_claims, list) or not raw_claims:
        logger.warning("thesis.extract: no 'claims' list in response")
        return []

    chain_consistency = _coerce_chain(str(parsed.get("chain_consistency", "neutral")))
    chain_reason = str(parsed.get("chain_consistency_reason", "") or "")[:500]

    now = datetime.now(timezone.utc).isoformat()
    inserted: list[ThesisRow] = []
    for raw in raw_claims[:5]:
        if not isinstance(raw, dict):
            continue
        claim_text = str(raw.get("claim_text", "")).strip()[:500]
        if not claim_text:
            continue
        claim_type = _coerce_claim_type(str(raw.get("claim_type", "")))
        verifiable_by = str(raw.get("verifiable_by", "") or "")[:120] or None

        cursor = conn.execute(
            "INSERT INTO prediction_theses ("
            "  prediction_id, claim_text, claim_type, verifiable_by,"
            "  chain_consistency, chain_consistency_reason, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (prediction_id, claim_text, claim_type, verifiable_by,
             chain_consistency, chain_reason, now),
        )
        inserted.append(ThesisRow(
            id=int(cursor.lastrowid or 0),
            prediction_id=prediction_id,
            claim_text=claim_text,
            claim_type=claim_type,
            verifiable_by=verifiable_by,
            chain_consistency=chain_consistency,
            chain_consistency_reason=chain_reason,
            created_at=now,
        ))
    conn.commit()
    return inserted


def _build_post_news_block(
    conn: sqlite3.Connection, *, ticker: str, since_iso: str, limit: int = POST_NEWS_LIMIT,
) -> str:
    """Pull news for the ticker filed after the prediction was made."""
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
        feat: dict[str, Any] = {}
        if feat_json:
            try:
                feat = json.loads(feat_json)
            except (json.JSONDecodeError, TypeError):
                feat = {}
        sentiment = feat.get("sentiment", "?")
        catalyst = feat.get("catalyst_type", "?")
        body_short = str(body or "")[:300].replace("\n", " ")
        lines.append(
            f"- [{ts[:16]}] {title[:200]}\n"
            f"    sentiment={sentiment} catalyst={catalyst}\n"
            f"    {body_short}"
        )
    return "\n".join(lines)


def _build_anomaly_block(
    conn: sqlite3.Connection, *, ticker: str, since_iso: str
) -> str:
    """Pull anomaly flags for the ticker after the prediction was made."""
    rows = conn.execute(
        "SELECT ts, pct_change, volume_ratio, flag_reason FROM price_anomalies"
        " WHERE ticker = ? AND ts >= ?"
        " ORDER BY ts DESC LIMIT 10",
        (ticker, since_iso[:10]),
    ).fetchall()
    if not rows:
        return "(no post-window anomalies)"
    return "\n".join(
        f"- [{ts}] pct={pct * 100:+.2f}% vol={vol:.2f}x reason={reason}"
        for ts, pct, vol, reason in rows
    )


def verify_thesis(
    thesis_id: int, conn: sqlite3.Connection
) -> ThesisRow | None:
    """Grade a single thesis against post-window evidence; persist verdict.

    Idempotent on already-graded rows. Returns None if the underlying prediction
    has no outcome yet (we need the actual_return to do the grading).
    """
    row = conn.execute(
        "SELECT t.id, t.prediction_id, t.claim_text, t.claim_type, t.verifiable_by,"
        " t.verdict, p.ticker, p.direction, p.created_at, p.due_at,"
        " o.actual_return, o.direction_hit"
        " FROM prediction_theses t"
        " JOIN predictions p ON p.id = t.prediction_id"
        " LEFT JOIN outcomes o ON o.prediction_id = p.id"
        " WHERE t.id = ?",
        (thesis_id,),
    ).fetchone()
    if row is None:
        return None

    (tid, pid, claim_text, claim_type, verifiable_by, existing_verdict,
     ticker, direction, created_at, due_at, actual_return, direction_hit) = row

    if existing_verdict in VALID_VERDICTS:
        return list_for_prediction(conn, pid)[0]  # already graded

    if actual_return is None:
        # outcome row not yet present
        return None

    settings = get_settings()
    try:
        check_cost_ceiling(conn, settings)
    except CostCeilingError:
        logger.warning("thesis.verify skipped: cost ceiling reached")
        return None

    post_news = _build_post_news_block(conn, ticker=ticker, since_iso=created_at)
    insiders = format_insider_block(
        recent_for_ticker(conn, ticker, days=INSIDER_LOOKBACK_DAYS)
    )
    anomalies = _build_anomaly_block(conn, ticker=ticker, since_iso=created_at)

    system_template, user_template = _load_verify_prompt()
    user_message = user_template.format(
        ticker=ticker,
        claim_text=claim_text,
        claim_type=claim_type,
        verifiable_by=verifiable_by or "unspecified",
        created_at=created_at,
        direction=direction,
        due_at=due_at,
        actual_return=f"{float(actual_return):+.2%}",
        direction_hit="YES" if direction_hit else "NO",
        post_news_block=post_news,
        insider_block=insiders,
        anomaly_block=anomalies,
    )

    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    try:
        client = get_core_client()
        response: ChatResponse = client.chat(
            messages=messages,
            model=get_core_model(),
            max_tokens=THESIS_VERIFY_MAX_TOKENS,
            conn=conn,
            caller="thesis.verify",
            cached_system=system_template,
        )
    except CostCeilingError:
        return None
    except Exception:
        logger.exception("thesis.verify LLM call failed for thesis %d", tid)
        return None

    try:
        parsed = parse_llm_json(response.content)
    except Exception:
        logger.warning("thesis.verify: JSON parse failed for thesis %d", tid)
        return None

    verdict = _coerce_verdict(str(parsed.get("verdict", "unverified")))
    confidence_raw = parsed.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    except (TypeError, ValueError):
        confidence = 0.0
    evidence_text = str(parsed.get("evidence_text", "") or "")[:1000]
    evidence_source = str(parsed.get("evidence_source", "none") or "none")[:64]

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE prediction_theses SET verdict = ?, confidence = ?,"
        " evidence_text = ?, evidence_source = ?, graded_at = ?"
        " WHERE id = ?",
        (verdict, confidence, evidence_text, evidence_source, now, tid),
    )
    conn.commit()

    return ThesisRow(
        id=tid, prediction_id=pid, claim_text=claim_text, claim_type=claim_type,
        verifiable_by=verifiable_by, verdict=verdict, confidence=confidence,
        evidence_text=evidence_text, evidence_source=evidence_source,
        graded_at=now, created_at="",
    )


def verify_due_theses(
    conn: sqlite3.Connection, *, max_items: int = 30
) -> list[ThesisRow]:
    """Verify every ungraded thesis whose underlying prediction is now scored."""
    rows = conn.execute(
        "SELECT t.id FROM prediction_theses t"
        " JOIN outcomes o ON o.prediction_id = t.prediction_id"
        " WHERE t.verdict IS NULL"
        " ORDER BY o.scored_at DESC, t.id DESC LIMIT ?",
        (max_items,),
    ).fetchall()
    graded: list[ThesisRow] = []
    for (tid,) in rows:
        try:
            result = verify_thesis(int(tid), conn)
        except Exception:
            logger.exception("verify_due_theses: thesis %s raised", tid)
            continue
        if result is not None:
            graded.append(result)
    return graded


def compute_thesis_stats(
    conn: sqlite3.Connection, *, hours: int = 36
) -> ThesisStats:
    """Aggregate thesis verdicts over a recent window for the grading note."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    rows = conn.execute(
        "SELECT t.claim_type, t.verdict, t.prediction_id, o.direction_hit"
        " FROM prediction_theses t"
        " JOIN predictions p ON p.id = t.prediction_id"
        " LEFT JOIN outcomes o ON o.prediction_id = p.id"
        " WHERE p.created_at >= ?",
        (cutoff,),
    ).fetchall()

    total = len(rows)
    supported = sum(1 for r in rows if r[1] == "supported")
    refuted = sum(1 for r in rows if r[1] == "refuted")
    unverified = sum(1 for r in rows if r[1] == "unverified")
    pending = sum(1 for r in rows if r[1] not in VALID_VERDICTS)

    # Right direction wrong reason: prediction direction was a hit, but a
    # catalyst|valuation|macro|supply_chain claim was refuted.
    rdwr_pred_ids: set[int] = set()
    for claim_type, verdict, pid, hit in rows:
        if verdict == "refuted" and hit == 1 and claim_type in (
            "catalyst", "valuation", "macro", "supply_chain"
        ):
            rdwr_pred_ids.add(int(pid))

    by_type: dict[str, dict[str, int]] = {}
    for ct in VALID_CLAIM_TYPES:
        sub = [r for r in rows if r[0] == ct]
        by_type[ct] = {
            "total": len(sub),
            "supported": sum(1 for r in sub if r[1] == "supported"),
            "refuted": sum(1 for r in sub if r[1] == "refuted"),
            "unverified": sum(1 for r in sub if r[1] == "unverified"),
        }

    return ThesisStats(
        total=total,
        supported=supported,
        refuted=refuted,
        unverified=unverified,
        pending=pending,
        right_direction_wrong_reason=len(rdwr_pred_ids),
        by_type=by_type,
    )


def format_thesis_block(stats: ThesisStats) -> str:
    """Render thesis stats as a compact markdown block for the grading note."""
    if stats.total == 0:
        return "(no theses graded in window)"

    lines = [
        f"Total claims: {stats.total} (supported={stats.supported},"
        f" refuted={stats.refuted}, unverified={stats.unverified},"
        f" pending={stats.pending})",
        f"Right direction wrong reason: {stats.right_direction_wrong_reason} prediction(s)",
        "By claim type:",
    ]
    for ct in VALID_CLAIM_TYPES:
        sub = stats.by_type.get(ct, {})
        if not sub.get("total"):
            continue
        lines.append(
            f"  - {ct}: {sub.get('supported', 0)}/{sub.get('total', 0)} supported,"
            f" {sub.get('refuted', 0)} refuted, {sub.get('unverified', 0)} unverified"
        )
    return "\n".join(lines)


def format_theses_inline(theses: list[ThesisRow]) -> str:
    """Render an ordered list of theses as a short inline block (for replies/research)."""
    if not theses:
        return "(no theses)"
    lines = []
    for t in theses:
        verdict_tag = f"[{t.verdict}]" if t.verdict else "[pending]"
        lines.append(
            f"- {verdict_tag} ({t.claim_type}) {t.claim_text[:240]}"
        )
    return "\n".join(lines)
