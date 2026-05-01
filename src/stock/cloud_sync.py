"""stock.cloud_sync -- bidirectional sync between local laptop and Render free tier.

Local laptop (STOCK_MODE=local, default):
  - Runs the full scheduler + LLM calls + GUI delivery (current behavior)
  - Plus: every 5 min, pushes recent research notes + recipient tokens to Render
    and pulls any boss replies sat in Render's buffer

Render web service (STOCK_MODE=cloud_proxy):
  - Skips the scheduler entirely (passive)
  - Serves /channel/* dashboard endpoints from its (ephemeral) SQLite, refilled
    by the local sync push
  - Buffers boss replies in `conversations` table; local pulls them via /sync/replies

Total cost: $0/mo on Render free tier. The 5-min push from local also acts as a
keepalive ping, so the free instance never goes to sleep -- no cold-start lag for
the boss when he opens the app.

Auth: every /sync/* endpoint takes the same Bearer token as the admin /stock/*
routes (the value of `STOCK_API_TOKEN`). On the laptop side, the same value goes
into `RENDER_SYNC_TOKEN` (defaults to STOCK_API_TOKEN if unset).
"""
from __future__ import annotations

import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import httpx
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel

from stock.config import get_settings
from stock.db import get_conn

logger = logging.getLogger(__name__)

SYNC_NOTES_LOOKBACK_DAYS: int = 14
SYNC_REPLIES_DEFAULT_LOOKBACK_DAYS: int = 7
# Render free tier first request after sleep can take 60-90s while the container
# cold-starts. After that subsequent calls are fast. The 5-min keepalive prevents
# sleeps in steady state.
HTTP_TIMEOUT_SECS: float = 120.0
FEEDBACK_PATH: str = "data/wechat_feedback.md"


# ============================================================================
# Wire models -- shared by both ends of the sync.
# ============================================================================


class NoteRow(BaseModel):
    """One research_reports row in transit between laptop and Render."""

    research_id: int
    kind: str
    topic: str | None = None
    layer_focus: str | None = None
    body: str
    cost_usd: float = 0.0
    created_at: str


class TokenRow(BaseModel):
    """One recipient_tokens row."""

    token: str
    recipient: str
    created_at: str
    last_seen_at: str | None = None
    revoked: int = 0


class ReplyRow(BaseModel):
    """One conversations row (direction='inbound') flowing back to the laptop."""

    id: int
    recipient: str
    body: str
    created_at: str


class SyncNotesRequest(BaseModel):
    """POST /sync/notes body."""

    notes: list[NoteRow]


class SyncTokensRequest(BaseModel):
    """POST /sync/tokens body."""

    tokens: list[TokenRow]


class SyncWriteResponse(BaseModel):
    """Generic ack from /sync/notes + /sync/tokens."""

    upserted: int


class SyncRepliesResponse(BaseModel):
    """GET /sync/replies response."""

    replies: list[ReplyRow]
    server_now: str


class CloudSyncResult(BaseModel):
    """Outcome of one local-side sync pass."""

    notes_pushed: int
    tokens_pushed: int
    replies_pulled: int
    error: str = ""


# ============================================================================
# Cloud-side endpoints (run on Render with STOCK_MODE=cloud_proxy).
# ============================================================================


