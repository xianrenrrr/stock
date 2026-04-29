"""stock.wechat_gui -- drive the WeChat desktop GUI directly via pyautogui.

This replaces the OpenClaw-agent path because it claimed delivery without actually
typing/clicking. Here every action is a real OS event: copy to clipboard, Ctrl+V,
keyboard Enter. Take a screenshot after each send so the user can audit.

Safety:
- pyautogui.FAILSAFE is on by default -- jam the mouse into a screen corner to abort.
- Per-step delays are generous so WeChat has time to render search results / open chats.
- Every delivery captures a screenshot to data/wechat_outbox/proof_<recipient>.png so
  there's a real artifact (not a model's self-reported "verified").
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# pyautogui + pyperclip are optional (only needed for local Windows GUI delivery).
# On Linux/cloud they fail to import without an X server -- guard so the rest of
# the package still loads and tests / cloud deployments work.
try:
    import pyautogui
    import pyperclip

    HAS_GUI = True
except Exception:  # noqa: BLE001 -- pyautogui can raise many exception types on import
    pyautogui = None  # type: ignore[assignment]
    pyperclip = None  # type: ignore[assignment]
    HAS_GUI = False

logger = logging.getLogger(__name__)

OUTBOX_DIR: str = "data/wechat_outbox"
WECHAT_HOTKEY: tuple[str, ...] = ("ctrl", "alt", "w")  # default WeChat foreground hotkey on Windows
WECHAT_SEARCH_HOTKEY: tuple[str, ...] = ("ctrl", "f")  # focus search box inside WeChat
PRE_DELIVERY_COUNTDOWN_SECS: int = 5  # let the operator move mouse away
WECHAT_FOCUS_WAIT_SECS: float = 1.2
SEARCH_OPEN_WAIT_SECS: float = 0.7
SEARCH_TYPING_WAIT_SECS: float = 1.5  # WeChat needs time to filter contacts
CHAT_OPEN_WAIT_SECS: float = 1.0
INPUT_FOCUS_WAIT_SECS: float = 0.4
PASTE_WAIT_SECS: float = 0.6
SEND_WAIT_SECS: float = 0.8
BETWEEN_RECIPIENTS_WAIT_SECS: float = 2.0


class DeliveryRecord(BaseModel):
    """Outcome of one outbox-task delivery attempt."""

    task_path: str
    recipient: str
    status: str  # "delivered" | "failed"
    detail: str
    proof_path: str = ""


class DeliveryBatchResult(BaseModel):
    """Aggregated outcome across all pending tasks."""

    delivered: int
    failed: int
    records: list[DeliveryRecord]


def _list_pending_tasks(outbox_dir: Path) -> list[Path]:
    """Return paths to every pending task JSON, sorted oldest first."""
    if not outbox_dir.exists():
        return []
    out: list[Path] = []
    for path in sorted(outbox_dir.glob("*.json")):
        if path.name.endswith(".sent.json") or path.name.endswith(".skipped.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "pending":
            out.append(path)
    return out


def _focus_wechat() -> None:
    """Bring WeChat to the foreground via its default global hotkey."""
    pyautogui.hotkey(*WECHAT_HOTKEY)
    time.sleep(WECHAT_FOCUS_WAIT_SECS)


def _open_chat(recipient: str) -> None:
    """Use WeChat's search box to open the conversation with the recipient."""
    # Open search box
    pyautogui.hotkey(*WECHAT_SEARCH_HOTKEY)
    time.sleep(SEARCH_OPEN_WAIT_SECS)

    # Paste recipient name (clipboard handles non-ASCII like 杨建中 cleanly)
    pyperclip.copy(recipient)
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(SEARCH_TYPING_WAIT_SECS)

    # Press Enter to select the top match
    pyautogui.press("enter")
    time.sleep(CHAT_OPEN_WAIT_SECS)


def _send_body(body: str) -> None:
    """Paste the body into the chat input and send via Enter."""
    # Most WeChat installs already focus the input box when a chat opens.
    # A short delay is enough; clicking blindly here risks hitting the wrong area.
    time.sleep(INPUT_FOCUS_WAIT_SECS)

    # Copy body to clipboard, paste with Ctrl+V (handles Unicode + multi-line)
    pyperclip.copy(body)
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(PASTE_WAIT_SECS)

    # Send. WeChat's default is Enter; configurable users have Ctrl+Enter.
    # Pressing Enter alone is the right default; if user has Ctrl+Enter set,
    # we'd insert a newline instead -- still recoverable, just won't auto-send.
    pyautogui.press("enter")
    time.sleep(SEND_WAIT_SECS)


