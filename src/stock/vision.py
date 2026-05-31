"""stock.vision -- extract structured info from a user-uploaded image.

F18: the boss is too lazy to type. They snap a screenshot of a chart, news
headline, broker app, group-chat message, etc. and upload it via the dashboard.
This module reads the image with a vision-capable LLM and returns a structured
extraction the existing intent-classify -> reply pipeline can consume as if it
were a typed message.

Backend choice (lazy-evaluated, never raises at import):
- Codex CLI with `codex exec --image <file>` is the default local vision path.
- Anthropic Claude vision remains an optional fallback when configured.
- If neither path works, returns a graceful stub so the upload still gets logged
  as a typed-feedback entry with the filename. MiniMax is not used.

Cost: per-image vision calls are tiny; we still log them to llm_calls so the
operator can spot a runaway upload spammer in the daily review.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import anthropic
from pydantic import BaseModel

from stock.config import get_settings
from stock.models import (
    CODEX_CLI_CORE_BIN,
    CODEX_CLI_CORE_MODEL_NAME,
    CODEX_CLI_CORE_TIMEOUT_SECS,
    PRICING,
    _looks_like_codex_credit_limit,
    parse_llm_json,
)

logger = logging.getLogger(__name__)

VISION_PROMPT_PATH: str = "prompts/vision_extract.txt"
VISION_CLAUDE_MODEL: str = "claude-opus-4-7"
VISION_MAX_TOKENS: int = 800
SUPPORTED_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
MAX_IMAGE_BYTES: int = 8 * 1024 * 1024  # 8 MB upload cap

_TICKER_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Z]{2,5}|[0-9]{4,6}\.(?:SS|SZ|HK|TW))(?![A-Za-z0-9])"
)
_TICKER_STOPWORDS: frozenset[str] = frozenset({
    "AI", "API", "AM", "PM", "USD", "CNY", "EPS", "GDP", "CEO", "CFO",
    "AND", "FOR", "THE", "PER", "ETC", "OK", "FYI", "TBD", "USA", "EU",
    "NDA", "IPO", "ETF", "OEM", "BOM", "ASP", "QOQ", "YOY", "BUY", "SELL",
    "HOLD", "LONG", "SHORT", "CALL", "PUT", "BTC", "ETH",
})


class ImageExtraction(BaseModel):
    """Result of running an uploaded image through a vision LLM."""

    description: str          # 1-3 sentence prose summary of the image
    extracted_text: str       # OCR-style raw text visible in the image (may be empty)
    ticker_mentions: list[str]  # tickers detected in the image, deduped + filtered
    suspected_topic: str      # short-phrase topic guess (e.g. "AVGO Q3 earnings preview")
    user_intent: str          # "question" | "instruction" | "share" | "unknown"
    backend: str              # "codex_cli" | "anthropic" | "stub"
    cost_usd: float           # logged to llm_calls
    duration_ms: int


@lru_cache(maxsize=1)
def _load_vision_prompt() -> str:
    """Load the structured-JSON vision prompt; cached after first read."""
    path = Path(VISION_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Vision prompt not found at {path}")
    return path.read_text(encoding="utf-8").strip()


def _detect_mime(image_path: Path) -> str:
    """Map a file extension to a vision-API mime type."""
    suffix = image_path.suffix.lower()
    mime = SUPPORTED_MIME_TYPES.get(suffix)
    if mime is None:
        raise ValueError(
            f"Unsupported image extension {suffix!r}. Allowed: "
            + ", ".join(sorted(SUPPORTED_MIME_TYPES))
        )
    return mime


def _read_and_encode(image_path: Path) -> tuple[str, str]:
    """Read the image off disk, base64-encode it, return (b64, mime)."""
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    raw = image_path.read_bytes()
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image {image_path.name} is {len(raw):,} bytes, exceeds"
            f" {MAX_IMAGE_BYTES:,} byte cap"
        )
    mime = _detect_mime(image_path)
    return base64.standard_b64encode(raw).decode("ascii"), mime


def _filter_tickers(raw: list[str]) -> list[str]:
    """Dedupe, normalize, drop common stopwords. Cap at 25 for portfolio screenshots."""
    seen: list[str] = []
    for tok in raw:
        t = (tok or "").strip().upper()
        if not t or t in _TICKER_STOPWORDS:
            continue
        if not _TICKER_RE.fullmatch(t):
            continue
        if t in seen:
            continue
        seen.append(t)
        if len(seen) >= 25:
            break
    return seen


def _coerce_intent(raw: str) -> str:
    """Snap the LLM's intent guess onto our four-class set."""
    cleaned = (raw or "").strip().lower()
    if cleaned in ("question", "instruction", "share", "unknown"):
        return cleaned
    return "unknown"


