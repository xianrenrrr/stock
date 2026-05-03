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
