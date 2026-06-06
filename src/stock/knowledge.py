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

from stock.memory import _serialize_embedding, embed

logger = logging.getLogger(__name__)

INDEX_TEXT_MAX_CHARS: int = 2000
DEFAULT_SEMANTIC_K: int = 3
SEMANTIC_DAYS: int = 150
# Cosine-similarity floor for thematic matches. Below this the research is only
# weakly related and injecting it adds noise (e.g. HBM research into an RKLB
# space prediction). all-MiniLM: ~0.4+ = strongly related, ~0.15 = unrelated.
MIN_SEMANTIC_SIMILARITY: float = 0.30

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
    "macro": "US macro",
    "daily": "Daily note",
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
    via: str = "direct"  # "direct" (ticker named) | "semantic" (thematic match)
    similarity: float | None = None


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


# --- Semantic index (embeddings) -------------------------------------------
# Direct ticker matching misses research that is THEMATICALLY relevant but never
# names the ticker (e.g. an AI-DC power dive that bears on a CEG prediction). We
# embed research bodies into a vec0 table and pull the nearest neighbours of the
# ticker's current news context too.

def _research_text(topic: str, body: str | None) -> str:
    return f"{topic}\n{(body or '')[:INDEX_TEXT_MAX_CHARS]}".strip()


def index_research(
    conn: sqlite3.Connection,
    research_id: int,
    *,
    topic: str | None = None,
    body: str | None = None,
) -> bool:
    """Embed one research report and (re)store it in knowledge_embeddings."""
    if topic is None or body is None:
        row = conn.execute(
            "SELECT topic, body FROM research_reports WHERE id = ?", (research_id,),
        ).fetchone()
        if row is None:
            return False
        topic, body = row[0], row[1]
    text = _research_text(str(topic or ""), body)
    if not text:
        return False
    blob = _serialize_embedding(embed(text))
    conn.execute("DELETE FROM knowledge_embeddings WHERE research_id = ?", (research_id,))
    conn.execute(
        "INSERT INTO knowledge_embeddings (research_id, embedding) VALUES (?, ?)",
        (research_id, blob),
    )
    conn.commit()
    return True


def backfill_knowledge(conn: sqlite3.Connection, *, limit: int = 1000) -> int:
    """Embed any KNOWLEDGE_KINDS research not yet in the index. Returns count."""
    kinds = list(KNOWLEDGE_KINDS.keys())
    placeholders = ",".join("?" * len(kinds))
    rows = conn.execute(
        "SELECT id, topic, body FROM research_reports"
        f" WHERE kind IN ({placeholders})"
        " AND id NOT IN (SELECT research_id FROM knowledge_embeddings)"
        " ORDER BY id DESC LIMIT ?",
        (*kinds, limit),
    ).fetchall()
    indexed = 0
    for rid, topic, body in rows:
        try:
            if index_research(conn, int(rid), topic=topic, body=body):
                indexed += 1
        except Exception:  # noqa: BLE001 -- isolate per-row failures
            logger.exception("knowledge index failed for research_id=%s", rid)
    if indexed:
        logger.info("knowledge backfill indexed %d research reports", indexed)
    return indexed


