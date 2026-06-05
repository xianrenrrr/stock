"""stock.knowledge -- knowledge base over generated research, fed into predictions.

The system produces a lot of deep research -- deep_dives, tech_dives, QA dives,
boss Q&A replies, DD checklists, health checks, discovery theses. Until now that
content only fed the boss-facing notes; the quantitative predictor never saw it,
so the analysis we paid to generate leaked out of the prediction loop.

This module is the retrieval + tagging layer that turns the research_reports
table into a per-ticker knowledge base the prediction prompt can consume. Each
piece of research is tagged by kind, and `predict_ticker` can pull ALL relevant
kinds or a subset. No new storage: research_reports already IS the store; this is
how we read it back intelligently at predict time.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# research_reports.kind values that count as knowledge, with a short display tag.
KNOWLEDGE_KINDS: dict[str, str] = {
    "deep_dive": "Deep-dive",
    "tech_dive": "Tech-dive",
    "deep_qa": "QA-dive",
    "reply": "Q&A reply",
    "health_check": "Health-check",
    "discovery_thesis": "Discovery thesis",
    "earnings_review": "Earnings review",
    "dd_checklist": "DD checklist",
}

DEFAULT_DAYS: int = 60
DEFAULT_MAX_ITEMS: int = 6
DEFAULT_EXCERPT_CHARS: int = 700


class KnowledgeItem(BaseModel):
    """One piece of prior research relevant to a ticker."""

    research_id: int
    kind: str
    tag: str
    topic: str
    created_at: str
    excerpt: str


def _ticker_pattern(ticker: str) -> re.Pattern[str]:
    """Word-boundary matcher so 'ON' does not match 'iON'; A-share/HK suffix
    forms like 600584.SS are matched literally."""
    t = re.escape(ticker.upper())
    return re.compile(rf"(?<![A-Za-z0-9.]){t}(?![A-Za-z0-9])", re.IGNORECASE)


def _excerpt_around(pat: re.Pattern[str], text: str, chars: int) -> str:
    """Return ~`chars` of text centered on the first ticker mention."""
    text = (text or "").strip()
    if not text:
        return ""
    m = pat.search(text)
    if not m:
        return text[:chars]
    start = max(0, m.start() - chars // 3)
    return text[start:start + chars].strip()


def gather_ticker_knowledge(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    kinds: list[str] | None = None,
    days: int = DEFAULT_DAYS,
    max_items: int = DEFAULT_MAX_ITEMS,
    excerpt_chars: int = DEFAULT_EXCERPT_CHARS,
) -> list[KnowledgeItem]:
    """Return recent research that mentions `ticker`, newest first, tagged by kind.

    `kinds` selects which research kinds to include (default: all KNOWLEDGE_KINDS).
    Matching is on a word-boundary ticker mention in the topic or body, so the
    predictor only sees research genuinely about this name.
    """
    kinds = kinds or list(KNOWLEDGE_KINDS.keys())
    if not kinds:
        return []
    placeholders = ",".join("?" * len(kinds))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT id, kind, COALESCE(topic, ''), body, created_at"
        " FROM research_reports"
        f" WHERE kind IN ({placeholders}) AND created_at >= ?"
        " ORDER BY created_at DESC, id DESC",
        (*kinds, cutoff),
    ).fetchall()

    pat = _ticker_pattern(ticker)
    items: list[KnowledgeItem] = []
    for rid, kind, topic, body, created_at in rows:
        haystack = f"{topic}\n{body or ''}"
        if not pat.search(haystack):
            continue
        items.append(KnowledgeItem(
            research_id=int(rid),
            kind=str(kind),
            tag=KNOWLEDGE_KINDS.get(str(kind), str(kind)),
            topic=str(topic)[:120],
            created_at=str(created_at),
            excerpt=_excerpt_around(pat, str(body or topic), excerpt_chars),
        ))
        if len(items) >= max_items:
            break
    return items


def format_knowledge_block(items: list[KnowledgeItem]) -> str:
    """Render knowledge items as a compact tagged block for the prediction prompt."""
    if not items:
        return "(no prior deep research on this ticker yet)"
    lines = [
        "Your own prior deep research on this ticker (knowledge base -- weigh it "
        "alongside the news + cases; cite it in your rationale when it applies):"
    ]
    for it in items:
        lines.append(f"- [{it.tag} | {it.created_at[:10]}] {it.topic}")
        lines.append(f"  {it.excerpt}")
    return "\n".join(lines)


def build_ticker_knowledge_block(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    kinds: list[str] | None = None,
    days: int = DEFAULT_DAYS,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> str:
    """Convenience: gather + format the per-ticker knowledge block."""
    return format_knowledge_block(
        gather_ticker_knowledge(
            conn, ticker, kinds=kinds, days=days, max_items=max_items,
        )
    )