def _log_call(
    conn: sqlite3.Connection,
    *,
    backend: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    duration_ms: int,
    caller: str,
) -> None:
    """Mirror the llm_calls log shape from models.LLMClient."""
    conn.execute(
        "INSERT INTO llm_calls"
        " (model, provider, input_tokens, output_tokens,"
        " cost_usd, duration_ms, caller, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            model, backend, input_tokens, output_tokens,
            cost_usd, duration_ms, caller,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def _call_anthropic_vision(
    image_b64: str, mime: str, caption: str
) -> tuple[str, int, int, float, int]:
    """Run the vision call against Anthropic. Returns (raw_json, in_toks, out_toks, cost, ms)."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("Anthropic key not configured")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    system_prompt = _load_vision_prompt()
    user_text = (
        f"Optional caption from the user: {caption.strip() or '(none)'}\n\n"
        "Analyze the image and respond with the JSON schema described above."
    )

    start = time.perf_counter()
    response = client.messages.create(
        model=VISION_CLAUDE_MODEL,
        max_tokens=VISION_MAX_TOKENS,
        system=[{"type": "text", "text": system_prompt}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    )
    duration_ms = int((time.perf_counter() - start) * 1000)

    content = response.content[0].text if response.content else ""
    in_toks = response.usage.input_tokens
    out_toks = response.usage.output_tokens
    pricing = PRICING.get(VISION_CLAUDE_MODEL, {"input": 0.0, "output": 0.0})
    cost = in_toks / 1_000_000 * pricing["input"] + out_toks / 1_000_000 * pricing["output"]
    return content, in_toks, out_toks, cost, duration_ms


def _call_codex_vision(
    image_path: Path, caption: str
) -> tuple[str, int, int, float, int]:
    """Run Codex CLI against a local image attachment."""
    import os
    import shutil
    import tempfile

    codex_bin = shutil.which(CODEX_CLI_CORE_BIN) or CODEX_CLI_CORE_BIN
    system_prompt = _load_vision_prompt()
    prompt = (
        f"{system_prompt}\n\n"
        f"Optional caption from the user: {caption.strip() or '(none)'}\n\n"
        "Analyze the attached image and respond with the JSON schema described above."
    )
    input_tokens_estimate = max(1, len(prompt) // 4)

    out_handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8",
    )
    out_path = out_handle.name
    out_handle.close()

    argv = [
        codex_bin, "exec",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "-i", str(image_path),
        "-o", out_path,
    ]

    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NO_WINDOW

    start = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=CODEX_CLI_CORE_TIMEOUT_SECS,
            creationflags=creation_flags,
        )
        duration_ms = int((time.perf_counter() - start) * 1000)
        try:
            raw = Path(out_path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"codex vision output file missing: {exc}") from exc

        if _looks_like_codex_credit_limit(proc.stderr or "", raw):
            raise RuntimeError(f"codex vision hit credit/usage limit: {(proc.stderr or raw)[:300]}")
        if proc.returncode != 0:
            raise RuntimeError(
                f"codex vision exit={proc.returncode}: {(proc.stderr or '').strip()[:500]}"
            )
        if not raw:
            raise RuntimeError("codex vision produced empty output")

        output_tokens_estimate = max(1, len(raw) // 4)
        return raw, input_tokens_estimate, output_tokens_estimate, 0.0, duration_ms
    finally:
        try:
            Path(out_path).unlink()
        except OSError:
            pass


def _stub_extraction(filename: str) -> ImageExtraction:
    """Last-resort extraction when neither backend is configured."""
    return ImageExtraction(
        description=f"Image uploaded: {filename}. No vision backend configured.",
        extracted_text="",
        ticker_mentions=[],
        suspected_topic=filename,
        user_intent="unknown",
        backend="stub",
        cost_usd=0.0,
        duration_ms=0,
    )


def _parse_response(raw: str, *, backend: str) -> dict[str, str | list[str]]:
    """Best-effort parse the LLM's JSON; tolerate stray prose."""
    try:
        return parse_llm_json(raw)  # type: ignore[no-any-return]
    except Exception:
        # Some vision models fence the JSON or wrap it in prose. Try one last
        # regex pull for the outermost {...} block.
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))  # type: ignore[no-any-return]
            except json.JSONDecodeError:
                pass
        logger.warning("vision[%s] could not parse JSON; raw=%r", backend, raw[:300])
        return {}


