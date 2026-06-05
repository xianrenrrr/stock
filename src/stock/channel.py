"""stock.channel -- boss-facing /channel/ endpoints + per-recipient tokens.

Cloud deployment (Render) is API-only by default; this module adds a thin
boss-facing surface so non-technical users can consume the daily research
notes through a browser without curl. Pairs with `static/dashboard.html`,
the single-page HTML dashboard served at `GET /channel/`.

Endpoints (all require a *recipient* bearer token, not the admin token):
  GET  /channel/                     -> serve dashboard.html
  GET  /channel/api/me               -> {recipient, last_seen_at}
  GET  /channel/api/notes?days=N     -> list recent research notes
  GET  /channel/api/notes/{id}       -> single note body
  POST /channel/api/reply            -> record a reply -> wechat_feedback.md + conversations table

Tokens are minted via the `stock channel-token issue <recipient>` CLI; one
token per recipient (yjz / richard / 杨建中). Sent to the boss once via any
channel, baked into the dashboard URL on first visit (`?token=...`),
then stored in the browser's localStorage by the dashboard JS.
"""
from __future__ import annotations

import logging
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from stock.config import get_settings
from stock.db import get_conn
from stock.warning_dashboard import WarningDashboard, build_warning_dashboard

# F18: image upload feature -- the boss is lazy, snaps a screenshot, and the
# system extracts content via a vision LLM and routes it to the same intent
# pipeline as a typed reply.
UPLOAD_DIR: str = "data/wechat_inbox/uploads"
UPLOAD_MAX_BYTES: int = 8 * 1024 * 1024  # mirrors stock.vision.MAX_IMAGE_BYTES
UPLOAD_ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp"}
)

logger = logging.getLogger(__name__)

DASHBOARD_HTML_PATH: str = "src/stock/static/dashboard.html"
FEEDBACK_PATH: str = "data/wechat_feedback.md"
DEFAULT_NOTES_LOOKBACK_DAYS: int = 14
DEFAULT_NOTES_LIMIT: int = 50
TOKEN_BYTES: int = 24  # 192 bits of entropy, base64 -> 32-char string


class ChannelHTTPError(RuntimeError):
    """Domain error converted to typed JSON by the global handler."""

    def __init__(self, status_code: int, error: str, detail: str | None = None) -> None:
        super().__init__(error)
        self.status_code = status_code
        self.error = error
        self.detail = detail


class MeResponse(BaseModel):
    """GET /channel/api/me wire shape."""

    recipient: str
    last_seen_at: str | None


class NoteSummary(BaseModel):
    """One row in the dashboard's note list."""

    research_id: int
    kind: str
    topic: str | None
    layer_focus: str | None
    body_preview: str
    created_at: str


class NoteDetail(BaseModel):
    """Full body for a single note."""

    research_id: int
    kind: str
    topic: str | None
    layer_focus: str | None
    body: str
    created_at: str


class NotesListResponse(BaseModel):
    """GET /channel/api/notes wire shape."""

    notes: list[NoteSummary]


class ReplyRequest(BaseModel):
    """POST /channel/api/reply body."""

    text: str = Field(min_length=1, max_length=4000)
    note_id: int | None = None


class ReplyResponse(BaseModel):
    """POST /channel/api/reply response."""

    ok: bool
    recorded_at: str
    feedback_path: str


class ImageUploadResponse(BaseModel):
    """POST /channel/api/upload_image response."""

    ok: bool
    recorded_at: str
    filename: str
    backend: str
    description: str
    suspected_topic: str
    ticker_mentions: list[str]
    user_intent: str


# ---- DB connection dependency ---------------------------------------------


def get_db_conn() -> Iterator[sqlite3.Connection]:
    """Yield a per-request connection and close on completion."""
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


# ---- Token CRUD ------------------------------------------------------------


def mint_token(conn: sqlite3.Connection, recipient: str) -> str:
    """Issue a new recipient token and persist it. Idempotent only on conflict."""
    if not recipient.strip():
        raise ValueError("recipient is required")
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO recipient_tokens (token, recipient, created_at, revoked)"
        " VALUES (?, ?, ?, 0)",
        (token, recipient.strip(), now),
    )
    conn.commit()
    return token


def list_tokens(
    conn: sqlite3.Connection, *, include_revoked: bool = False
) -> list[dict[str, str | int | None]]:
    """Return all recipient tokens (optionally including revoked ones)."""
    if include_revoked:
        rows = conn.execute(
            "SELECT token, recipient, created_at, last_seen_at, revoked"
            " FROM recipient_tokens ORDER BY created_at DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT token, recipient, created_at, last_seen_at, revoked"
            " FROM recipient_tokens WHERE revoked = 0 ORDER BY created_at DESC"
        ).fetchall()
    return [
        {
            "token": r[0],
            "recipient": r[1],
            "created_at": r[2],
            "last_seen_at": r[3],
            "revoked": int(r[4]),
        }
        for r in rows
    ]


