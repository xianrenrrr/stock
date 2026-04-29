"""stock.wechat_inbox -- pull replies from WeChat + record feedback to disk.

Workflow:
  1. `pull_chat_screenshots()` drives WeChat GUI to open each recipient's chat and
     captures a screenshot of the conversation area. Screenshots land in
     `data/wechat_inbox/<ts>_<recipient>.png`.
  2. The user (or a transcription pass) extracts the boss's reply text and calls
     `append_feedback(recipient, text)` to append a structured entry to
     `data/wechat_feedback.md`.
  3. The research generator reads the last N entries via `recent_feedback_block()`
     and includes them in the LLM prompt so subsequent pushes adapt.

This file is intentionally narrow: GUI capture + MD append + read-back for prompts.
Transcription (OCR / vision LLM) is a separate concern; for now we save the image and
let the operator add structured text via the `stock add-feedback` CLI.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# pyautogui + pyperclip are optional (cloud / headless installs skip them).
try:
    import pyautogui
    import pyperclip

    HAS_GUI = True
except Exception:  # noqa: BLE001 -- pyautogui import can fail many ways without X server
    pyautogui = None  # type: ignore[assignment]
    pyperclip = None  # type: ignore[assignment]
    HAS_GUI = False

from pydantic import BaseModel

from stock.wechat import Recipient, load_recipients
from stock.wechat_gui import (
    CHAT_OPEN_WAIT_SECS,
    SEARCH_OPEN_WAIT_SECS,
    SEARCH_TYPING_WAIT_SECS,
    WECHAT_FOCUS_WAIT_SECS,
    WECHAT_HOTKEY,
    WECHAT_SEARCH_HOTKEY,
)

logger = logging.getLogger(__name__)

INBOX_DIR: str = "data/wechat_inbox"
FEEDBACK_PATH: str = "data/wechat_feedback.md"
FEEDBACK_LOOKBACK_DAYS: int = 14


class ChatCapture(BaseModel):
    """One screenshot of a recipient's WeChat chat."""

    recipient: str
    path: str
    taken_at: str
    note: str = ""


class FeedbackEntry(BaseModel):
    """One parsed entry from the feedback log."""

    timestamp: str
    recipient: str
    source: str
    text: str


def _ascii_slug(recipient: str, *, fallback: str = "recipient") -> str:
    """Same ASCII-slug rule the outbox uses, kept here to avoid import cycle."""
    ascii_chars = [c for c in recipient if c.isascii() and (c.isalnum() or c in "-_")]
    slug = "".join(ascii_chars)
    if slug:
        return slug
    import hashlib

    digest = hashlib.sha1(recipient.encode("utf-8")).hexdigest()[:8]
    return f"{fallback}_{digest}"


def _open_recipient_chat(recipient: str) -> None:
    """Bring WeChat to foreground and open the chat with `recipient`."""
    pyautogui.hotkey(*WECHAT_HOTKEY)
    time.sleep(WECHAT_FOCUS_WAIT_SECS)

    pyautogui.hotkey(*WECHAT_SEARCH_HOTKEY)
    time.sleep(SEARCH_OPEN_WAIT_SECS)

    pyperclip.copy(recipient)
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(SEARCH_TYPING_WAIT_SECS)

    pyautogui.press("enter")
    time.sleep(CHAT_OPEN_WAIT_SECS)


def _capture(path: Path) -> bool:
    """Best-effort full-screen capture. Returns True on success."""
    try:
        img = pyautogui.screenshot()
        img.save(str(path))
        return True
    except Exception as exc:  # noqa: BLE001 -- pyscreeze raises generic types
        logger.warning("Inbox screenshot failed for %s: %s", path.name, exc)
        return False


