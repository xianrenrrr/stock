"""Daily grade-and-reply: refresh prices, score, summarize, queue follow-ups."""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

from stock import action_queue, emailer, holdings, prompt_rewriter, thesis
from stock.config import get_settings
from stock.ingest import fetch_prices
from stock.models import (
    ChatMessage,
    ChatResponse,
    check_cost_ceiling,
    get_core_client,
    get_core_model,
)
from stock.score import score_due

logger = logging.getLogger(__name__)

GRADING_PROMPT_PATH: str = "prompts/grading.txt"
RULES_DIR: str = "data/rules"
WATCHLIST_PATH: str = "data/watchlist.yaml"
GRADING_MAX_TOKENS: int = 2200
GRADING_MAX_CHARS: int = 2800
DEFAULT_LOOKBACK_HOURS: int = 36
PRICE_HISTORY_DAYS: int = 5
AUTO_IMPROVE_RULES_PATH: str = "data/rules/current.md"


class OutcomeRow(BaseModel):
    """One scored prediction with its outcome, used for grading."""

    prediction_id: int
    ticker: str
    direction: str
    prob_up: float
    prob_up_calibrated: float | None
    confidence: float
    rationale: str
    model_used: str
    strategy_arm: str | None
    actual_return: float
    direction_hit: int
    brier: float
    created_at: str
    due_at: str
    scored_at: str


class PriceRefreshResult(BaseModel):
    """Summary of the per-ticker price refresh step."""

    tickers: list[str]
    inserted_total: int
    failed: list[str]


class GradingStats(BaseModel):
    """Aggregated stats over the recent outcomes window."""

    total: int
    hits: int
    hit_rate: float
    mean_brier: float
    mean_calibrated_brier: float | None
    biggest_win: OutcomeRow | None
    biggest_loss: OutcomeRow | None
    confident_misses: int


class GradingNote(BaseModel):
    """Result of a generate_grading_note run."""

    research_id: int
    body: str
    cost_usd: float
    refreshed: PriceRefreshResult
    stats: GradingStats
    follow_ups_queued: int
    rewrites_applied: int = 0
    rewrites_staged: int = 0
    created_at: str


def _load_active_tickers(conn: sqlite3.Connection) -> list[str]:
    """Return the union of active watchlist tickers + active holdings tickers."""
    # Active watchlist from DB, fallback to YAML
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE active = 1 ORDER BY ticker"
    ).fetchall()
    tickers: set[str] = {str(r[0]).upper() for r in rows} if rows else set()

    if not tickers:
        path = Path(WATCHLIST_PATH)
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("tickers"), list):
                tickers.update(str(t).upper() for t in raw["tickers"] if t)

    # Add active holdings -- some may not be on the watchlist
    for h in holdings.list_holdings(conn, active_only=True):
        tickers.add(h.ticker.upper())

    return sorted(tickers)


def refresh_prices_for_all(
    conn: sqlite3.Connection, *, days: int = PRICE_HISTORY_DAYS
) -> PriceRefreshResult:
    """Pull fresh daily OHLCV bars for every active watchlist + holdings ticker."""
    tickers = _load_active_tickers(conn)
    inserted_total = 0
    failed: list[str] = []

    for ticker in tickers:
        try:
            result = fetch_prices(ticker, conn, days=days)
            inserted_total += result.inserted
        except Exception as exc:  # noqa: BLE001 -- surface and continue
            logger.warning("grading: price refresh failed for %s: %s", ticker, exc)
            failed.append(ticker)

    return PriceRefreshResult(
        tickers=tickers, inserted_total=inserted_total, failed=failed
    )


