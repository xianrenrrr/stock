"""stock.research -- daily AI-supply-chain research note generator + deep dives."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from stock import action_queue
from stock.anomaly import format_anomaly_block, recent_anomalies
from stock.config import get_settings
from stock.holdings import Holding, format_holdings_block, list_holdings
from stock.ingest.insiders import format_insider_block, recent_for_ticker
from stock.conversation import format_context_block, recent_turns
from stock.discover import (
    format_extractions_for_research,
    get_recent_extractions,
)
from stock.wechat_inbox import recent_feedback_block
from stock.models import (
    MINIMAX_DEFAULT_MODEL,
    ChatMessage,
    ChatResponse,
    ClaudeCliUnavailable,
    check_cost_ceiling,
    get_client,
    get_core_client,
    get_core_model,
)
from stock.score import build_report, format_report
from stock.discovery_engine import format_candidates_block, list_candidates
from stock.events import (
    event_calibration_summary,
    extract_events_from_research,
    recent_events_block,
)
from stock.secular import (
    format_theme_block,
    load_themes,
    pick_focus_theme,
)
from stock.stops import format_stop_loss_block
from stock.ai_loop_monitor import format_loop_block
from stock.options import format_uoa_block
from stock.smallcap_scanner import format_smallcap_block
from stock.tech_trends import (
    format_conviction_watchlist_block,
    format_trend_radar_block,
    load_conviction,
    load_trends,
    pick_focus_trend,
)
from stock.thesis import compute_thesis_stats, format_thesis_block
from stock.supply_chain import (
    Layer,
    SupplyChain,
    format_cross_layer_sample,
    format_layer_players,
    gather_chain_context,
    load_chain,
    pick_focus_layer,
)

logger = logging.getLogger(__name__)

RESEARCH_PROMPT_PATH: str = "prompts/research.txt"
DEEP_DIVE_PROMPT_PATH: str = "prompts/deep_dive.txt"
HEALTH_CHECK_PROMPT_PATH: str = "prompts/health_check.txt"
REPLY_PROMPT_PATH: str = "prompts/reply.txt"
DISCOVERY_THESIS_PROMPT_PATH: str = "prompts/discovery_thesis.txt"
DISCOVERY_THESIS_MAX_TOKENS: int = 4500
DAILY_RESEARCH_MAX_TOKENS: int = 4500
DEEP_DIVE_MAX_TOKENS: int = 5500
HEALTH_CHECK_MAX_TOKENS: int = 4500
REPLY_MAX_TOKENS: int = 600
REPLY_MAX_CHARS: int = 600
WATCHLIST_PREDICTION_LOOKBACK_HOURS: int = 36
NEWS_FEATURE_LOOKBACK_HOURS: int = 24
NEWS_FEATURE_LIMIT: int = 25
DEFAULT_MAX_CHARS: int = 3500


def _core_chat(
    *,
    messages: list[ChatMessage],
    max_tokens: int,
    conn: sqlite3.Connection,
    caller: str,
    cached_system: str | None = None,
) -> ChatResponse:
    """Send a chat request via the active core backend, falling back to MiniMax on outage.

    Honors STOCK_CORE_BACKEND. When `claude_cli` is selected but the binary is
    missing or the subprocess fails, transparently falls back to MiniMax so a
    misconfigured Render deployment doesn't break the daily push. Logs the
    fallback so the operator can see it in `pipeline/logs/orchestrator.log`.
    """
    primary = get_core_client()
    primary_model = get_core_model()
    try:
        return primary.chat(
            messages=messages,
            model=primary_model,
            max_tokens=max_tokens,
            conn=conn,
            caller=caller,
            cached_system=cached_system,
        )
    except ClaudeCliUnavailable as exc:
        logger.warning(
            "core backend claude_cli unavailable for %s (%s); falling back to MiniMax",
            caller, exc,
        )
        fallback = get_client("minimax")
        return fallback.chat(
            messages=messages,
            model=MINIMAX_DEFAULT_MODEL,
            max_tokens=max_tokens,
            conn=conn,
            caller=f"{caller}+fallback",
            cached_system=cached_system,
        )


class ResearchReport(BaseModel):
    """One generated research note as stored on disk + in DB."""

    research_id: int
    kind: str
    topic: str | None
    layer_focus: str | None
    body: str
    cost_usd: float
    created_at: str


@lru_cache(maxsize=1)
def _load_research_prompt() -> tuple[str, str]:
    """Load and split the daily research prompt on [SYSTEM]/[USER] markers."""
    path = Path(RESEARCH_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Research prompt not found at {RESEARCH_PROMPT_PATH}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


@lru_cache(maxsize=1)
def _load_reply_prompt() -> tuple[str, str]:
    """Load and split the reply prompt on [SYSTEM]/[USER] markers."""
    path = Path(REPLY_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Reply prompt not found at {REPLY_PROMPT_PATH}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


@lru_cache(maxsize=1)
def _load_health_check_prompt() -> tuple[str, str]:
    """Load and split the health-check prompt on [SYSTEM]/[USER] markers."""
    path = Path(HEALTH_CHECK_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Health-check prompt not found at {HEALTH_CHECK_PROMPT_PATH}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


@lru_cache(maxsize=1)
def _load_deep_dive_prompt() -> tuple[str, str]:
    """Load and split the deep-dive prompt on [SYSTEM]/[USER] markers."""
    path = Path(DEEP_DIVE_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Deep-dive prompt not found at {DEEP_DIVE_PROMPT_PATH}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


def _session_label(now: datetime) -> str:
    """Tag morning vs evening based on UTC hour."""
    if now.hour < 18:
        return "morning (Asia evening / pre-US-open)"
    return "evening (post-US-close / Asia next-morning)"


def _build_watchlist_block(conn: sqlite3.Connection) -> str:
    """Pull recent predictions per active watchlist ticker for the prompt."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=WATCHLIST_PREDICTION_LOOKBACK_HOURS)
    ).isoformat()

    rows = conn.execute(
        "SELECT p.ticker, p.direction, p.prob_up, p.prob_up_calibrated,"
        " p.confidence, p.rationale, p.created_at"
        " FROM predictions p"
        " JOIN ("
        "   SELECT ticker, MAX(id) AS max_id FROM predictions"
        "   WHERE created_at >= ? GROUP BY ticker"
        " ) latest ON latest.max_id = p.id"
        " ORDER BY p.ticker",
        (cutoff,),
    ).fetchall()

    if not rows:
        return "(no fresh predictions in the lookback window — schedule may not have produced one yet)"

    lines: list[str] = []
    for row in rows:
        ticker, direction, prob_up, prob_cal, confidence, rationale, created_at = row
        prob_str = f"prob_up={prob_up:.2f}"
        if prob_cal is not None:
            prob_str += f" (cal={prob_cal:.2f})"
        lines.append(
            f"- {ticker} {direction} | {prob_str} | conf={confidence:.2f} | {created_at[:16]}\n"
            f"    rationale: {rationale[:240]}"
        )
    return "\n".join(lines)