def pull_chat_screenshots(
    *, recipients: Iterable[Recipient] | None = None
) -> list[ChatCapture]:
    """For every enabled recipient, open their chat and snapshot the conversation.

    No-op on headless / cloud hosts where pyautogui isn't available.
    """
    targets = list(recipients) if recipients is not None else load_recipients()
    if not targets:
        logger.warning("Inbox pull skipped: no enabled recipients")
        return []

    if not HAS_GUI:
        logger.warning(
            "pyautogui not available -- skipping inbox snapshot for %d recipient(s)",
            len(targets),
        )
        return []

    out_dir = Path(INBOX_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    captures: list[ChatCapture] = []
    for rec in targets:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = _ascii_slug(rec.alias)
        path = out_dir / f"{ts}_{slug}.png"
        try:
            _open_recipient_chat(rec.alias)
            ok = _capture(path)
            captures.append(
                ChatCapture(
                    recipient=rec.alias,
                    path=str(path),
                    taken_at=datetime.now(timezone.utc).isoformat(),
                    note="screenshot taken" if ok else "screenshot failed",
                )
            )
        except (pyautogui.FailSafeException, OSError) as exc:
            captures.append(
                ChatCapture(
                    recipient=rec.alias,
                    path="",
                    taken_at=datetime.now(timezone.utc).isoformat(),
                    note=f"GUI step failed: {exc}",
                )
            )
        time.sleep(1.5)
    return captures


def append_feedback(
    recipient: str,
    text: str,
    *,
    source: str = "manual",
    now_iso: str | None = None,
) -> Path:
    """Append a feedback entry to data/wechat_feedback.md (markdown, append-only)."""
    if not text.strip():
        raise ValueError("feedback text is required")

    path = Path(FEEDBACK_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    ts = now_iso or datetime.now(timezone.utc).isoformat(timespec="minutes")
    quoted = "\n".join(f"> {line}" for line in text.strip().splitlines())

    entry = (
        f"\n## {ts} -- {recipient}\n"
        f"**source**: {source}\n\n"
        f"{quoted}\n"
    )
    with path.open("a", encoding="utf-8") as fp:
        if path.stat().st_size == 0:
            fp.write(
                "# WeChat reader feedback\n\n"
                "Append-only log of replies from research-note recipients. Used by the\n"
                "research generator to adapt subsequent notes.\n"
            )
        fp.write(entry)
    return path


def read_feedback_entries(*, lookback_days: int = FEEDBACK_LOOKBACK_DAYS) -> list[FeedbackEntry]:
    """Parse the feedback MD file into structured entries (best-effort)."""
    path = Path(FEEDBACK_PATH)
    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8")
    cutoff = datetime.now(timezone.utc).timestamp() - (lookback_days * 86400)

    entries: list[FeedbackEntry] = []
    current: dict[str, str] | None = None
    body_lines: list[str] = []

    def _flush() -> None:
        if current is None:
            return
        text = "\n".join(line[2:] if line.startswith("> ") else line for line in body_lines).strip()
        if not text:
            return
        try:
            ts_dt = datetime.fromisoformat(current["timestamp"].rstrip("Z"))
        except ValueError:
            return
        if ts_dt.timestamp() < cutoff:
            return
        entries.append(
            FeedbackEntry(
                timestamp=current["timestamp"],
                recipient=current["recipient"],
                source=current.get("source", "manual"),
                text=text,
            )
        )

    for line in raw.splitlines():
        if line.startswith("## "):
            _flush()
            header = line[3:].strip()
            if " -- " in header:
                ts, recipient = header.split(" -- ", 1)
                current = {"timestamp": ts.strip(), "recipient": recipient.strip()}
                body_lines = []
            else:
                current = None
                body_lines = []
        elif current is not None and line.startswith("**source**:"):
            current["source"] = line.split(":", 1)[1].strip()
        elif current is not None:
            body_lines.append(line)
    _flush()
    return entries


def recent_feedback_block(*, max_entries: int = 8) -> str:
    """Render the last N feedback entries as a text block for the research prompt."""
    entries = read_feedback_entries()
    if not entries:
        return "(no recent reader feedback recorded -- run `stock pull-feedback` then `stock add-feedback`)"

    # Most recent first, capped
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    entries = entries[:max_entries]

    lines: list[str] = []
    for e in entries:
        lines.append(f"- [{e.timestamp[:16]}] **{e.recipient}** ({e.source}): {e.text[:400]}")
    return "\n".join(lines)