def extract_image_info(
    image_path: Path | str, conn: sqlite3.Connection, *, caption: str = ""
) -> ImageExtraction:
    """Read an uploaded image and return a structured extraction.

    Tries Codex CLI image input first, then Anthropic Claude vision when
    configured, otherwise returns a stub. Never calls MiniMax. Never raises on
    backend failure -- callers always get a usable extraction.
    """
    image_path = Path(image_path)
    settings = get_settings()
    filename = image_path.name

    # Validate file and size once. Codex accepts the file path directly; Anthropic
    # needs base64 if used as fallback.
    try:
        image_b64, mime = _read_and_encode(image_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("vision: cannot read image %s: %s", filename, exc)
        return _stub_extraction(filename)

    raw = ""
    backend = ""
    in_toks = out_toks = 0
    cost_usd = 0.0
    duration_ms = 0
    try:
        raw, in_toks, out_toks, cost_usd, duration_ms = _call_codex_vision(
            image_path, caption
        )
        backend = "codex_cli"
    except Exception:
        logger.exception("vision: codex_cli backend failed")

    if not raw and settings.anthropic_api_key:
        try:
            raw, in_toks, out_toks, cost_usd, duration_ms = _call_anthropic_vision(
                image_b64, mime, caption
            )
            backend = "anthropic"
        except Exception:
            logger.exception("vision: anthropic backend failed; falling back to stub")
            return _stub_extraction(filename)

    if not raw:
        return _stub_extraction(filename)

    # Log the call for cost auditing.
    model_name = CODEX_CLI_CORE_MODEL_NAME if backend == "codex_cli" else VISION_CLAUDE_MODEL
    try:
        _log_call(
            conn,
            backend=backend,
            model=model_name,
            input_tokens=in_toks,
            output_tokens=out_toks,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            caller="vision.extract_image_info",
        )
    except Exception:
        logger.exception("vision: failed to log llm_calls row (non-fatal)")

    parsed = _parse_response(raw, backend=backend)
    description = str(parsed.get("description", "") or "").strip()[:1000]
    extracted_text = str(parsed.get("extracted_text", "") or "").strip()[:4000]
    suspected_topic = str(parsed.get("suspected_topic", "") or "").strip()[:200]

    # Take both the LLM-extracted tickers and a regex pass over the raw text --
    # the model is the primary source but the regex catches things it missed.
    llm_tickers = parsed.get("ticker_mentions", []) or []
    if not isinstance(llm_tickers, list):
        llm_tickers = []
    regex_tickers = _TICKER_RE.findall(extracted_text)
    ticker_mentions = _filter_tickers(
        [str(t) for t in llm_tickers] + list(regex_tickers)
    )

    return ImageExtraction(
        description=description or f"Image uploaded: {filename}",
        extracted_text=extracted_text,
        ticker_mentions=ticker_mentions,
        suspected_topic=suspected_topic or filename,
        user_intent=_coerce_intent(str(parsed.get("user_intent", ""))),
        backend=backend,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
    )


def format_extraction_as_feedback(
    extraction: ImageExtraction, *, image_filename: str, caption: str = ""
) -> str:
    """Render an extraction as the body of a feedback entry that the F13 pipeline can read.

    The output mimics what the boss would have typed if they'd transcribed the
    image themselves. F13's intent classifier + reply generator consume it the
    same way they consume a /channel/api/reply text message.
    """
    parts: list[str] = []
    if caption.strip():
        parts.append(f"[caption] {caption.strip()}")
    parts.append(f"[image] {image_filename}")
    parts.append(f"[summary] {extraction.description}")
    if extraction.suspected_topic:
        parts.append(f"[topic] {extraction.suspected_topic}")
    if extraction.ticker_mentions:
        parts.append(f"[tickers] {', '.join(extraction.ticker_mentions)}")
    if extraction.extracted_text:
        # Cap quoted text so a long screenshot doesn't blow the conversation log
        snippet = extraction.extracted_text[:1200]
        parts.append(f"[ocr] {snippet}")
    return "\n".join(parts)
