"""stock.conversation -- two-way WeChat conversation memory with vector recall."""
from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from stock.config import get_settings
from stock.memory import _serialize_embedding, embed

logger = logging.getLogger(__name__)


def _embeddings_enabled() -> bool:
    """False in cloud_proxy mode -- the laptop owns embedding; cloud is just a buffer."""
    return (get_settings().stock_mode or "").strip().lower() != "cloud_proxy"

CONTEXT_BODY_MAX_CHARS: int = 240
RECENT_TURNS_DEFAULT_LIMIT: int = 6
RETRIEVE_OVERSAMPLE_FACTOR: int = 4


class ConversationTurn(BaseModel):
    """One row of the conversations table."""

    id: int
    run_id: str
    recipient: str
    direction: str
    body: str
    intent: str | None = None
    intent_confidence: float | None = None
    related_research_id: int | None = None
    related_action_queue_id: int | None = None
    rewrite_id: int | None = None
    created_at: str
    embedding_idx: int | None = None
    similarity: float | None = None


def _row_to_turn(row: tuple) -> ConversationTurn:
    """Convert a SELECT row into a ConversationTurn model."""
    return ConversationTurn(
        id=int(row[0]),
        run_id=str(row[1]),
        recipient=str(row[2]),
        direction=str(row[3]),
        body=str(row[4]),
        intent=row[5],
        intent_confidence=row[6],
        related_research_id=row[7],
        related_action_queue_id=row[8],
        rewrite_id=row[9],
        created_at=str(row[10]),
        embedding_idx=row[11],
    )


def _embed_and_store(
    conn: sqlite3.Connection, conversation_id: int, body: str
) -> int | None:
    """Embed the body text and store it under conversation_embeddings."""
    if not body.strip():
        return None
    # cloud_proxy skips embedding to stay under Render free-tier 512MB ceiling;
    # the laptop re-embeds when the conversation row syncs back over /sync/replies.
    if not _embeddings_enabled():
        return None
    try:
        vector = embed(body)
    except Exception:
        logger.exception("Embed failed for conversation %d", conversation_id)
        return None
    blob = _serialize_embedding(vector)
    conn.execute(
        "DELETE FROM conversation_embeddings WHERE conversation_id = ?",
        (conversation_id,),
    )
    conn.execute(
        "INSERT INTO conversation_embeddings (conversation_id, embedding)"
        " VALUES (?, ?)",
        (conversation_id, blob),
    )
    conn.execute(
        "UPDATE conversations SET embedding_idx = ? WHERE id = ?",
        (conversation_id, conversation_id),
    )
    conn.commit()
    return conversation_id


def record_inbound(
    recipient: str,
    body: str,
    conn: sqlite3.Connection,
    *,
    related_research_id: int | None = None,
    run_id: str | None = None,
    created_at: str | None = None,
) -> int:
    """Persist an inbound (boss) message and embed it for later recall."""
    rid = run_id or str(uuid.uuid4())
    ts = created_at or datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO conversations (run_id, recipient, direction, body,"
        " related_research_id, created_at) VALUES (?, ?, 'inbound', ?, ?, ?)",
        (rid, recipient, body, related_research_id, ts),
    )
    conn.commit()
    cid = int(cursor.lastrowid or 0)
    _embed_and_store(conn, cid, body)
    return cid


def record_outbound(
    recipient: str,
    body: str,
    conn: sqlite3.Connection,
    *,
    run_id: str,
    related_research_id: int | None = None,
    related_action_queue_id: int | None = None,
    created_at: str | None = None,
) -> int:
    """Persist an outbound (our) reply that joins an inbound run_id."""
    ts = created_at or datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO conversations (run_id, recipient, direction, body,"
        " related_research_id, related_action_queue_id, created_at)"
        " VALUES (?, ?, 'outbound', ?, ?, ?, ?)",
        (run_id, recipient, body, related_research_id,
         related_action_queue_id, ts),
    )
    conn.commit()
    cid = int(cursor.lastrowid or 0)
    _embed_and_store(conn, cid, body)
    return cid