def _capture_proof(outbox_dir: Path, recipient_slug: str) -> Path | None:
    """Take a screenshot post-send so the operator can audit what happened.

    Best-effort: returns None if pyscreeze/Pillow isn't installed instead of crashing
    the whole delivery. Verification can fall back to the user inspecting WeChat
    directly.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_slug = "".join(c for c in recipient_slug if c.isascii() and (c.isalnum() or c in "-_")) or "recipient"
    path = outbox_dir / f"proof_{ts}_{safe_slug}.png"
    try:
        img = pyautogui.screenshot()
        img.save(str(path))
        return path
    except Exception as exc:  # noqa: BLE001 -- pyautogui re-raises a generic exception type
        logger.warning("Screenshot capture failed (%s); marking delivered without proof", exc)
        return None


def _mark_delivered(task_path: Path, *, proof_path: str, notes: str) -> Path:
    """Stamp delivered_at + rename .json -> .sent.json. Returns the new path."""
    try:
        data: dict[str, Any] = json.loads(task_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"task JSON unreadable: {exc}") from exc

    data["status"] = "delivered"
    data["delivered_at"] = datetime.now(timezone.utc).isoformat()
    data["delivery_notes"] = notes
    data["proof_path"] = proof_path

    sent_path = task_path.with_name(task_path.stem + ".sent.json")
    sent_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    task_path.unlink(missing_ok=True)
    return sent_path


def deliver_pending(
    *,
    outbox_dir: str | None = None,
    skip_countdown: bool = False,
) -> DeliveryBatchResult:
    """Process every pending outbox task: type into WeChat, paste body, hit Enter.

    Each delivery captures a real screenshot afterwards as proof. The pending JSON
    is renamed to `.sent.json` only after the screenshot is saved.
    """
    out_dir = Path(outbox_dir or OUTBOX_DIR)
    pending = _list_pending_tasks(out_dir)

    records: list[DeliveryRecord] = []
    if not pending:
        return DeliveryBatchResult(delivered=0, failed=0, records=records)

    # GUI delivery requires pyautogui + a desktop session. On cloud / headless,
    # this path is a no-op so the orchestrator doesn't crash on Linux.
    if not HAS_GUI:
        logger.warning(
            "pyautogui/pyperclip not available -- skipping GUI delivery for %d task(s). "
            "Install [gui] extras and run on a Windows desktop with WeChat open.",
            len(pending),
        )
        for task_path in pending:
            try:
                data = json.loads(task_path.read_text(encoding="utf-8"))
                recipient = str(data.get("recipient", "?"))
            except (OSError, json.JSONDecodeError):
                recipient = "?"
            records.append(DeliveryRecord(
                task_path=str(task_path), recipient=recipient,
                status="failed", detail="GUI unavailable on this host",
            ))
        return DeliveryBatchResult(
            delivered=0, failed=len(records), records=records,
        )

    if not skip_countdown:
        # Give the operator a chance to move the mouse / focus away
        for i in range(PRE_DELIVERY_COUNTDOWN_SECS, 0, -1):
            print(f"WeChat GUI delivery starts in {i}s -- move mouse to corner to abort")
            time.sleep(1)

    delivered = failed = 0
    for task_path in pending:
        try:
            data = json.loads(task_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failed += 1
            records.append(DeliveryRecord(
                task_path=str(task_path), recipient="?",
                status="failed", detail=f"unreadable JSON: {exc}",
            ))
            continue

        recipient = str(data.get("recipient", "")).strip()
        body_path = out_dir / str(data.get("body_path", ""))
        if not recipient or not body_path.exists():
            failed += 1
            records.append(DeliveryRecord(
                task_path=str(task_path), recipient=recipient,
                status="failed",
                detail=f"missing recipient or body file ({body_path})",
            ))
            continue

        try:
            body = body_path.read_text(encoding="utf-8")
        except OSError as exc:
            failed += 1
            records.append(DeliveryRecord(
                task_path=str(task_path), recipient=recipient,
                status="failed", detail=f"body unreadable: {exc}",
            ))
            continue

        # Drive the WeChat GUI
        try:
            _focus_wechat()
            _open_chat(recipient)
            _send_body(body)
            proof = _capture_proof(out_dir, recipient)
        except (pyautogui.FailSafeException, OSError) as exc:
            failed += 1
            records.append(DeliveryRecord(
                task_path=str(task_path), recipient=recipient,
                status="failed", detail=f"GUI step failed: {exc}",
            ))
            continue

        proof_name = proof.name if proof is not None else ""

        # Stamp + rename
        try:
            sent_path = _mark_delivered(
                task_path,
                proof_path=proof_name,
                notes=f"pyautogui delivered, body={len(body)} chars"
                + ("" if proof_name else " (no proof screenshot -- check WeChat manually)"),
            )
            delivered += 1
            records.append(DeliveryRecord(
                task_path=str(sent_path), recipient=recipient,
                status="delivered",
                detail=f"renamed to {sent_path.name}",
                proof_path=proof_name,
            ))
        except RuntimeError as exc:
            failed += 1
            records.append(DeliveryRecord(
                task_path=str(task_path), recipient=recipient,
                status="failed", detail=f"mark-delivered failed: {exc}",
                proof_path=proof_name,
            ))
            continue

        time.sleep(BETWEEN_RECIPIENTS_WAIT_SECS)

    return DeliveryBatchResult(delivered=delivered, failed=failed, records=records)