def recent_outcomes(
    conn: sqlite3.Connection, *, hours: int = DEFAULT_LOOKBACK_HOURS
) -> list[OutcomeRow]:
    """Return scored predictions whose scored_at falls within the lookback window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    rows = conn.execute(
        "SELECT p.id, p.ticker, p.direction, p.prob_up, p.prob_up_calibrated,"
        " p.confidence, p.rationale, p.model_used, p.strategy_arm,"
        " o.actual_return, o.direction_hit, o.brier,"
        " p.created_at, p.due_at, o.scored_at"
        " FROM predictions p"
        " JOIN outcomes o ON p.id = o.prediction_id"
        " WHERE o.scored_at >= ?"
        " ORDER BY o.scored_at DESC, p.id DESC",
        (cutoff,),
    ).fetchall()

    return [
        OutcomeRow(
            prediction_id=r[0],
            ticker=r[1],
            direction=r[2],
            prob_up=r[3],
            prob_up_calibrated=r[4],
            confidence=r[5],
            rationale=r[6],
            model_used=r[7],
            strategy_arm=r[8],
            actual_return=r[9],
            direction_hit=r[10],
            brier=r[11],
            created_at=r[12],
            due_at=r[13],
            scored_at=r[14],
        )
        for r in rows
    ]


def compute_stats(rows: list[OutcomeRow]) -> GradingStats:
    """Compute hit rate, mean Brier, biggest win/loss, confident-miss count."""
    total = len(rows)
    if total == 0:
        return GradingStats(
            total=0, hits=0, hit_rate=0.0, mean_brier=0.0,
            mean_calibrated_brier=None, biggest_win=None, biggest_loss=None,
            confident_misses=0,
        )

    hits = sum(1 for r in rows if r.direction_hit)
    hit_rate = hits / total
    mean_brier = sum(r.brier for r in rows) / total

    cal_briers: list[float] = []
    for r in rows:
        if r.prob_up_calibrated is None:
            continue
        went_up = r.actual_return > 0.0
        prob = max(0.0, min(1.0, r.prob_up_calibrated))
        cal_briers.append((prob - (1.0 if went_up else 0.0)) ** 2)
    mean_cal: float | None = (
        sum(cal_briers) / len(cal_briers) if cal_briers else None
    )

    # Biggest win = highest actual return among hits
    hit_rows = [r for r in rows if r.direction_hit]
    biggest_win = (
        max(hit_rows, key=lambda r: r.actual_return) if hit_rows else None
    )

    # Biggest loss = lowest actual return among misses (most negative for 'up' miss,
    # most positive for 'down' miss; we measure by absolute return magnitude)
    miss_rows = [r for r in rows if not r.direction_hit]
    biggest_loss = (
        max(miss_rows, key=lambda r: abs(r.actual_return)) if miss_rows else None
    )

    # Confident-miss = miss with prob_up >= 0.7 (for 'up' calls) or <= 0.3 (for 'down')
    confident_misses = sum(
        1 for r in rows
        if not r.direction_hit and (
            (r.direction == "up" and r.prob_up >= 0.7)
            or (r.direction == "down" and r.prob_up <= 0.3)
        )
    )

    return GradingStats(
        total=total,
        hits=hits,
        hit_rate=hit_rate,
        mean_brier=mean_brier,
        mean_calibrated_brier=mean_cal,
        biggest_win=biggest_win,
        biggest_loss=biggest_loss,
        confident_misses=confident_misses,
    )


def _format_outcomes_block(rows: list[OutcomeRow]) -> str:
    """Render scored predictions as one bullet per row for the prompt."""
    if not rows:
        return "(no scored predictions in the lookback window)"

    lines: list[str] = []
    for r in rows:
        cal = (
            f" (cal={r.prob_up_calibrated:.2f})"
            if r.prob_up_calibrated is not None else ""
        )
        hit_tag = "HIT" if r.direction_hit else "MISS"
        lines.append(
            f"- [{r.created_at[:10]}] {r.ticker} {r.direction}"
            f" prob_up={r.prob_up:.2f}{cal} conf={r.confidence:.2f}"
            f" -> actual={r.actual_return:+.2%} brier={r.brier:.3f} {hit_tag}\n"
            f"    rationale: {r.rationale[:240]}"
        )
    return "\n".join(lines)


def _format_stats_block(stats: GradingStats) -> str:
    """Render aggregated stats as a compact human-readable block."""
    if stats.total == 0:
        return "(no scored predictions in the lookback window)"

    lines = [
        f"Total scored: {stats.total}",
        f"Hits: {stats.hits} ({stats.hit_rate:.1%})",
        f"Mean Brier (raw): {stats.mean_brier:.4f}",
    ]
    if stats.mean_calibrated_brier is not None:
        lines.append(f"Mean Brier (calibrated): {stats.mean_calibrated_brier:.4f}")
    lines.append(f"Confident misses (prob>=0.7 wrong way): {stats.confident_misses}")

    if stats.biggest_win:
        bw = stats.biggest_win
        lines.append(
            f"Biggest win: {bw.ticker} {bw.direction} prob={bw.prob_up:.2f}"
            f" actual={bw.actual_return:+.2%}"
        )
    if stats.biggest_loss:
        bl = stats.biggest_loss
        lines.append(
            f"Biggest loss: {bl.ticker} {bl.direction} prob={bl.prob_up:.2f}"
            f" actual={bl.actual_return:+.2%}"
        )
    return "\n".join(lines)


def _format_error_patterns(conn: sqlite3.Connection, *, hours: int) -> str:
    """Systematic error breakdowns so the grading LLM targets MEASURED weaknesses
    (worst direction/confidence bucket, calibration verdict, trend) -- not vibes."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    def _rate(extra_sql: str, *params: object) -> tuple[int, float | None]:
        row = conn.execute(
            "SELECT COUNT(*), AVG(o.direction_hit) FROM predictions p"
            " JOIN outcomes o ON p.id = o.prediction_id"
            f" WHERE o.scored_at >= ? {extra_sql}",
            (cutoff, *params),
        ).fetchone()
        n = int(row[0] or 0)
        return n, (round(float(row[1]) * 100, 1) if n and row[1] is not None else None)

    lines = ["系统性误差 / Systematic error patterns (base improvement directions on these):"]
    for d in ("up", "down"):
        n, h = _rate("AND p.direction = ?", d)
        if n:
            lines.append(f"- {d}-calls: n={n} hit={h}%")
    for label, lo, hi in (("high>=.7", 0.7, 1.01), ("med.55-.7", 0.55, 0.7), ("low<.55", 0.0, 0.55)):
        n, h = _rate("AND p.confidence >= ? AND p.confidence < ?", lo, hi)
        if n:
            lines.append(f"- conf {label}: n={n} hit={h}%")

    cal = conn.execute(
        "SELECT helps, brier_raw, brier_cal FROM calibration ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if cal and cal[1] is not None:
        verdict = "HELPS" if cal[0] else "DOES NOT help (raw is used)"
        lines.append(
            f"- calibration: {verdict} (holdout brier raw={cal[1]:.4f} cal={cal[2]:.4f})"
        )

    # Trend: most-recent half vs the prior half of the window.
    mid = (datetime.now(timezone.utc) - timedelta(hours=hours / 2)).isoformat()
    recent_n, recent_h = _rate("AND o.scored_at >= ?", mid)
    prior = conn.execute(
        "SELECT COUNT(*), AVG(o.direction_hit) FROM predictions p"
        " JOIN outcomes o ON p.id = o.prediction_id"
        " WHERE o.scored_at >= ? AND o.scored_at < ?",
        (cutoff, mid),
    ).fetchone()
    prior_n = int(prior[0] or 0)
    if recent_h is not None and prior_n and prior[1] is not None:
        arrow = "improving" if recent_h > prior[1] * 100 else "declining/flat"
        lines.append(
            f"- trend: prior-half hit={round(prior[1]*100,1)}% -> recent-half hit={recent_h}% ({arrow})"
        )
    return "\n".join(lines)


def _format_refresh_block(refreshed: PriceRefreshResult) -> str:
    """Render the price-refresh result as a one-line summary."""
    if not refreshed.tickers:
        return "(no active tickers to refresh)"
    fail_str = (
        f" failed: {', '.join(refreshed.failed)}" if refreshed.failed else ""
    )
    return (
        f"Refreshed {len(refreshed.tickers)} tickers,"
        f" {refreshed.inserted_total} new bars inserted.{fail_str}"
    )


@lru_cache(maxsize=1)
def _load_grading_prompt() -> tuple[str, str]:
    """Load and split the grading prompt into [SYSTEM]/[USER] sections."""
    path = Path(GRADING_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Grading prompt not found at {GRADING_PROMPT_PATH}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


def _load_current_rules() -> str:
    """Read the current rules document for inclusion in the grading prompt."""
    path = Path(RULES_DIR) / "current.md"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return "(no rules established yet)"


def _persist_grading(
    conn: sqlite3.Connection, *, body: str, cost_usd: float
) -> tuple[int, str]:
    """Insert the grading body as a research_reports row of kind='grading'."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO research_reports (kind, topic, layer_focus, body, cost_usd, created_at)"
        " VALUES ('grading', NULL, NULL, ?, ?, ?)",
        (body, cost_usd, now),
    )
    conn.commit()
    return int(cursor.lastrowid or 0), now


def _empty_grading_body(refreshed: PriceRefreshResult, lookback_hours: int) -> str:
    """Build a minimal note when no predictions were scored in the window."""
    refresh_line = _format_refresh_block(refreshed)
    return (
        f"# 每日评分 / Daily grading\n\n"
        f"## 价格刷新 / Price refresh\n{refresh_line}\n\n"
        f"## 评分 / Grading\n"
        f"过去 {lookback_hours} 小时内没有已评分的预测。"
        f" Skipping LLM analysis to save cost.\n\n"
        f"Not financial advice."
    )


_MODEL_IMPROVEMENT_HEADING_RE = re.compile(
    r"(?im)^[ \t]*(?:#{1,4}\s*)?(?:\d+[.)]\s*)?"
    r".*(?:模型改进方向|model\s+improvement\s+directions).*$"
)
_NEXT_SECTION_RE = re.compile(r"(?m)^[ \t]*(?:#{1,4}\s+|\d+[.)]\s+)")


def _extract_model_improvement_section(body: str) -> str:
    """Return the grading note's model-improvement section, or empty string."""
    match = _MODEL_IMPROVEMENT_HEADING_RE.search(body)
    if not match:
        return ""
    rest = body[match.start():]
    next_match = _NEXT_SECTION_RE.search(rest, pos=1)
    section = rest if next_match is None else rest[: next_match.start()]
    return section.strip()


def _auto_apply_model_improvements(
    conn: sqlite3.Connection, *, grading_body: str, research_id: int
) -> tuple[int, int]:
    """Turn concrete grading improvements into prompt/rule rewrites."""
    section = _extract_model_improvement_section(grading_body)
    if not section:
        return 0, 0

    instruction = (
        "System-generated grading note improvement. Convert only the concrete, "
        "evidence-backed items in the Model Improvement Directions section into "
        "surgical edits to data/rules/current.md or prompts/research.txt. "
        "If the section is vague, unsupported, or only asks for more research, "
        "emit <no_changes>."
    )
    context = (
        f"Source research_reports.id={research_id}\n\n"
        f"{section}\n\n"
        "Full grading note for evidence context:\n"
        f"{grading_body[:6000]}"
    )

    proposals = prompt_rewriter.propose_rewrite_from_text(
        instruction_summary=instruction,
        context_excerpt=context,
        conn=conn,
        caller="grading.auto_improve",
    )
    applied = staged = 0
    for proposal in proposals[:3]:
        rewrite_id = prompt_rewriter.apply_rewrite(proposal, conn, force=True)
        if rewrite_id is None:
            continue
        row = conn.execute(
            "SELECT applied FROM prompt_rewrites WHERE id = ?",
            (rewrite_id,),
        ).fetchone()
        if row and int(row[0]) == 1:
            applied += 1
        else:
            staged += 1
    if applied == 0:
        _append_model_improvements_to_rules(
            section=section, research_id=research_id,
        )
        applied += 1
    return applied, staged


def _append_model_improvements_to_rules(*, section: str, research_id: int) -> None:
    """Aggressive fallback: make grading lessons visible to the next prediction.

    The byte-exact rewriter is still preferred because it can edit existing
    rules cleanly. If it refuses or stages only, append the grading-derived
    section verbatim to current rules so the prediction prompt receives it on
    the next run.
    """
    if not section.strip():
        return
    path = Path(AUTO_IMPROVE_RULES_PATH)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    header = (
        "\n\n## Auto-Appended Model Improvement "
        f"({datetime.now(timezone.utc).date()}, grading #{research_id})\n"
    )
    addition = header + section.strip() + "\n"
    if addition.strip() in existing:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(existing.rstrip() + addition, encoding="utf-8")


def generate_grading_note(
    conn: sqlite3.Connection,
    *,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    refresh_prices: bool = True,
    score_first: bool = True,
    language: str | None = None,
) -> GradingNote:
    """Run the full daily grade-and-reply cycle.

    Pipeline: refresh prices -> score due predictions -> pull recent outcomes ->
    LLM grading note -> persist as research_reports row -> queue follow-ups.
    Idempotent in the sense that score_due is idempotent and a same-day re-run
    just produces an additional grading note through the Codex-first backend.
    """
    settings = get_settings()
    lang = (language or settings.research_language or "zh").strip() or "zh"

    # Step 1: refresh prices for every active ticker (best-effort)
    refreshed = (
        refresh_prices_for_all(conn) if refresh_prices
        else PriceRefreshResult(tickers=[], inserted_total=0, failed=[])
    )

    # Step 2: score any newly-due predictions before reading outcomes
    if score_first:
        try:
            score_due(conn)
        except Exception:
            logger.exception(
                "grading: score_due raised; proceeding with outcomes already on file"
            )

    # Step 3: pull recent outcomes + compute stats
    rows = recent_outcomes(conn, hours=lookback_hours)
    stats = compute_stats(rows)

    # Step 4: short-circuit on empty window so we don't burn LLM cost
    if stats.total == 0:
        body = _empty_grading_body(refreshed, lookback_hours)
        research_id, created_at = _persist_grading(conn, body=body, cost_usd=0.0)
        return GradingNote(
            research_id=research_id,
            body=body,
            cost_usd=0.0,
            refreshed=refreshed,
            stats=stats,
            follow_ups_queued=0,
            rewrites_applied=0,
            rewrites_staged=0,
            created_at=created_at,
        )

    # Step 5: LLM call -- gated by daily cost ceiling
    check_cost_ceiling(conn, settings)

    system_template, user_template = _load_grading_prompt()
    system_prompt = system_template.format(language=lang)
    # F16: pull thesis-grading stats so the LLM can name "right direction wrong reason"
    thesis_stats = thesis.compute_thesis_stats(conn, hours=lookback_hours)
    thesis_block = thesis.format_thesis_block(thesis_stats)

    user_message = user_template.format(
        language=lang,
        now_utc=datetime.now(timezone.utc).isoformat(timespec="minutes"),
        lookback_hours=lookback_hours,
        refresh_block=_format_refresh_block(refreshed),
        stats_block=(
            _format_stats_block(stats)
            + "\n\n" + _format_error_patterns(conn, hours=lookback_hours)
        ),
        outcomes_block=_format_outcomes_block(rows),
        thesis_block=thesis_block,
        current_rules=_load_current_rules(),
        max_chars=GRADING_MAX_CHARS,
    )

    # F17: route through the Codex-first core backend.
    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    primary = get_core_client()
    response: ChatResponse = primary.chat(
        messages=messages,
        model=get_core_model(),
        max_tokens=GRADING_MAX_TOKENS,
        conn=conn,
        caller="grading.generate_note",
        cached_system=system_prompt,
    )

    body = response.content.strip()
    if not body:
        raise RuntimeError("Grading note generated empty body")
    if "Not financial advice" not in body:
        body = body.rstrip() + "\n\nNot financial advice."

    # Step 6: persist as research_reports row (APK pulls these via /channel/api/notes)
    research_id, created_at = _persist_grading(
        conn, body=body, cost_usd=response.cost_usd
    )

    # Step 7: feed the auto-queued follow-ups into action_queue so the next
    # research push references the resulting deep-dives -- this closes the
    # F11 improvement loop with grading-driven topics.
    follow_ups_queued = 0
    try:
        raw_items = action_queue.extract_action_items(body)
        if raw_items:
            inserted = action_queue.enqueue_actions(
                conn, source_research_id=research_id, raw_items=raw_items
            )
            follow_ups_queued = len(inserted)
            if follow_ups_queued:
                logger.info(
                    "grading: enqueued %d follow-up(s) from grading note %d",
                    follow_ups_queued, research_id,
                )
    except Exception:
        logger.exception("grading: action_queue enqueue failed (non-fatal)")

    rewrites_applied = rewrites_staged = 0
    try:
        rewrites_applied, rewrites_staged = _auto_apply_model_improvements(
            conn, grading_body=body, research_id=research_id,
        )
        if rewrites_applied or rewrites_staged:
            logger.info(
                "grading: auto-improve rewrites applied=%d staged=%d from note %d",
                rewrites_applied, rewrites_staged, research_id,
            )
    except Exception:
        logger.exception("grading: auto-improve rewrite failed (non-fatal)")
        emailer.send_email(
            subject=f"STOCK auto-improve failed for grading #{research_id}",
            body=(
                "The grading Model Improvement auto-apply path failed after the "
                "system attempted to process it automatically.\n\n"
                f"research_reports.id={research_id}\n\n"
                "Check orchestrator logs and prompt_rewrites for details."
            ),
        )

    return GradingNote(
        research_id=research_id,
        body=body,
        cost_usd=response.cost_usd,
        refreshed=refreshed,
        stats=stats,
        follow_ups_queued=follow_ups_queued,
        rewrites_applied=rewrites_applied,
        rewrites_staged=rewrites_staged,
        created_at=created_at,
    )