def _build_news_block(conn: sqlite3.Connection) -> str:
    """Pull the most recent featured news rows across all watchlist tickers."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=NEWS_FEATURE_LOOKBACK_HOURS)
    ).isoformat()

    rows = conn.execute(
        "SELECT n.ticker, n.title, n.ts, f.json"
        " FROM news n JOIN features f ON n.id = f.news_id"
        " WHERE n.ticker IN (SELECT ticker FROM watchlist WHERE active = 1)"
        " AND n.ts >= ?"
        " ORDER BY n.ts DESC LIMIT ?",
        (cutoff, NEWS_FEATURE_LIMIT),
    ).fetchall()

    if not rows:
        return "(no recent featured news — ingest job may not have run yet)"

    lines: list[str] = []
    for row in rows:
        ticker, title, ts, feat_json = row
        feat: dict[str, Any] = {}
        try:
            feat = json.loads(feat_json) if feat_json else {}
        except (json.JSONDecodeError, TypeError):
            feat = {}
        sentiment = feat.get("sentiment", "?")
        catalyst = feat.get("catalyst_type", "?")
        summary = (feat.get("summary") or "").strip()
        lines.append(
            f"- [{ts[:16]}] {ticker} — {title[:160]}\n"
            f"    sentiment={sentiment}, catalyst={catalyst}\n"
            f"    summary: {summary[:200]}"
        )
    return "\n".join(lines)


def _build_performance_block(conn: sqlite3.Connection, days: int = 7) -> str:
    """Summarize last-N-days hit rate, Brier, spend for the prompt."""
    summary = build_report(conn, days=days)
    return format_report(summary)


def _build_predictions_block_for_topic(conn: sqlite3.Connection, topic: str, limit: int = 10) -> str:
    """Pull recent predictions whose ticker matches a topic substring (best-effort)."""
    target = f"%{topic.upper()}%"
    rows = conn.execute(
        "SELECT ticker, direction, prob_up, confidence, rationale, created_at"
        " FROM predictions"
        " WHERE UPPER(ticker) LIKE ?"
        " ORDER BY created_at DESC LIMIT ?",
        (target, limit),
    ).fetchall()
    if not rows:
        return "(no recent predictions match this topic)"
    return "\n".join(
        f"- [{r[5][:10]}] {r[0]} {r[1]} prob_up={r[2]:.2f} conf={r[3]:.2f} | {r[4][:160]}"
        for r in rows
    )


def _build_news_block_for_topic(conn: sqlite3.Connection, topic: str, limit: int = 12) -> str:
    """Pull recent news whose title or ticker contains the topic."""
    target = f"%{topic}%"
    rows = conn.execute(
        "SELECT n.ticker, n.title, n.ts, f.json FROM news n"
        " LEFT JOIN features f ON n.id = f.news_id"
        " WHERE n.title LIKE ? OR n.ticker LIKE ?"
        " ORDER BY n.ts DESC LIMIT ?",
        (target, target, limit),
    ).fetchall()
    if not rows:
        return "(no recent news matches this topic)"

    lines: list[str] = []
    for row in rows:
        ticker, title, ts, feat_json = row
        feat: dict[str, Any] = {}
        if feat_json:
            try:
                feat = json.loads(feat_json)
            except (json.JSONDecodeError, TypeError):
                feat = {}
        sentiment = feat.get("sentiment", "?")
        summary = (feat.get("summary") or "")[:200]
        lines.append(f"- [{ts[:16]}] {ticker} — {title[:160]}\n    sentiment={sentiment} | {summary}")
    return "\n".join(lines)


def _persist_research(
    conn: sqlite3.Connection,
    *,
    kind: str,
    topic: str | None,
    layer_focus: str | None,
    body: str,
    cost_usd: float,
) -> int:
    """Insert a research_reports row and return its id."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO research_reports (kind, topic, body, layer_focus, cost_usd, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (kind, topic, body, layer_focus, cost_usd, now),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)