def get_db_conn() -> Iterator[sqlite3.Connection]:
    """Per-request SQLite handle; closed after the response."""
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def _require_admin(authorization: str | None = Header(default=None)) -> None:
    """Bearer-token gate using STOCK_API_TOKEN (same auth as /stock/* admin routes)."""
    settings = get_settings()
    expected = (settings.stock_api_token or "").strip()
    if not expected:
        raise PermissionError("STOCK_API_TOKEN not configured on this server")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise PermissionError("Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, expected):
        raise PermissionError("Invalid bearer token")


def post_sync_notes(
    body: SyncNotesRequest,
    _auth: None = Depends(_require_admin),
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> SyncWriteResponse:
    """Upsert research_reports rows pushed from the laptop."""
    upserted = 0
    new_notes: list[tuple[int, str, str]] = []
    for note in body.notes:
        existing = conn.execute(
            "SELECT id FROM research_reports WHERE id = ?", (note.research_id,)
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO research_reports"
                " (id, kind, topic, layer_focus, body, cost_usd, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    note.research_id, note.kind, note.topic, note.layer_focus,
                    note.body, note.cost_usd, note.created_at,
                ),
            )
            upserted += 1
            new_notes.append((note.research_id, note.kind, (note.topic or "")[:80]))
        else:
            conn.execute(
                "UPDATE research_reports SET kind=?, topic=?, layer_focus=?,"
                " body=?, cost_usd=?, created_at=? WHERE id=?",
                (
                    note.kind, note.topic, note.layer_focus,
                    note.body, note.cost_usd, note.created_at, note.research_id,
                ),
            )
    conn.commit()
    # Audit log: a new boss-bound note has arrived on Render. Routine repushes
    # of existing notes (upserted=0) stay silent so the log isn't flooded.
    for nid, kind, topic in new_notes:
        logger.info(
            "Boss-bound note received on Render: id=%d kind=%s topic=%r",
            nid, kind, topic,
        )
    return SyncWriteResponse(upserted=upserted)


def post_sync_tokens(
    body: SyncTokensRequest,
    _auth: None = Depends(_require_admin),
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> SyncWriteResponse:
    """Upsert recipient_tokens rows pushed from the laptop."""
    upserted = 0
    for tok in body.tokens:
        existing = conn.execute(
            "SELECT token FROM recipient_tokens WHERE token = ?", (tok.token,)
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO recipient_tokens"
                " (token, recipient, created_at, last_seen_at, revoked)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    tok.token, tok.recipient, tok.created_at,
                    tok.last_seen_at, tok.revoked,
                ),
            )
            upserted += 1
        else:
            conn.execute(
                "UPDATE recipient_tokens SET recipient=?, revoked=? WHERE token=?",
                (tok.recipient, tok.revoked, tok.token),
            )
    conn.commit()
    return SyncWriteResponse(upserted=upserted)


def get_sync_replies(
    since: str | None = Query(default=None),
    _auth: None = Depends(_require_admin),
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> SyncRepliesResponse:
    """Return inbound conversations rows newer than `since` (ISO-8601)."""
    if not since:
        since = (
            datetime.now(timezone.utc)
            - timedelta(days=SYNC_REPLIES_DEFAULT_LOOKBACK_DAYS)
        ).isoformat()

    rows = conn.execute(
        "SELECT id, recipient, body, created_at FROM conversations"
        " WHERE direction = 'inbound' AND created_at > ?"
        " ORDER BY created_at ASC",
        (since,),
    ).fetchall()

    return SyncRepliesResponse(
        replies=[
            ReplyRow(id=r[0], recipient=r[1], body=r[2], created_at=r[3])
            for r in rows
        ],
        server_now=datetime.now(timezone.utc).isoformat(),
    )


def create_router() -> APIRouter:
    """FastAPI router for /sync/* endpoints (cloud_proxy mode)."""
    router = APIRouter(prefix="/sync", tags=["sync"])
    router.add_api_route(
        "/notes", post_sync_notes, methods=["POST"], response_model=SyncWriteResponse,
    )
    router.add_api_route(
        "/tokens", post_sync_tokens, methods=["POST"], response_model=SyncWriteResponse,
    )
    router.add_api_route(
        "/replies", get_sync_replies, methods=["GET"], response_model=SyncRepliesResponse,
    )
    return router


# ============================================================================
# Local-side sync logic (run on the Windows laptop every 5 min).
# ============================================================================


def _read_local_notes(
    conn: sqlite3.Connection, lookback_days: int
) -> list[NoteRow]:
    """Pull recent research_reports rows from the local DB."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=lookback_days)
    ).isoformat()
    rows = conn.execute(
        "SELECT id, kind, topic, layer_focus, body, cost_usd, created_at"
        " FROM research_reports WHERE created_at >= ?"
        " ORDER BY created_at ASC",
        (cutoff,),
    ).fetchall()
    return [
        NoteRow(
            research_id=r[0], kind=r[1], topic=r[2], layer_focus=r[3],
            body=r[4], cost_usd=r[5], created_at=r[6],
        )
        for r in rows
    ]


def _read_local_tokens(conn: sqlite3.Connection) -> list[TokenRow]:
    """Pull all recipient_tokens rows from the local DB."""
    rows = conn.execute(
        "SELECT token, recipient, created_at, last_seen_at, revoked"
        " FROM recipient_tokens"
    ).fetchall()
    return [
        TokenRow(
            token=r[0], recipient=r[1], created_at=r[2],
            last_seen_at=r[3], revoked=int(r[4]),
        )
        for r in rows
    ]


def _get_last_pull_ts(conn: sqlite3.Connection) -> str:
    """Read the timestamp of the last successful reply pull (for the `since` arg)."""
    row = conn.execute(
        "SELECT value FROM cloud_sync_state WHERE key = 'last_pull_replies'"
    ).fetchone()
    if row:
        return str(row[0])
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _set_last_pull_ts(conn: sqlite3.Connection, ts: str) -> None:
    """Persist the new high-water mark so the next pull only fetches newer rows."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO cloud_sync_state (key, value, updated_at)"
        " VALUES ('last_pull_replies', ?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
        " updated_at=excluded.updated_at",
        (ts, now),
    )
    conn.commit()


def _record_pulled_reply(
    conn: sqlite3.Connection, recipient: str, body: str, created_at: str
) -> None:
    """Append the boss's reply to wechat_feedback.md so F13 picks it up next call."""
    fp = Path(FEEDBACK_PATH)
    fp.parent.mkdir(parents=True, exist_ok=True)
    ts = (created_at or datetime.now(timezone.utc).isoformat())[:16]
    quoted = "\n".join(f"> {line}" for line in body.splitlines())
    entry = (
        f"\n## {ts} -- {recipient}\n"
        f"**source**: cloud_channel\n\n"
        f"{quoted}\n"
    )
    with fp.open("a", encoding="utf-8") as fh:
        if fp.stat().st_size == 0:
            fh.write(
                "# WeChat reader feedback\n\n"
                "Append-only log of replies. F13 picks these up and adapts.\n"
            )
        fh.write(entry)
    # Conversations row is created by F13 itself; no pre-insert here so we
    # don't race the F13 inline trigger and produce duplicate rows.


def run_local_sync(conn: sqlite3.Connection) -> CloudSyncResult:
    """One sync round-trip: push notes/tokens, pull replies. Never raises."""
    settings = get_settings()
    base_url = (settings.render_sync_url or "").strip().rstrip("/")
    if not base_url:
        return CloudSyncResult(
            notes_pushed=0, tokens_pushed=0, replies_pulled=0,
            error="render_sync_url unset",
        )
    token = (settings.stock_api_token or "").strip()
    if not token:
        return CloudSyncResult(
            notes_pushed=0, tokens_pushed=0, replies_pulled=0,
            error="stock_api_token unset",
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    tokens = _read_local_tokens(conn)

    notes_pushed = 0
    tokens_pushed = 0
    replies_pulled = 0
    error = ""

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECS) as client:
            # Push tokens first (cheap, idempotent)
            if tokens:
                resp = client.post(
                    f"{base_url}/sync/tokens",
                    json={"tokens": [t.model_dump() for t in tokens]},
                    headers=headers,
                )
                resp.raise_for_status()
                tokens_pushed = int(resp.json().get("upserted", 0))

            # Pull replies the boss has typed via the dashboard since last poll
            since = _get_last_pull_ts(conn)
            resp = client.get(
                f"{base_url}/sync/replies",
                params={"since": since},
                headers=headers,
            )
            resp.raise_for_status()
            payload = resp.json()
            for reply in payload.get("replies", []) or []:
                _record_pulled_reply(
                    conn,
                    recipient=str(reply.get("recipient", "")),
                    body=str(reply.get("body", "")),
                    created_at=str(reply.get("created_at", "")),
                )
                replies_pulled += 1

            new_high_water = str(
                payload.get("server_now")
                or datetime.now(timezone.utc).isoformat()
            )
            _set_last_pull_ts(conn, new_high_water)

            # Trigger F13 inline BEFORE pushing notes so any newly-generated
            # reply note rides the same sync tick that pulled the question.
            if replies_pulled > 0:
                try:
                    from stock.orchestrator import _job_learn_from_feedback

                    _job_learn_from_feedback()
                    logger.info(
                        "Inline F13 fired after sync pulled %d replies",
                        replies_pulled,
                    )
                except Exception:
                    logger.exception("Inline F13 trigger failed")

            # Re-read notes AFTER F13 so the just-generated reply is included
            notes = _read_local_notes(conn, SYNC_NOTES_LOOKBACK_DAYS)
            if notes:
                resp = client.post(
                    f"{base_url}/sync/notes",
                    json={"notes": [n.model_dump() for n in notes]},
                    headers=headers,
                )
                resp.raise_for_status()
                notes_pushed = int(resp.json().get("upserted", 0))
    except httpx.HTTPError as exc:
        error = f"sync failed: {exc}"
        logger.warning(error)
    except Exception as exc:  # noqa: BLE001 -- never let sync crash the orchestrator
        error = f"sync unexpected error: {exc}"
        logger.exception("Cloud sync raised unexpectedly")

    return CloudSyncResult(
        notes_pushed=notes_pushed,
        tokens_pushed=tokens_pushed,
        replies_pulled=replies_pulled,
        error=error,
    )