def get_run_id(conn: sqlite3.Connection, conversation_id: int) -> str:
    """Return the run_id for an existing conversation row."""
    row = conn.execute(
        "SELECT run_id FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"conversation {conversation_id} not found")
    return str(row[0])


def set_intent(
    conn: sqlite3.Connection,
    conversation_id: int,
    intent: str,
    confidence: float,
) -> None:
    """Stamp the classified intent + confidence onto an inbound row."""
    conn.execute(
        "UPDATE conversations SET intent = ?, intent_confidence = ? WHERE id = ?",
        (intent, float(confidence), conversation_id),
    )
    conn.commit()


def has_entry(
    conn: sqlite3.Connection, timestamp: str, recipient: str
) -> bool:
    """Return True if an inbound row with that timestamp+recipient already exists."""
    row = conn.execute(
        "SELECT 1 FROM conversations"
        " WHERE recipient = ? AND created_at = ? AND direction = 'inbound'"
        " LIMIT 1",
        (recipient, timestamp),
    ).fetchone()
    return row is not None


def is_duplicate_inbound(
    conn: sqlite3.Connection,
    *,
    recipient: str,
    body: str,
    exclude_id: int,
    hours: int = 6,
) -> bool:
    """Return True if an identical inbound message was already recorded recently.

    Matches on trimmed body + recipient within the last `hours`, excluding
    `exclude_id` (the just-recorded row). Used to drop accidental re-sends so a
    repeated boss message does not queue a second deep-dive or duplicate reply.
    """
    norm = (body or "").strip()
    if not norm:
        return False
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    row = conn.execute(
        "SELECT 1 FROM conversations"
        " WHERE recipient = ? AND direction = 'inbound' AND id != ?"
        " AND TRIM(body) = ? AND created_at >= ? LIMIT 1",
        (recipient, exclude_id, norm, cutoff),
    ).fetchone()
    return row is not None


def recent_turns(
    conn: sqlite3.Connection,
    *,
    recipient: str | None = None,
    limit: int = RECENT_TURNS_DEFAULT_LIMIT,
) -> list[ConversationTurn]:
    """Return the most recent turns, optionally scoped to one recipient."""
    if recipient:
        rows = conn.execute(
            "SELECT id, run_id, recipient, direction, body, intent,"
            " intent_confidence, related_research_id, related_action_queue_id,"
            " rewrite_id, created_at, embedding_idx FROM conversations"
            " WHERE recipient = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (recipient, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, run_id, recipient, direction, body, intent,"
            " intent_confidence, related_research_id, related_action_queue_id,"
            " rewrite_id, created_at, embedding_idx FROM conversations"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_turn(r) for r in rows]


def recent_instruction_ids(
    conn: sqlite3.Connection, *, hours: int = 12
) -> list[int]:
    """Return ids of inbound rows classified as 'instruction' within the window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        "SELECT id FROM conversations"
        " WHERE intent = 'instruction' AND direction = 'inbound'"
        " AND created_at >= ? ORDER BY created_at DESC",
        (cutoff,),
    ).fetchall()
    return [int(r[0]) for r in rows]


def retrieve_similar(
    query_embedding: list[float],
    conn: sqlite3.Connection,
    *,
    recipient: str | None = None,
    k: int = 5,
) -> list[ConversationTurn]:
    """Find the K most similar past turns by cosine distance."""
    blob = _serialize_embedding(query_embedding)
    fetch_count = max(k * RETRIEVE_OVERSAMPLE_FACTOR, 25)

    vec_rows = conn.execute(
        "SELECT conversation_id, distance FROM conversation_embeddings"
        " WHERE embedding MATCH ? AND k = ?",
        (blob, fetch_count),
    ).fetchall()
    if not vec_rows:
        return []

    distances: dict[int, float] = {int(r[0]): float(r[1]) for r in vec_rows}
    ids = list(distances.keys())
    placeholders = ",".join("?" * len(ids))

    if recipient:
        rows = conn.execute(
            f"SELECT id, run_id, recipient, direction, body, intent,"
            f" intent_confidence, related_research_id, related_action_queue_id,"
            f" rewrite_id, created_at, embedding_idx FROM conversations"
            f" WHERE id IN ({placeholders}) AND recipient = ?",
            (*ids, recipient),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT id, run_id, recipient, direction, body, intent,"
            f" intent_confidence, related_research_id, related_action_queue_id,"
            f" rewrite_id, created_at, embedding_idx FROM conversations"
            f" WHERE id IN ({placeholders})",
            ids,
        ).fetchall()

    out: list[ConversationTurn] = []
    for row in rows:
        turn = _row_to_turn(row)
        distance = distances.get(turn.id, 1.0)
        turn.similarity = max(0.0, 1.0 - distance)
        out.append(turn)
    out.sort(key=lambda t: t.similarity or 0.0, reverse=True)
    return out[:k]


def format_context_block(turns: list[ConversationTurn]) -> str:
    """Render recent turns as a per-recipient context block for prompts."""
    if not turns:
        return "(no prior conversation turns recorded)"

    by_recipient: dict[str, list[ConversationTurn]] = {}
    for turn in turns:
        by_recipient.setdefault(turn.recipient, []).append(turn)

    blocks: list[str] = []
    for recipient, items in by_recipient.items():
        # Sort chronologically for readability
        items_sorted = sorted(items, key=lambda t: t.created_at)
        lines: list[str] = [f"- [recipient: {recipient}]"]
        for t in items_sorted:
            who = "them" if t.direction == "inbound" else "us"
            body = t.body.replace("\n", " ")[:CONTEXT_BODY_MAX_CHARS]
            lines.append(f"  - [{t.created_at[:16]}] {who}: \"{body}\"")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)