def generate_daily_research(
    conn: sqlite3.Connection,
    *,
    focus_layer_name: str | None = None,
    language: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ResearchReport:
    """Run the daily AI-supply-chain research cycle and persist the note."""
    settings = get_settings()
    chain: SupplyChain = load_chain()

    # Pick the focus layer (explicit override wins, otherwise rotate by day-of-year)
    if focus_layer_name:
        focus_layer: Layer | None = chain.find_layer(focus_layer_name)
        if focus_layer is None:
            raise ValueError(f"Unknown focus layer '{focus_layer_name}'")
    else:
        focus_layer = pick_focus_layer(chain)

    now = datetime.now(timezone.utc)
    lang = (language or settings.research_language or "zh").strip() or "zh"

    # Assemble prompt context
    watchlist_block = _build_watchlist_block(conn)
    news_block = _build_news_block(conn)
    performance_block = _build_performance_block(conn, days=7)
    focus_layer_players = format_layer_players(focus_layer)
    cross_layer_block = format_cross_layer_sample(chain, exclude_layer=focus_layer.layer)
    web_discovery_block = format_extractions_for_research(
        get_recent_extractions(conn, hours=12)
    )
    # F16: thesis verification stats so the morning note self-flags
    # "right direction wrong reason" patterns.
    thesis_block = format_thesis_block(compute_thesis_stats(conn, hours=48))

    # F19: forward-looking candidates -- the boss complained that everything is
    # backward-looking ("by the time you tell me it's up 20x the move is over").
    # The discovery engine flags tickers with leading-indicator signals (insider
    # cluster buys, 8-K novelty, quiet accumulation, reddit acceleration) BEFORE
    # they break out. Top 5 candidates injected into the prompt.
    discovery_block = format_candidates_block(
        list_candidates(conn, status="candidate", limit=5)
    )

    # F26: tracked events -- pending + recently-verified, plus a calibration
    # summary so the LLM sees its own hit-rate and can self-correct confidence.
    events_block = recent_events_block(conn, lookback_days=30, limit=12)
    cal = event_calibration_summary(conn, lookback_days=90)
    events_calibration = (
        f"Last 90d: {cal['total_resolved']} resolved, {cal['hits']} hits "
        f"({cal['hit_rate']:.0%}), avg confidence-on-resolve {cal['avg_confidence_when_resolved']:.2f}"
        if cal["total_resolved"] else
        "(no resolved events in last 90d -- still building calibration baseline)"
    )

    # F25: rotate one non-AI long-horizon theme into every note. Boss explicitly
    # asked for "hidden gems not driven by AI but by things you believe gonna
    # happen in the next 5-10 years -- China aging, US wealth inequality, AI
    # displacement / consumer crisis." Themes live in data/secular_themes.yaml;
    # rotation is by day-of-year so each theme gets ~73 days/year of airtime.
    secular_focus = pick_focus_theme(load_themes(), now=now)
    secular_block = format_theme_block(secular_focus)

    # F24: pre-compute stop-loss prices for every watchlist + secular ticker the
    # note will mention, so the LLM cites real ATR-based + swing-low + percent
    # stops instead of generic "set a stop" boilerplate. Boss explicitly asked
    # for stop-loss on every recommendation.
    stop_loss_tickers: list[str] = []
    rows_for_stops = conn.execute(
        "SELECT ticker FROM watchlist WHERE active = 1 ORDER BY ticker"
    ).fetchall()
    stop_loss_tickers.extend(str(r[0]) for r in rows_for_stops)
    if secular_focus is not None:
        for pick in secular_focus.beneficiaries[:4]:
            t = pick.ticker.upper()
            if t and t not in stop_loss_tickers:
                stop_loss_tickers.append(t)
    stop_loss_block = format_stop_loss_block(conn, stop_loss_tickers[:30])
    # F36: unusual options activity from the last 3 sessions, top 12.
    # Caller-renders an empty string when nothing fired (silent on quiet days).
    uoa_block = format_uoa_block(conn, days=3, limit=12)
    # F38: top forward-discovery small-caps in 3 sectors (AI semis, biopharma,
    # AI-DC energy). Refreshed by the 22:15 UTC nightly scan.
    smallcap_block = format_smallcap_block(conn, days=2)
    # F39: AI commercial-loop closure-risk monitor. Headline + table of any
    # panel companies showing simultaneous deceleration + margin compression.
    ai_loop_block = format_loop_block(conn, days=120)
    # F41: tech-trend radar (1 trend per push, day-rotated across enabled).
    # Boss directive: lead with technology trends, not news summaries.
    enabled_trends = load_trends(enabled_only=True)
    focus_trend = pick_focus_trend(enabled_trends, now=now)
    trend_radar_block = format_trend_radar_block(focus_trend)
    # F42: conviction watchlist (~10 names) -- the deeply-tracked layer
    # above the 39-ticker ingest universe. Live prices + F24 stops.
    conviction_block = format_conviction_watchlist_block(
        conn, load_conviction(enabled_only=True),
    )
    feedback_block = recent_feedback_block()
    anomaly_block = format_anomaly_block(recent_anomalies(conn, days=2))
    previous_followups_block = action_queue.format_previous_followups(
        action_queue.recent_completed(conn, hours=18), conn
    )
    holdings_block = format_holdings_block(list_holdings(conn, active_only=True), conn)
    conversation_context_block = format_context_block(
        recent_turns(conn, recipient=None, limit=6)
    )

    # Cost-ceiling check before LLM dispatch
    check_cost_ceiling(conn, settings)

    # Build [SYSTEM]/[USER] messages
    system_template, user_template = _load_research_prompt()
    system_prompt = system_template.format(language=lang)
    user_message = user_template.format(
        language=lang,
        now_utc=now.isoformat(timespec="minutes"),
        session_label=_session_label(now),
        focus_layer_name=focus_layer.layer,
        focus_layer_function=focus_layer.function,
        watchlist_block=watchlist_block,
        performance_block=performance_block,
        focus_layer_players=focus_layer_players,
        cross_layer_block=cross_layer_block,
        news_block=news_block,
        web_discovery_block=web_discovery_block,
        feedback_block=feedback_block,
        anomaly_block=anomaly_block,
        previous_followups_block=previous_followups_block,
        holdings_block=holdings_block,
        conversation_context_block=conversation_context_block,
        thesis_block=thesis_block,
        discovery_block=discovery_block,
        secular_block=secular_block,
        stop_loss_block=stop_loss_block,
        events_block=events_block,
        events_calibration=events_calibration,
        uoa_block=uoa_block or "(no unusual options activity in the last 3 sessions)",
        smallcap_block=smallcap_block or "(smallcap scan has not run yet today)",
        ai_loop_block=ai_loop_block or "(AI loop monitor not yet measured this cycle)",
        trend_radar_block=trend_radar_block,
        conviction_block=conviction_block or "(no conviction watchlist names enabled)",
        max_chars=max_chars,
    )

    # Core backend is swappable via STOCK_CORE_BACKEND (minimax|claude_cli)
    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    response: ChatResponse = _core_chat(
        messages=messages,
        max_tokens=DAILY_RESEARCH_MAX_TOKENS,
        conn=conn,
        caller="research.generate_daily",
        cached_system=system_prompt,
    )

    body = response.content.strip()
    if not body:
        raise RuntimeError("Daily research generated empty body")

    # Belt-and-suspenders: enforce disclaimer
    if "Not financial advice" not in body:
        body = body.rstrip() + "\n\nNot financial advice."

    research_id = _persist_research(
        conn,
        kind="daily",
        topic=None,
        layer_focus=focus_layer.layer,
        body=body,
        cost_usd=response.cost_usd,
    )

    # Auto-queue follow-up topics from the just-generated note (best-effort)
    try:
        raw_items = action_queue.extract_action_items(body)
        if raw_items:
            queued = action_queue.enqueue_actions(
                conn, source_research_id=research_id, raw_items=raw_items
            )
            if queued:
                logger.info(
                    "action_queue: enqueued %d new follow-up(s) from research %d",
                    len(queued), research_id,
                )
    except Exception:
        logger.exception("action_queue auto-enqueue failed (non-fatal)")

    # F26: parse `[NEW EVENT] ticker | type | title | outcome | start | end | conf`
    # lines from the body and add them to tracked_events so the next-day note
    # sees them in the recent_events_block + nightly verify grades them.
    try:
        new_events = extract_events_from_research(
            body, conn, source_research_id=research_id,
        )
        if new_events:
            logger.info(
                "events: extracted %d new tracked event(s) from research %d",
                len(new_events), research_id,
            )
    except Exception:
        logger.exception("events auto-extract failed (non-fatal)")

    return ResearchReport(
        research_id=research_id,
        kind="daily",
        topic=None,
        layer_focus=focus_layer.layer,
        body=body,
        cost_usd=response.cost_usd,
        created_at=now.isoformat(),
    )


def generate_deep_dive(
    conn: sqlite3.Connection,
    *,
    topic: str,
    extra_context: str | None = None,
    language: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ResearchReport:
    """Run an on-demand deep-dive research note for a specific topic."""
    if not topic.strip():
        raise ValueError("topic is required for deep_dive")

    settings = get_settings()
    chain = load_chain()
    lang = (language or settings.research_language or "zh").strip() or "zh"

    chain_context = gather_chain_context(chain, topic=topic)
    predictions_block = _build_predictions_block_for_topic(conn, topic)
    news_block = _build_news_block_for_topic(conn, topic)
    extra_block = (extra_context or "").strip() or "(none)"

    check_cost_ceiling(conn, settings)

    system_template, user_template = _load_deep_dive_prompt()
    system_prompt = system_template.format(language=lang)
    user_message = user_template.format(
        language=lang,
        topic=topic,
        chain_context=chain_context,
        news_block=news_block,
        predictions_block=predictions_block,
        extra_context=extra_block,
        max_chars=max_chars,
    )

    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    response: ChatResponse = _core_chat(
        messages=messages,
        max_tokens=DEEP_DIVE_MAX_TOKENS,
        conn=conn,
        caller="research.generate_deep_dive",
        cached_system=system_prompt,
    )

    body = response.content.strip()
    if not body:
        raise RuntimeError("Deep-dive generated empty body")

    if "Not financial advice" not in body:
        body = body.rstrip() + "\n\nNot financial advice."

    research_id = _persist_research(
        conn,
        kind="deep_dive",
        topic=topic,
        layer_focus=None,
        body=body,
        cost_usd=response.cost_usd,
    )
    return ResearchReport(
        research_id=research_id,
        kind="deep_dive",
        topic=topic,
        layer_focus=None,
        body=body,
        cost_usd=response.cost_usd,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def generate_health_check(
    conn: sqlite3.Connection,
    *,
    holding: Holding,
    language: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ResearchReport:
    """Run a per-holding health-check deep-dive that injects anomalies + Form 4."""
    settings = get_settings()
    chain = load_chain()
    lang = (language or settings.research_language or "zh").strip() or "zh"

    # Pull all the holding-specific signals
    chain_context = gather_chain_context(chain, topic=holding.ticker)
    predictions_block = _build_predictions_block_for_topic(conn, holding.ticker)
    news_block = _build_news_block_for_topic(conn, holding.ticker)
    anomalies = [
        a for a in recent_anomalies(conn, days=14)
        if a.ticker == holding.ticker
    ]
    anomalies_block = format_anomaly_block(anomalies)
    insiders_block = format_insider_block(
        recent_for_ticker(conn, holding.ticker, days=90)
    )

    extra_context = (
        f"qty={holding.qty} cost_basis={holding.cost_basis}"
        f" opened_at={holding.opened_at} notes={holding.notes}"
    )

    check_cost_ceiling(conn, settings)

    system_template, user_template = _load_health_check_prompt()
    system_prompt = system_template.format(language=lang)
    user_message = user_template.format(
        language=lang,
        topic=holding.ticker,
        extra_context=extra_context,
        anomalies_block=anomalies_block,
        insiders_block=insiders_block,
        news_block=news_block,
        chain_context=chain_context,
        predictions_block=predictions_block,
        max_chars=max_chars,
    )

    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    response: ChatResponse = _core_chat(
        messages=messages,
        max_tokens=HEALTH_CHECK_MAX_TOKENS,
        conn=conn,
        caller="research.generate_health_check",
        cached_system=system_prompt,
    )

    body = response.content.strip()
    if not body:
        raise RuntimeError("Health-check generated empty body")
    if "Not financial advice" not in body:
        body = body.rstrip() + "\n\nNot financial advice."

    research_id = _persist_research(
        conn,
        kind="health_check",
        topic=holding.ticker,
        layer_focus=None,
        body=body,
        cost_usd=response.cost_usd,
    )
    return ResearchReport(
        research_id=research_id,
        kind="health_check",
        topic=holding.ticker,
        layer_focus=None,
        body=body,
        cost_usd=response.cost_usd,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


REPLY_WEB_SEARCH_RESULTS: int = 4
REPLY_WEB_FETCH_PER_RESULT_CHARS: int = 1500
REPLY_WEB_BLOCK_MAX_CHARS: int = 6000


@lru_cache(maxsize=1)
def _load_discovery_thesis_prompt() -> tuple[str, str]:
    """Load + split the F22 discovery-thesis prompt."""
    path = Path(DISCOVERY_THESIS_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Discovery-thesis prompt not found at {path}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    return parts[0].replace("[SYSTEM]", "").strip(), parts[1].strip() if len(parts) > 1 else ""


def _format_leading_signals_block(components: dict[str, float]) -> str:
    """Render the F19/F21 component dict as a readable block for the thesis prompt."""
    lines: list[str] = []
    lines.append(f"- Insider OCIS (raw): {components.get('ocis_raw', 0):.2f}")
    lines.append(f"  - distinct filers (30d): {int(components.get('ocis_distinct_filers', 0))}")
    lines.append(f"  - max cluster size (10d window): {int(components.get('ocis_cluster_max', 0))}")
    lines.append(f"  - opportunistic $ value: ${components.get('ocis_opportunistic_usd', 0):,.0f}")
    lines.append(f"- 8-K novelty score: {components.get('novelty_raw', 0):.2f} (0=identical, 1=totally new)")
    lines.append(f"- QAP gate (Wyckoff-lite quiet accumulation): {'PRESENT' if components.get('qap_gate', 0) > 0 else 'NOT PRESENT'}")
    lines.append(f"  - range/ATR: {components.get('qap_range_over_atr', -1):.2f}")
    lines.append(f"  - 60d/180d volume ratio: {components.get('qap_volume_ratio', -1):.2f}")
    lines.append(f"- Reddit (ApeWisdom) mentions now/prior 24h: {int(components.get('reddit_now', 0))}/{int(components.get('reddit_prior', 0))} (accel {components.get('reddit_accel', 0):+.2f})")
    if components.get('theme_hn_30d', 0) > 0 or components.get('theme_arxiv_30d', 0) > 0:
        lines.append(f"- HN mentions 30d / prior 30d: {int(components.get('theme_hn_30d', 0))} / accel {components.get('theme_hn_accel', 0):+.2f}")
        lines.append(f"- arXiv mentions 30d / prior 30d: {int(components.get('theme_arxiv_30d', 0))} / accel {components.get('theme_arxiv_accel', 0):+.2f}")
    return "\n".join(lines)


def _format_recent_insider_block_for_ticker(
    conn: sqlite3.Connection, ticker: str, *, days: int = 90,
) -> str:
    """Pull the last 90 days of Form 4 filings for one ticker as a readable block."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT filed_at, filer_name, COALESCE(filer_role, ''), transaction_type,"
        " COALESCE(shares, 0), COALESCE(price, 0)"
        " FROM insider_filings WHERE ticker = ? AND filed_at >= ?"
        " ORDER BY filed_at DESC LIMIT 20",
        (ticker, cutoff),
    ).fetchall()
    if not rows:
        return "(no insider filings in window)"
    lines = []
    for filed_at, filer_name, filer_role, txn_type, shares, price in rows:
        value = float(shares) * float(price) if shares and price else 0.0
        lines.append(
            f"- [{str(filed_at)[:10]}] {filer_name} ({filer_role or 'n/a'})"
            f" {txn_type or '?'} {int(shares)} @ ${price:.2f} = ${value:,.0f}"
        )
    return "\n".join(lines)


def generate_discovery_thesis(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    components: dict[str, float],
    company_name: str = "",
    sublayer: str = "",
    layer: str = "",
    language: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ResearchReport:
    """F22: write a forward-looking discovery thesis on a candidate the engine just flagged.

    Caller (typically the discovery_engine job) supplies the ticker + the
    leading-indicator components dict already computed during the scoring pass,
    so this function does NOT re-run the indicators -- it just composes the
    LLM prompt + persists the resulting note as kind='discovery_thesis' in
    research_reports. Cloud_sync pushes to Render, APK shows it.
    """
    settings = get_settings()
    chain = load_chain()
    lang = (language or settings.research_language or "zh").strip() or "zh"

    leading_block = _format_leading_signals_block(components)
    chain_context = gather_chain_context(chain, topic=ticker)
    news_block = _build_news_block_for_topic(conn, ticker, limit=10)
    insider_block = _format_recent_insider_block_for_ticker(conn, ticker)
    anomalies = recent_anomalies(conn, days=14)
    anomalies = [a for a in anomalies if a.ticker == ticker]
    anomaly_block = format_anomaly_block(anomalies)
    predictions_block = _build_predictions_block_for_topic(conn, ticker)

    check_cost_ceiling(conn, settings)

    system_template, user_template = _load_discovery_thesis_prompt()
    system_prompt = system_template
    user_message = user_template.format(
        ticker=ticker,
        company=company_name or ticker,
        sublayer=sublayer or "(unmapped)",
        layer=layer or "(unmapped)",
        language=lang,
        leading_signals_block=leading_block,
        news_block=news_block,
        insider_block=insider_block,
        anomaly_block=anomaly_block,
        chain_context=chain_context,
        predictions_block=predictions_block,
        max_chars=max_chars,
    )

    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    response: ChatResponse = _core_chat(
        messages=messages,
        max_tokens=DISCOVERY_THESIS_MAX_TOKENS,
        conn=conn,
        caller="research.discovery_thesis",
        cached_system=system_prompt,
    )

    body = response.content.strip()
    if not body:
        raise RuntimeError(f"Discovery thesis generated empty body for {ticker}")
    if "Not financial advice" not in body:
        body = body.rstrip() + "\n\nNot financial advice."

    research_id = _persist_research(
        conn,
        kind="discovery_thesis",
        topic=ticker,
        layer_focus=layer or None,
        body=body,
        cost_usd=response.cost_usd,
    )

    # Auto-queue follow-ups for the next research cycle (closes the loop)
    try:
        raw_items = action_queue.extract_action_items(body)
        if raw_items:
            action_queue.enqueue_actions(
                conn, source_research_id=research_id, raw_items=raw_items
            )
    except Exception:
        logger.exception("discovery_thesis: action_queue enqueue failed (non-fatal)")

    return ResearchReport(
        research_id=research_id,
        kind="discovery_thesis",
        topic=ticker,
        layer_focus=layer or None,
        body=body,
        cost_usd=response.cost_usd,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

# F16: ticker detection in boss replies. Matches both US-style (NVDA, AVGO) and
# A-share/HK suffix forms (600584.SS, 0700.HK) used across the supply chain map.
import re as _re_thesis  # alias to avoid shadowing module-level imports above

_REPLY_TICKER_RE = _re_thesis.compile(
    r"(?<![A-Za-z0-9])([A-Z]{2,5}|[0-9]{4,6}\.(?:SS|SZ|HK|TW))(?![A-Za-z0-9])"
)
_REPLY_TICKER_STOPWORDS: frozenset[str] = frozenset({
    "AI", "API", "AM", "PM", "USD", "CNY", "EPS", "GDP", "CEO", "CFO",
    "AND", "FOR", "THE", "PER", "ETC", "OK", "FYI", "TBD", "USA", "EU",
    "NDA", "IPO", "ETF", "OEM", "BOM", "ASP", "QOQ", "YOY",
})
_REPLY_TICKER_MAX: int = 2  # cap how many fresh predictions we generate per reply


def _detect_tickers_in_text(text: str) -> list[str]:
    """Extract ticker-shaped tokens from a boss reply, deduped + stopword-filtered.

    Returns up to _REPLY_TICKER_MAX tickers in first-seen order. Used by
    generate_reply to attach a fresh per-ticker prediction (and its theses) so
    every outbound reply has a verifiable thesis tied to it.
    """
    if not text:
        return []
    seen: list[str] = []
    for match in _REPLY_TICKER_RE.finditer(text):
        tok = match.group(1).upper()
        if tok in _REPLY_TICKER_STOPWORDS:
            continue
        if tok in seen:
            continue
        seen.append(tok)
        if len(seen) >= _REPLY_TICKER_MAX:
            break
    return seen


def _build_ticker_prediction_block(
    conn: sqlite3.Connection, *, boss_reply: str
) -> str:
    """For each ticker mentioned in the boss reply, emit a fresh prediction + theses.

    Best-effort: any per-ticker failure (no news, yfinance error, cost ceiling)
    gets logged and skipped so the reply still goes through. The prediction call
    persists to the predictions table and triggers thesis extraction via the
    predict_ticker hook -- so the reply is *traceable* and gradeable later.
    """
    tickers = _detect_tickers_in_text(boss_reply)
    if not tickers:
        return "(no tickers in boss reply)"

    # Lazy import to avoid cycles: research imports predict, predict imports thesis,
    # thesis imports models. All resolved at call-time.
    from stock.predict import predict_ticker
    from stock.thesis import format_theses_inline, list_for_prediction

    blocks: list[str] = []
    for ticker in tickers:
        try:
            pred = predict_ticker(ticker, conn)
        except Exception as exc:  # noqa: BLE001 -- surface and continue
            blocks.append(
                f"### {ticker}\n  (fresh prediction skipped: {type(exc).__name__})"
            )
            continue

        theses = list_for_prediction(conn, pred.prediction_id)
        cal = (
            f" (cal={pred.prob_up_calibrated:.2f})"
            if pred.prob_up_calibrated is not None else ""
        )
        blocks.append(
            f"### {ticker}\n"
            f"  direction={pred.direction} prob_up={pred.prob_up:.2f}{cal}"
            f" confidence={pred.confidence:.2f}\n"
            f"  rationale: {pred.rationale[:300]}\n"
            f"  due_at: {pred.due_at}\n"
            f"  Theses (will be graded vs post-window news):\n"
            f"{format_theses_inline(theses)}"
        )
    return "\n\n".join(blocks)


def _gather_web_grounding(question: str) -> str:
    """Run a Tavily search on the boss's question and fetch top hits as a context block.

    Returns a markdown-formatted block; empty string if web search is unavailable
    (no key configured, transient failure). Never raises -- the reply still goes
    through with whatever context we have.
    """
    from stock.webfetch import fetch_many
    from stock.websearch import WebSearchUnavailable, search

    try:
        hits = search(question.strip(), max_results=REPLY_WEB_SEARCH_RESULTS)
    except WebSearchUnavailable as exc:
        logger.info("generate_reply: web search unavailable (%s); proceeding ungrounded", exc)
        return ""
    except Exception:
        logger.exception("generate_reply: web search raised; proceeding ungrounded")
        return ""

    if not hits:
        return ""

    # Fetch the actual page text for each top hit so MiniMax sees real content,
    # not just snippets. Cheap (~2-3s per page, parallelism not worth the
    # complexity for N=4).
    urls = [h.url for h in hits if h.url]
    fetched = fetch_many(urls, max_chars=REPLY_WEB_FETCH_PER_RESULT_CHARS)
    fetched_by_url = {f.url: f for f in fetched}

    parts: list[str] = ["Live web search context (grounding for the answer below):"]
    total_chars = 0
    for hit in hits:
        snippet = (hit.snippet or "").strip()[:300]
        body = ""
        ftc = fetched_by_url.get(hit.url)
        if ftc and ftc.ok:
            body = ftc.text.strip()[:REPLY_WEB_FETCH_PER_RESULT_CHARS]
        block = (
            f"\n--- {hit.title or '(untitled)'} ---\n"
            f"URL: {hit.url}\n"
            f"Snippet: {snippet}\n"
            f"Page text:\n{body if body else '(fetch failed; use snippet only)'}\n"
        )
        if total_chars + len(block) > REPLY_WEB_BLOCK_MAX_CHARS:
            break
        parts.append(block)
        total_chars += len(block)
    return "\n".join(parts)


def generate_reply(
    conn: sqlite3.Connection,
    *,
    recipient: str,
    boss_reply: str,
    language: str | None = None,
) -> str:
    """Compose a short MiniMax-driven reply to a single boss message."""
    # Lazy imports to avoid top-level import cycles
    from stock.conversation import format_context_block, recent_turns

    settings = get_settings()
    lang = (language or settings.research_language or "zh").strip() or "zh"

    # Build context blocks
    context_block = format_context_block(
        recent_turns(conn, recipient=recipient, limit=6)
    )
    holdings_block = format_holdings_block(
        list_holdings(conn, active_only=True), conn
    )

    # Pull latest research note body as background, capped tightly
    row = conn.execute(
        "SELECT body FROM research_reports WHERE kind = 'daily'"
        " ORDER BY created_at DESC, id DESC LIMIT 1"
    ).fetchone()
    recent_research_excerpt = (
        str(row[0])[:1000] if row and row[0] else "(no recent daily note)"
    )

    similar_turns_block = "(none)"

    # Live web grounding via Tavily/Serper/Brave: search the boss's question text
    # and fetch the top pages so the LLM sees real source material instead of
    # making up specifics from training-data memory.
    web_grounding_block = _gather_web_grounding(boss_reply) or "(none)"

    # F16: if the boss mentioned a ticker, run a fresh prediction (which also
    # triggers thesis extraction) so the reply has a verifiable thesis attached.
    try:
        ticker_prediction_block = _build_ticker_prediction_block(
            conn, boss_reply=boss_reply
        )
    except Exception:
        logger.exception("generate_reply: ticker prediction block failed; using stub")
        ticker_prediction_block = "(ticker prediction unavailable)"

    check_cost_ceiling(conn, settings)

    system_template, user_template = _load_reply_prompt()
    system_prompt = system_template.format(language=lang)
    user_message = user_template.format(
        language=lang,
        recipient=recipient,
        boss_reply=boss_reply,
        conversation_context_block=context_block,
        recent_research_excerpt=recent_research_excerpt,
        similar_turns_block=similar_turns_block,
        holdings_block=holdings_block,
        web_grounding_block=web_grounding_block,
        ticker_prediction_block=ticker_prediction_block,
    )

    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]

    # MiniMax M2.5-highspeed is a thinking model: sometimes burns the entire
    # max_tokens budget on <think>...</think> and emits nothing afterward.
    # strip_thinking() then leaves us with an empty body. Retry up to 2 times
    # before giving up and surfacing "(empty reply)" to the user.
    # The claude_cli backend doesn't have this failure mode, but the retry loop
    # is harmless when it runs against it (subsequent calls just succeed once).
    body = ""
    for attempt in range(3):
        response: ChatResponse = _core_chat(
            messages=messages,
            max_tokens=REPLY_MAX_TOKENS,
            conn=conn,
            caller="research.generate_reply",
            cached_system=system_prompt,
        )
        candidate = response.content.strip()
        if candidate:
            body = candidate
            break
        logger.warning(
            "generate_reply attempt %d returned empty content; retrying", attempt + 1,
        )

    if not body:
        body = "(empty reply)"
    if len(body) > REPLY_MAX_CHARS:
        body = body[:REPLY_MAX_CHARS].rstrip()
    if "Not financial advice" not in body:
        body = body.rstrip() + "\n\nNot financial advice."
    return body


def get_latest_report(
    conn: sqlite3.Connection, *, kind: str = "daily"
) -> ResearchReport | None:
    """Return the most recent stored report of a given kind."""
    row = conn.execute(
        "SELECT id, kind, topic, layer_focus, body, cost_usd, created_at"
        " FROM research_reports WHERE kind = ?"
        " ORDER BY created_at DESC, id DESC LIMIT 1",
        (kind,),
    ).fetchone()
    if row is None:
        return None
    return ResearchReport(
        research_id=row[0],
        kind=row[1],
        topic=row[2],
        layer_focus=row[3],
        body=row[4],
        cost_usd=row[5],
        created_at=row[6],
    )
