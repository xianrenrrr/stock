"""stock.wechat -- queue research messages for OpenClaw to deliver via WeChat GUI."""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from pydantic import BaseModel

from stock.config import get_settings

logger = logging.getLogger(__name__)

RECIPIENTS_PATH: str = "data/wechat_recipients.yaml"
OUTBOX_DIR: str = "data/wechat_outbox"
HTTP_TIMEOUT_SECS: float = 10.0
OUTBOX_ABS_PATH: str = str(Path(OUTBOX_DIR).resolve())
OPENCLAW_CONFIG_PATH: str = str(Path.home() / ".openclaw" / "openclaw.json")
OPENCLAW_SESSIONS_DIR: str = str(Path.home() / ".openclaw" / "agents" / "main" / "sessions")
INSTRUCTIONS_FILENAME: str = "INSTRUCTIONS.md"
OPENCLAW_DELIVERY_MESSAGE: str = (
    "Deliver every pending WeChat outbox task. "
    f"Read {OUTBOX_ABS_PATH}\\{INSTRUCTIONS_FILENAME} for the procedure. "
    f"For every *.json file in {OUTBOX_ABS_PATH} whose status is 'pending' "
    "(skip *.sent.json and *.skipped.json): "
    "(1) read recipient + body_path from the JSON, "
    "(2) read the body text from the matching .txt, "
    "(3) bring WeChat to foreground (click the icon on the lower taskbar), "
    "(4) type the recipient name into WeChat's top search box, click the matching contact, "
    "(5) paste the body into the chat input, press Enter to send, "
    "(6) screenshot to verify the last message bubble matches the body, "
    "(7) rename the JSON from <name>.json to <name>.sent.json and stamp delivered_at "
    "with current ISO-8601 UTC timestamp. "
    "If a step fails, write delivery_notes describing the failure and STOP for that task "
    "(do NOT rename to .sent.json) so the next run can retry."
)


class Recipient(BaseModel):
    """A single WeChat recipient entry."""

    alias: str
    nickname: str = ""
    enabled: bool = True


class SendResult(BaseModel):
    """Outcome of a single push attempt."""

    recipient: str
    status: str
    detail: str = ""
    log_id: int | None = None


class BroadcastResult(BaseModel):
    """Aggregated outcome of a broadcast."""

    sent: int
    failed: int
    queued: int
    results: list[SendResult]


def load_recipients(path: str | None = None) -> list[Recipient]:
    """Read enabled recipients from the YAML config (skips disabled rows)."""
    cfg_path = Path(path or RECIPIENTS_PATH)
    if not cfg_path.exists():
        return []

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    rows = raw.get("recipients") or []
    out: list[Recipient] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rec = Recipient(
            alias=str(row.get("alias", "")).strip(),
            nickname=str(row.get("nickname", "")).strip(),
            enabled=bool(row.get("enabled", True)),
        )
        if rec.alias and rec.enabled:
            out.append(rec)
    return out


def _ascii_slug(recipient: str, *, fallback: str = "recipient") -> str:
    """Produce an ASCII-only filename slug from a recipient alias.

    Chinese / non-ASCII chars get mangled to '???' by some Windows tooling, which
    prevents downstream tools from reading the outbox files. We keep the original
    name inside the JSON sidecar so OpenClaw still uses it when searching WeChat.
    """
    ascii_chars = [c for c in recipient if c.isascii() and (c.isalnum() or c in "-_")]
    slug = "".join(ascii_chars)
    if slug:
        return slug
    # Pure non-ASCII alias -- hash it so the filename is stable but ASCII-safe
    import hashlib

    digest = hashlib.sha1(recipient.encode("utf-8")).hexdigest()[:8]
    return f"{fallback}_{digest}"