def revoke_token(conn: sqlite3.Connection, token: str) -> bool:
    """Mark a token revoked. Returns True if a row was changed."""
    cursor = conn.execute(
        "UPDATE recipient_tokens SET revoked = 1 WHERE token = ? AND revoked = 0",
        (token,),
    )
    conn.commit()
    return cursor.rowcount > 0


def _resolve_recipient(
    conn: sqlite3.Connection, token: str
) -> tuple[str, str | None]:
    """Validate a token and return (recipient, last_seen_at). Raises on miss."""
    row = conn.execute(
        "SELECT recipient, last_seen_at FROM recipient_tokens"
        " WHERE token = ? AND revoked = 0",
        (token,),
    ).fetchone()
    if row is None:
        raise ChannelHTTPError(401, "invalid_token", "Token unknown or revoked.")

    # Stamp last_seen_at so the admin can audit who is checking in
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE recipient_tokens SET last_seen_at = ? WHERE token = ?",
        (now, token),
    )
    conn.commit()
    return str(row[0]), row[1]


def _require_recipient(
    authorization: str | None = Header(default=None),
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> tuple[str, str | None, sqlite3.Connection]:
    """Auth dependency: returns (recipient, last_seen_at, conn) or raises 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ChannelHTTPError(401, "missing_token", "Provide Bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    recipient, last_seen = _resolve_recipient(conn, token)
    return recipient, last_seen, conn


# ---- Handlers --------------------------------------------------------------


def serve_dashboard() -> HTMLResponse:
    """Serve the single-page dashboard HTML."""
    path = Path(DASHBOARD_HTML_PATH)
    if not path.exists():
        # Fall back to a minimal inline HTML so the deploy never 500s on a missing asset.
        return HTMLResponse(
            "<h1>Dashboard asset missing</h1>"
            "<p>The static dashboard file was not bundled into this image.</p>",
            status_code=500,
        )
    return HTMLResponse(path.read_text(encoding="utf-8"))


def get_me(
    auth: tuple[str, str | None, sqlite3.Connection] = Depends(_require_recipient),
) -> MeResponse:
    """Return identity for the holder of the bearer token."""
    recipient, last_seen, _conn = auth
    return MeResponse(recipient=recipient, last_seen_at=last_seen)


def get_notes(
    days: int = Query(default=DEFAULT_NOTES_LOOKBACK_DAYS, ge=1, le=90),
    limit: int = Query(default=DEFAULT_NOTES_LIMIT, ge=1, le=200),
    auth: tuple[str, str | None, sqlite3.Connection] = Depends(_require_recipient),
) -> NotesListResponse:
    """Return recent research notes (daily + deep-dive) sorted newest first.

    Excludes kind='warning_dashboard': those warnings already render in the
    dedicated top warning panel (/channel/api/warnings), so including them in the
    feed produced a wall of near-duplicate notes every 15 minutes.
    """
    _recipient, _last_seen, conn = auth
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT id, kind, topic, layer_focus, body, created_at"
        " FROM research_reports"
        " WHERE created_at >= ? AND kind != 'warning_dashboard'"
        " ORDER BY created_at DESC, id DESC LIMIT ?",
        (cutoff, limit),
    ).fetchall()
    notes = [
        NoteSummary(
            research_id=r[0],
            kind=r[1],
            topic=r[2],
            layer_focus=r[3],
            body_preview=(r[4] or "").strip()[:280],
            created_at=r[5],
        )
        for r in rows
    ]
    return NotesListResponse(notes=notes)


def get_warnings(
    days: int = Query(default=7, ge=1, le=30),
    auth: tuple[str, str | None, sqlite3.Connection] = Depends(_require_recipient),
) -> WarningDashboard:
    """Return the top risk warnings for the dashboard."""
    _recipient, _last_seen, conn = auth
    return build_warning_dashboard(conn, days=days)


def get_note(
    research_id: int,
    auth: tuple[str, str | None, sqlite3.Connection] = Depends(_require_recipient),
) -> NoteDetail:
    """Return the full body of one stored research note."""
    _recipient, _last_seen, conn = auth
    row = conn.execute(
        "SELECT id, kind, topic, layer_focus, body, created_at"
        " FROM research_reports WHERE id = ?",
        (research_id,),
    ).fetchone()
    if row is None:
        raise ChannelHTTPError(404, "note_not_found", f"no research_reports row id={research_id}")
    return NoteDetail(
        research_id=row[0],
        kind=row[1],
        topic=row[2],
        layer_focus=row[3],
        body=row[4],
        created_at=row[5],
    )


def post_reply(
    body: ReplyRequest,
    auth: tuple[str, str | None, sqlite3.Connection] = Depends(_require_recipient),
) -> ReplyResponse:
    """Record a recipient reply.

    1. Append a structured entry to data/wechat_feedback.md (F13's input source).
    2. Insert a row into the conversations table (used by the F13 learner).
    3. The orchestrator's _job_learn_from_feedback picks it up on the next run
       and either replies (if intent=question) or queues a follow-up
       (if intent=instruction).
    """
    recipient, _last_seen, conn = auth
    text = body.text.strip()
    if not text:
        raise ChannelHTTPError(400, "empty_text", "reply text is required")

    # Append to wechat_feedback.md (the operator-edited file F13 currently reads)
    feedback_path = Path(FEEDBACK_PATH)
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    quoted = "\n".join(f"> {line}" for line in text.splitlines())
    entry = (
        f"\n## {now} -- {recipient}\n"
        f"**source**: channel\n\n"
        f"{quoted}\n"
    )
    with feedback_path.open("a", encoding="utf-8") as fp:
        if feedback_path.stat().st_size == 0:
            fp.write(
                "# WeChat reader feedback\n\n"
                "Append-only log of replies. Used by the research generator to adapt.\n"
            )
        fp.write(entry)

    # Insert into conversations table (F13 schema). Lazy import so this module
    # can load even if F13's conversation.py isn't on disk yet.
    try:
        from stock import conversation as _conv  # type: ignore[attr-defined]

        _conv.record_inbound(
            recipient=recipient,
            body=text,
            conn=conn,
            related_research_id=body.note_id,
        )
    except Exception as exc:  # noqa: BLE001 -- conversation module is optional for this path
        logger.warning("Could not record inbound to conversations table: %s", exc)

    return ReplyResponse(
        ok=True,
        recorded_at=datetime.now(timezone.utc).isoformat(),
        feedback_path=str(feedback_path),
    )


async def post_upload_image(
    image: UploadFile = File(..., description="The image file (.png/.jpg/.jpeg/.gif/.webp)"),
    caption: str = Form(default="", description="Optional caption from the user"),
    note_id: int | None = Form(default=None),
    auth: tuple[str, str | None, sqlite3.Connection] = Depends(_require_recipient),
) -> ImageUploadResponse:
    """Accept an image upload from the dashboard, run vision extraction, route as feedback.

    1. Validate the upload (size, extension).
    2. Save the file to data/wechat_inbox/uploads/<timestamp>_<recipient>.<ext>.
    3. Call stock.vision.extract_image_info to get a structured extraction.
    4. Render the extraction as a typed-feedback string and append to
       wechat_feedback.md AND insert into the conversations table.
    5. The orchestrator's _job_learn_from_feedback picks it up on the next tick
       and either replies (intent=question) or queues a follow-up
       (intent=instruction). Existing F18 vision tests cover the happy path.
    """
    # Lazy import: vision pulls anthropic + openai SDKs which are heavy
    from stock.vision import extract_image_info, format_extraction_as_feedback

    recipient, _last_seen, conn = auth

    if image.filename is None:
        raise ChannelHTTPError(400, "missing_filename", "uploaded file has no filename")
    suffix = Path(image.filename).suffix.lower()
    if suffix not in UPLOAD_ALLOWED_EXTENSIONS:
        raise ChannelHTTPError(
            400,
            "unsupported_extension",
            f"got {suffix!r}; allowed: {sorted(UPLOAD_ALLOWED_EXTENSIONS)}",
        )

    raw = await image.read()
    if len(raw) == 0:
        raise ChannelHTTPError(400, "empty_image", "uploaded file is empty")
    if len(raw) > UPLOAD_MAX_BYTES:
        raise ChannelHTTPError(
            413,
            "image_too_large",
            f"got {len(raw):,} bytes; cap is {UPLOAD_MAX_BYTES:,}",
        )

    # Persist to disk under a deterministic name so the orchestrator + auditor
    # can find it later. Strip dangerous chars from the recipient to keep it a
    # safe path component.
    safe_recipient = re.sub(r"[^A-Za-z0-9_\-]", "_", recipient) or "anon"
    upload_dir = Path(UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_filename = f"{stamp}_{safe_recipient}{suffix}"
    image_path = upload_dir / safe_filename
    image_path.write_bytes(raw)
    logger.info(
        "channel: stored upload %s (%d bytes) from %s",
        image_path, len(raw), recipient,
    )

    # When running as cloud_proxy (Render), DO NOT call vision. Render is a
    # passive relay; the local laptop pulls the image and runs Codex CLI vision
    # against the downloaded file.
    settings = get_settings()
    is_cloud_proxy = (settings.stock_mode or "").strip().lower() == "cloud_proxy"

    if is_cloud_proxy:
        # Skip vision entirely on Render. Local will do it.
        feedback_body = (
            f"[image_pending_local_vision] {safe_filename}\n"
            + (f"[caption] {caption.strip()}\n" if caption.strip() else "")
            + f"[recipient] {recipient}\n"
            + f"[uploaded_at] {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
        )
        extraction = type("StubExtraction", (), {
            "backend": "deferred_to_local",
            "description": f"Image stored on cloud proxy; awaiting local vision: {safe_filename}",
            "suspected_topic": safe_filename,
            "ticker_mentions": [],
            "user_intent": "unknown",
            "extracted_text": "",
            "cost_usd": 0.0,
        })()
        logger.info(
            "channel[cloud_proxy]: deferred vision for %s; local will pull via /sync/upload",
            safe_filename,
        )
    else:
        # Extract structured info via the vision pipeline (best-effort, never raises)
        extraction = extract_image_info(image_path, conn, caption=caption or "")
        feedback_body = format_extraction_as_feedback(
            extraction, image_filename=safe_filename, caption=caption or "",
        )
    feedback_path = Path(FEEDBACK_PATH)
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    now_min = datetime.now(timezone.utc).isoformat(timespec="minutes")
    quoted = "\n".join(f"> {line}" for line in feedback_body.splitlines())
    entry = (
        f"\n## {now_min} -- {recipient}\n"
        f"**source**: channel_image\n"
        f"**image**: {image_path}\n"
        f"**vision_backend**: {extraction.backend}\n\n"
        f"{quoted}\n"
    )
    with feedback_path.open("a", encoding="utf-8") as fp:
        if feedback_path.stat().st_size == 0:
            fp.write(
                "# WeChat reader feedback\n\n"
                "Append-only log of replies. Used by the research generator to adapt.\n"
            )
        fp.write(entry)

    # Mirror into conversations table so F13 sees it via the same path as
    # /channel/api/reply text messages.
    try:
        from stock import conversation as _conv

        _conv.record_inbound(
            recipient=recipient,
            body=feedback_body,
            conn=conn,
            related_research_id=note_id,
        )
    except Exception as exc:  # noqa: BLE001 -- conversation module is optional for this path
        logger.warning("Could not record image inbound to conversations table: %s", exc)

    return ImageUploadResponse(
        ok=True,
        recorded_at=datetime.now(timezone.utc).isoformat(),
        filename=safe_filename,
        backend=extraction.backend,
        description=extraction.description,
        suspected_topic=extraction.suspected_topic,
        ticker_mentions=extraction.ticker_mentions,
        user_intent=extraction.user_intent,
    )


# ---- Router factory --------------------------------------------------------


def create_router() -> APIRouter:
    """Build the FastAPI router for /channel/* routes."""
    router = APIRouter(prefix="/channel", tags=["channel"])

    # Dashboard HTML at /channel/ (no auth -- the page itself prompts for token)
    router.add_api_route(
        "/",
        serve_dashboard,
        methods=["GET"],
        response_class=HTMLResponse,
    )

    # JSON API at /channel/api/* (bearer-token auth on every route)
    router.add_api_route(
        "/api/me",
        get_me,
        methods=["GET"],
        response_model=MeResponse,
    )
    router.add_api_route(
        "/api/notes",
        get_notes,
        methods=["GET"],
        response_model=NotesListResponse,
    )
    router.add_api_route(
        "/api/notes/{research_id}",
        get_note,
        methods=["GET"],
        response_model=NoteDetail,
    )
    router.add_api_route(
        "/api/warnings",
        get_warnings,
        methods=["GET"],
        response_model=WarningDashboard,
    )
    router.add_api_route(
        "/api/reply",
        post_reply,
        methods=["POST"],
        response_model=ReplyResponse,
    )
    router.add_api_route(
        "/api/upload_image",
        post_upload_image,
        methods=["POST"],
        response_model=ImageUploadResponse,
    )
    return router


# ---- Exception handler -----------------------------------------------------


async def channel_exception_handler(_request: object, exc: Exception) -> JSONResponse:
    """Convert ChannelHTTPError to typed JSON; everything else 500s generically."""
    if isinstance(exc, ChannelHTTPError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error, "detail": exc.detail},
        )
    logger.exception("Unhandled /channel/ error")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error"},
    )