def retrieve_semantic(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    *,
    k: int = DEFAULT_SEMANTIC_K,
    days: int = SEMANTIC_DAYS,
    kinds: list[str] | None = None,
    exclude_ids: set[int] | None = None,
    excerpt_chars: int = DEFAULT_EXCERPT_CHARS,
    min_similarity: float = MIN_SEMANTIC_SIMILARITY,
) -> list[KnowledgeItem]:
    """Return the k research reports most semantically similar to query_embedding,
    filtered by kind + recency + a similarity floor, most-similar first."""
    kinds = kinds or list(KNOWLEDGE_KINDS.keys())
    if not kinds:
        return []
    blob = _serialize_embedding(query_embedding)
    vec_rows = conn.execute(
        "SELECT research_id, distance FROM knowledge_embeddings"
        " WHERE embedding MATCH ? AND k = ?",
        (blob, max(k * 4, 20)),
    ).fetchall()
    if not vec_rows:
        return []
    dist = {int(r[0]): float(r[1]) for r in vec_rows}
    exclude = exclude_ids or set()
    ids = [i for i in dist if i not in exclude]
    if not ids:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    id_ph = ",".join("?" * len(ids))
    kind_ph = ",".join("?" * len(kinds))
    rows = conn.execute(
        "SELECT id, kind, COALESCE(topic, ''), body, created_at FROM research_reports"
        f" WHERE id IN ({id_ph}) AND kind IN ({kind_ph}) AND created_at >= ?",
        (*ids, *kinds, cutoff),
    ).fetchall()
    rows.sort(key=lambda r: dist.get(int(r[0]), 9.9))
    items: list[KnowledgeItem] = []
    for rid, kind, topic, body, created_at in rows:
        similarity = round(max(0.0, 1.0 - dist.get(int(rid), 1.0)), 3)
        if similarity < min_similarity:
            continue  # too weakly related -- skip rather than inject noise
        items.append(KnowledgeItem(
            research_id=int(rid), kind=str(kind),
            tag=KNOWLEDGE_KINDS.get(str(kind), str(kind)),
            topic=str(topic)[:120], created_at=str(created_at),
            excerpt=(str(body or topic) or "").strip()[:excerpt_chars],
            via="semantic", similarity=similarity,
        ))
        if len(items) >= k:
            break
    return items


def gather_knowledge(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    query_embedding: list[float] | None = None,
    kinds: list[str] | None = None,
    days: int = DEFAULT_DAYS,
    max_items: int = DEFAULT_MAX_ITEMS,
    semantic_k: int = DEFAULT_SEMANTIC_K,
) -> list[KnowledgeItem]:
    """Combine DIRECT ticker matches (primary) with SEMANTIC thematic matches.

    Direct matches (the ticker is named) come first; if a query embedding is
    given, up to `semantic_k` thematically-similar reports that do NOT name the
    ticker are appended, deduped by research_id.
    """
    direct = gather_ticker_knowledge(
        conn, ticker, kinds=kinds, days=days, max_items=max_items,
    )
    if not query_embedding:
        return direct
    seen = {i.research_id for i in direct}
    out = list(direct)
    added = 0
    for it in retrieve_semantic(
        conn, query_embedding, k=semantic_k + len(seen),
        days=max(days, SEMANTIC_DAYS), kinds=kinds, exclude_ids=seen,
    ):
        if it.research_id in seen:
            continue
        out.append(it)
        seen.add(it.research_id)
        added += 1
        if added >= semantic_k:
            break
    return out


def format_knowledge_block(items: list[KnowledgeItem]) -> str:
    """Render knowledge items as a compact tagged block for the prediction prompt."""
    if not items:
        return "(no prior deep research on this ticker yet)"
    lines = [
        "Your own prior deep research (knowledge base -- weigh it alongside the "
        "news + cases; cite it in your rationale when it applies). Items tagged "
        "(thematic) are related research that did not name this ticker directly:"
    ]
    for it in items:
        marker = " (thematic)" if it.via == "semantic" else ""
        lines.append(f"- [{it.tag} | {it.created_at[:10]}{marker}] {it.topic}")
        lines.append(f"  {it.excerpt}")
    return "\n".join(lines)


def build_ticker_knowledge_block(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    query_embedding: list[float] | None = None,
    kinds: list[str] | None = None,
    days: int = DEFAULT_DAYS,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> str:
    """Convenience: gather (direct + semantic) + format the knowledge block."""
    return format_knowledge_block(
        gather_knowledge(
            conn, ticker, query_embedding=query_embedding,
            kinds=kinds, days=days, max_items=max_items,
        )
    )