def _log_outbox_file(
    recipient: str, body: str, *, research_id: int | None = None
) -> Path:
    """Write the message + a JSON sidecar so OpenClaw can pick it up cleanly.

    Layout per push:
      data/wechat_outbox/<ts>_<slug>.txt   -- the message body, exact text to paste
      data/wechat_outbox/<ts>_<slug>.json  -- {recipient, status:"pending", body_path, ...}

    `slug` is always ASCII-safe (Chinese aliases get hashed) so the agent's read tool
    on Windows doesn't mangle filenames. The original recipient string is preserved
    inside the JSON sidecar for the agent to use when typing into WeChat search.

    OpenClaw renames the .json to .sent.json after delivery; the system never
    deletes outbox files (kept for audit / replay).
    """
    out_dir = Path(OUTBOX_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = _ascii_slug(recipient)
    base = f"{ts}_{slug}"

    body_path = out_dir / f"{base}.txt"
    body_path.write_text(body, encoding="utf-8")

    task_path = out_dir / f"{base}.json"
    task = {
        "recipient": recipient,
        "status": "pending",
        "body_path": str(body_path.name),
        "body_chars": len(body),
        "research_id": research_id,
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "delivered_at": None,
        "delivery_notes": None,
    }
    task_path.write_text(
        json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return body_path


def list_pending_outbox() -> list[dict[str, Any]]:
    """Return every pending task JSON in the outbox (status == 'pending')."""
    out_dir = Path(OUTBOX_DIR)
    if not out_dir.exists():
        return []
    pending: list[dict[str, Any]] = []
    for path in sorted(out_dir.glob("*.json")):
        # .sent.json = delivered, .skipped.json = deliberately bypassed; never "pending"
        if path.name.endswith(".sent.json") or path.name.endswith(".skipped.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "pending":
            data["_task_path"] = str(path)
            pending.append(data)
    return pending


def mark_outbox_delivered(
    task_filename: str, *, notes: str | None = None
) -> bool:
    """Rename a pending task to <base>.sent.json and stamp delivered_at."""
    out_dir = Path(OUTBOX_DIR)
    src = out_dir / task_filename
    if not src.exists():
        return False
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    data["status"] = "delivered"
    data["delivered_at"] = datetime.now(timezone.utc).isoformat()
    if notes:
        data["delivery_notes"] = notes

    dst = src.with_name(src.stem + ".sent.json")
    dst.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    src.unlink(missing_ok=True)
    return True


def _record_send(
    conn: sqlite3.Connection,
    *,
    recipient: str,
    body: str,
    status: str,
    detail: str,
    research_id: int | None,
) -> int:
    """Append a row to the wechat_log table and return its id."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO wechat_log (recipient, body, status, detail, research_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (recipient, body, status, detail, research_id, now),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)


def _http_post_message(url: str, payload: dict[str, Any], token: str) -> tuple[bool, str]:
    """POST the payload to the bridge. Return (ok, detail)."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECS) as client:
            resp = client.post(url, json=payload, headers=headers)
        if 200 <= resp.status_code < 300:
            return True, f"HTTP {resp.status_code}"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except httpx.HTTPError as exc:
        return False, f"transport error: {exc}"


def send_message(
    recipient: str,
    body: str,
    conn: sqlite3.Connection,
    *,
    research_id: int | None = None,
) -> SendResult:
    """Send a single message to one recipient.

    Order of attempts:
    1. HTTP POST to WECHAT_PUSH_URL (if configured) — preferred.
    2. Fallback: write to data/wechat_outbox/<ts>_<alias>.txt with status=queued.
    """
    settings = get_settings()
    url = (settings.wechat_push_url or "").strip()
    token = (settings.wechat_push_token or "").strip()
    field_to = settings.wechat_push_field_to or "to"
    field_text = settings.wechat_push_field_text or "text"

    # Attempt HTTP delivery first when an endpoint is configured
    if url:
        payload = {field_to: recipient, field_text: body}
        ok, detail = _http_post_message(url, payload, token)
        status = "sent" if ok else "failed"
        if not ok:
            backup = _log_outbox_file(recipient, body, research_id=research_id)
            detail = f"{detail}; mirrored to {backup}"
        log_id = _record_send(
            conn,
            recipient=recipient,
            body=body,
            status=status,
            detail=detail,
            research_id=research_id,
        )
        if not ok:
            logger.warning("WeChat push failed for %s: %s", recipient, detail)
        else:
            logger.info("WeChat push sent to %s (%s chars)", recipient, len(body))
        return SendResult(recipient=recipient, status=status, detail=detail, log_id=log_id)

    # Legacy GUI-delivery mode: queue the task for manual pickup. OpenClaw
    # auto-spawn is disabled by default because Boss-app sync + email are safer.
    backup = _log_outbox_file(recipient, body, research_id=research_id)
    detail = f"queued for manual GUI delivery: {backup}"
    log_id = _record_send(
        conn,
        recipient=recipient,
        body=body,
        status="queued",
        detail=detail,
        research_id=research_id,
    )
    logger.info("WeChat push queued for manual GUI delivery: %s -> %s", recipient, backup)
    return SendResult(recipient=recipient, status="queued", detail=detail, log_id=log_id)


def _load_openclaw_gateway_token() -> str:
    """Read the gateway auth token from ~/.openclaw/openclaw.json (best-effort).

    Returns "" if the file doesn't exist or doesn't have the expected shape.
    The OpenClaw CLI requires this token to dispatch agent commands -- without it
    the gateway returns "1008: pairing required".
    """
    cfg_path = Path(OPENCLAW_CONFIG_PATH)
    if not cfg_path.exists():
        return ""
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    gateway = cfg.get("gateway") or {}
    auth = gateway.get("auth") or {}
    token = auth.get("token") or ""
    return str(token).strip()


def _purge_stale_session_locks() -> int:
    """Delete any orphaned `<session>.jsonl.lock` files in the OpenClaw sessions dir.

    OpenClaw doesn't release session locks cleanly when an agent CLI run is killed
    or hits a fatal error -- a leftover lock blocks every subsequent run with
    "session file locked (timeout 10000ms)". Sweep the lock files before each
    spawn so each delivery starts clean. Returns the number of locks removed.
    """
    sessions_dir = Path(OPENCLAW_SESSIONS_DIR)
    if not sessions_dir.exists():
        return 0
    removed = 0
    for lock_path in sessions_dir.glob("*.jsonl.lock"):
        try:
            lock_path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def trigger_openclaw_delivery() -> tuple[bool, str]:
    """Fire the OpenClaw CLI in the background to deliver pending outbox tasks.

    Returns (ok, detail). Never raises -- a missing or broken OpenClaw is a soft failure,
    so the daily push still succeeds (the .txt files remain queued for manual delivery).
    """
    import os

    settings = get_settings()
    if not settings.openclaw_auto_deliver:
        return False, "openclaw_auto_deliver disabled in settings"

    # Sweep any orphaned session locks left by prior runs (OpenClaw doesn't always
    # release them cleanly) so this spawn isn't blocked by "session file locked".
    purged = _purge_stale_session_locks()
    if purged:
        logger.info("Purged %d stale OpenClaw session lock(s) before trigger", purged)

    # Resolve the openclaw binary on PATH so the subprocess call is robust on Windows
    bin_name = (settings.openclaw_bin or "openclaw").strip()
    resolved = shutil.which(bin_name)
    if resolved is None:
        return False, f"OpenClaw CLI not found on PATH (looked for {bin_name!r})"

    agent_name = (settings.openclaw_agent or "main").strip()
    # Fresh session-id per invocation so each run gets its own session file (no
    # stale .lock conflicts). --local runs embedded so we skip the gateway/pairing
    # wall — the OpenClaw 'main' agent's tools (screen capture, mouse) are loaded
    # in-process and use the model API keys from this environment.
    session_id = f"stock-deliver-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    cmd = [
        resolved,
        "agent",
        "--local",
        "--agent", agent_name,
        "--session-id", session_id,
        "--message", OPENCLAW_DELIVERY_MESSAGE,
    ]

    # Inject the gateway auth token so the CLI bypasses the "pairing required" gate.
    # Token order: explicit env var wins, otherwise auto-load from ~/.openclaw/openclaw.json
    env = os.environ.copy()
    token = env.get("OPENCLAW_GATEWAY_TOKEN", "").strip()
    if not token:
        token = _load_openclaw_gateway_token()
    if not token:
        return False, (
            "no OpenClaw gateway token found -- set OPENCLAW_GATEWAY_TOKEN env or "
            f"populate gateway.auth.token in {OPENCLAW_CONFIG_PATH}"
        )
    env["OPENCLAW_GATEWAY_TOKEN"] = token

    # Spawn detached so the caller doesn't block on the agent run; output is logged
    # to data/wechat_outbox/openclaw_trigger.log so we can audit failures later.
    log_path = Path(OUTBOX_DIR) / "openclaw_trigger.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_handle = open(log_path, "ab")
        creationflags = 0
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP detaches from this console so closing the parent
            # doesn't kill the trigger; DETACHED_PROCESS would also work but loses logs.
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        subprocess.Popen(
            cmd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            cwd=str(Path.cwd()),
            env=env,
        )
    except (OSError, ValueError) as exc:
        return False, f"failed to spawn openclaw: {exc}"

    return True, f"spawned: {' '.join(cmd[:4])} (logs at {log_path})"


def broadcast(
    body: str,
    conn: sqlite3.Connection,
    *,
    recipients: list[Recipient] | None = None,
    research_id: int | None = None,
    auto_trigger_openclaw: bool = False,
) -> BroadcastResult:
    """Send the same body to every enabled recipient.

    When `auto_trigger_openclaw` is True and outbox-mode is in use, also fire
    the OpenClaw CLI so the agent picks up the freshly queued tasks and clicks them
    through WeChat without manual intervention. This is legacy and defaults OFF.
    """
    targets = recipients if recipients is not None else load_recipients()
    if not targets:
        logger.warning("WeChat broadcast skipped: no enabled recipients")
        return BroadcastResult(sent=0, failed=0, queued=0, results=[])

    results: list[SendResult] = []
    sent = failed = queued = 0
    for rec in targets:
        result = send_message(rec.alias, body, conn, research_id=research_id)
        results.append(result)
        if result.status == "sent":
            sent += 1
        elif result.status == "failed":
            failed += 1
        else:
            queued += 1

    # If anything landed in the outbox, kick OpenClaw so it delivers automatically
    if auto_trigger_openclaw and queued > 0:
        ok, detail = trigger_openclaw_delivery()
        if ok:
            logger.info("OpenClaw delivery triggered: %s", detail)
        else:
            logger.warning("OpenClaw auto-trigger skipped: %s", detail)

    return BroadcastResult(sent=sent, failed=failed, queued=queued, results=results)
