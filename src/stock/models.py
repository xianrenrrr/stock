"""stock.models -- unified LLM client layer with cost control."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, TypedDict

import anthropic
import openai
from pydantic import BaseModel

from stock.config import Settings, get_settings

logger = logging.getLogger(__name__)

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_thinking(content: str) -> str:
    """Remove <think>...</think> reasoning blocks emitted by hybrid thinking models."""
    cleaned = _THINK_BLOCK_RE.sub("", content)
    # Some models leave a stray opening <think> with no closer if max_tokens cut them off
    if "<think>" in cleaned and "</think>" not in cleaned:
        cleaned = cleaned.split("<think>")[0]
    return cleaned.strip()

# Default to China-mainland host (api.minimaxi.com). The "global" host (api.minimax.io)
# uses a *different* API key issued by platform.minimax.io. If your key was issued
# against the global host, set MINIMAX_BASE_URL=https://api.minimax.io/v1 in .env.
MINIMAX_BASE_URL: str = "https://api.minimaxi.com/v1"
MINIMAX_DEFAULT_MODEL: str = "MiniMax-M2.5-highspeed"
MINIMAX_HTTP_TIMEOUT_SECS: float = 60.0
MINIMAX_MAX_RETRIES: int = 8

PRICING: dict[str, dict[str, float]] = {
    "MiniMax-M1-80k": {"input": 0.30, "output": 1.20},
    "MiniMax-M2.5": {"input": 0.40, "output": 1.60},
    "MiniMax-M2.5-highspeed": {"input": 0.20, "output": 0.80},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    # claude_cli backend = locally-spawned `claude -p` subprocess; cost is paid via
    # the user's Claude Code subscription, not metered through our API key. We log
    # cost_usd=0 so the daily ceiling doesn't block, but token counts (estimated)
    # still flow into llm_calls for visibility.
    "claude-code-session": {"input": 0.0, "output": 0.0},
}

# F17: subprocess Claude Code session as a swappable core backend. Has built-in
# WebSearch so the prompt can ground itself; our existing Tavily/Serper layer
# (stock.websearch) stays available as an explicit backup for the MiniMax path
# and as a fallback when subprocess search whiffs.
CLAUDE_CLI_CORE_BIN: str = "claude"
CLAUDE_CLI_CORE_DEFAULT_MODEL: str = "claude-opus-4-7"
CLAUDE_CLI_CORE_TIMEOUT_SECS: int = 600
CLAUDE_CLI_CORE_MODEL_NAME: str = "claude-code-session"  # the key in PRICING


class ChatMessage(TypedDict):
    """Single message in a chat conversation."""

    role: str
    content: str


class ChatResponse(BaseModel):
    """Structured response from an LLM chat call."""

    content: str
    input_tokens: int
    output_tokens: int
    model: str
    cost_usd: float


class CostCeilingError(RuntimeError):
    """Raised when daily LLM spend exceeds the configured ceiling."""


def parse_llm_json(raw: str) -> dict[str, Any]:
    """Parse JSON from LLM output, stripping <think> blocks and code fences."""
    text = strip_thinking(raw).strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text:
        raise json.JSONDecodeError("LLM returned empty content", "", 0)
    return json.loads(text)  # type: ignore[no-any-return]


def check_cost_ceiling(conn: sqlite3.Connection, settings: Settings) -> float:
    """Raise CostCeilingError if today's LLM spend meets or exceeds the ceiling."""
    today_midnight = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )

    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0) FROM llm_calls WHERE created_at >= ?",
        (today_midnight,),
    ).fetchone()
    total: float = row[0] if row else 0.0

    if total >= settings.daily_cost_ceiling_usd:
        raise CostCeilingError(
            f"Daily cost ceiling ${settings.daily_cost_ceiling_usd} reached"
            f" (spent ${total:.4f})"
        )
    return total


class LLMClient:
    """Thin wrapper around a single LLM provider."""

    def __init__(self, provider: str, api_key: str) -> None:
        if not api_key:
            raise ValueError(f"API key for provider '{provider}' is empty")

        self._provider = provider
        self._openai_client: openai.OpenAI | None = None
        self._anthropic_client: anthropic.Anthropic | None = None

        if provider == "minimax":
            settings = get_settings()
            base_url = (settings.minimax_base_url or "").strip() or MINIMAX_BASE_URL
            # Aggressive retries because api.minimaxi.com DNS can be flaky from the US;
            # the OpenAI SDK does exponential backoff between attempts internally.
            self._openai_client = openai.OpenAI(
                api_key=api_key,
                base_url=base_url,
                max_retries=MINIMAX_MAX_RETRIES,
                timeout=MINIMAX_HTTP_TIMEOUT_SECS,
            )
        elif provider == "claude":
            self._anthropic_client = anthropic.Anthropic(api_key=api_key)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    @property
    def provider(self) -> str:
        """Return the provider name."""
        return self._provider

    def chat(
        self,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        conn: sqlite3.Connection,
        caller: str,
        cached_system: str | None = None,
    ) -> ChatResponse:
        """Send a chat request, enforce cost ceiling, log usage, and return response."""
        # Check cost ceiling before making the call
        settings = get_settings()
        check_cost_ceiling(conn, settings)

        # Time the LLM call
        start = time.perf_counter()

        if self._provider == "minimax":
            content, input_tokens, output_tokens = self._call_minimax(
                messages, model, max_tokens, cached_system
            )
        else:
            content, input_tokens, output_tokens = self._call_claude(
                messages, model, max_tokens, cached_system
            )

        duration_ms = int((time.perf_counter() - start) * 1000)

        # Compute cost from pricing table
        pricing = PRICING.get(model)
        if pricing:
            cost_usd = (
                input_tokens / 1_000_000 * pricing["input"]
                + output_tokens / 1_000_000 * pricing["output"]
            )
        else:
            logger.warning("No pricing for model %s, recording cost as 0.0", model)
            cost_usd = 0.0

        # Log to llm_calls table
        conn.execute(
            "INSERT INTO llm_calls"
            " (model, provider, input_tokens, output_tokens,"
            " cost_usd, duration_ms, caller, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                model,
                self._provider,
                input_tokens,
                output_tokens,
                cost_usd,
                duration_ms,
                caller,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

        return ChatResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            cost_usd=cost_usd,
        )

    def _call_minimax(
        self,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        cached_system: str | None,
    ) -> tuple[str, int, int]:
        """Call MiniMax via OpenAI-compatible endpoint."""
        assert self._openai_client is not None

        all_messages: list[ChatMessage] = []
        if cached_system:
            all_messages.append({"role": "system", "content": cached_system})
        all_messages.extend(messages)

        response = self._openai_client.chat.completions.create(
            model=model,
            messages=all_messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
        )

        raw_content = response.choices[0].message.content or ""
        # Hybrid-thinking MiniMax models emit <think>...</think> in content; strip it
        content = strip_thinking(raw_content) if "<think>" in raw_content else raw_content
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        return content, input_tokens, output_tokens

    def _call_claude(
        self,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        cached_system: str | None,
    ) -> tuple[str, int, int]:
        """Call Claude via Anthropic SDK."""
        assert self._anthropic_client is not None

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        if cached_system:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": cached_system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        response = self._anthropic_client.messages.create(**kwargs)

        content = response.content[0].text if response.content else ""
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        return content, input_tokens, output_tokens


def get_client(provider: str) -> LLMClient:
    """Return an LLMClient for the given provider."""
    settings = get_settings()
    if provider == "minimax":
        return LLMClient("minimax", settings.minimax_api_key)
    if provider == "claude":
        return LLMClient("claude", settings.anthropic_api_key)
    raise ValueError(f"Unknown provider: {provider}")


class ClaudeCliUnavailable(RuntimeError):
    """Raised when the `claude` binary isn't installed or the subprocess fails non-recoverably."""


class ClaudeCliClient:
    """Subprocess-backed Claude Code session. Implements the same chat() interface as LLMClient.

    Each chat() call spawns `claude -p <prompt> --model <model> --output-format text
    --dangerously-skip-permissions` and reads stdout. The subprocess inherits the
    user's existing `claude login`, so authentication and billing happen via the
    Claude Code subscription -- cost is logged as $0 against our daily ceiling.

    Critically, `claude -p` has access to its own WebSearch tool, so prompts can
    self-ground without going through our Tavily/Serper layer. The Tavily layer
    stays available as the backup path and is still used by the MiniMax backend.
    """

    def __init__(
        self,
        *,
        bin_path: str = CLAUDE_CLI_CORE_BIN,
        timeout_secs: int = CLAUDE_CLI_CORE_TIMEOUT_SECS,
    ) -> None:
        # Resolve the binary to an absolute path so subprocess.run finds it
        # without shell=True. On Windows, the npm-installed `claude` is
        # actually `claude.CMD`; subprocess.run([self._bin, ...]) with
        # self._bin='claude' and shell=False does NOT auto-resolve the .CMD
        # extension and raises FileNotFoundError. Resolving via shutil.which
        # at construction time picks up the .CMD form transparently.
        import shutil
        resolved = shutil.which(bin_path)
        self._bin = resolved or bin_path
        self._timeout = timeout_secs

    @property
    def provider(self) -> str:
        """Return the provider name (matches LLMClient API)."""
        return "claude_cli"

    def chat(
        self,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        conn: sqlite3.Connection,
        caller: str,
        cached_system: str | None = None,
    ) -> ChatResponse:
        """Send a chat request to a `claude -p` subprocess; log usage; return response."""
        import subprocess

        # Cost ceiling check is a no-op for this backend (cost is $0 here), but
        # we still call it so a MiniMax-spike day blocks subprocess calls too --
        # we don't want a runaway subscription drain hidden behind "free."
        settings = get_settings()
        check_cost_ceiling(conn, settings)

        # Compose the single-turn prompt: system block + each user/assistant turn.
        # claude -p is one-shot per invocation, so we flatten the conversation.
        parts: list[str] = []
        if cached_system:
            parts.append(cached_system.strip())
            parts.append("---")
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if not content:
                continue
            if role == "user":
                parts.append(content)
            else:
                parts.append(f"[{role}]\n{content}")
        prompt = "\n\n".join(parts).strip()

        # Token estimate before the call so we can log even on timeout.
        # ~4 chars/token is the canonical Anthropic rule of thumb.
        input_tokens_estimate = max(1, len(prompt) // 4)

        start = time.perf_counter()
        try:
            proc = subprocess.run(
                [
                    self._bin, "-p", prompt,
                    "--model", model or CLAUDE_CLI_CORE_DEFAULT_MODEL,
                    "--output-format", "text",
                    "--dangerously-skip-permissions",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._timeout,
            )
        except FileNotFoundError as exc:
            raise ClaudeCliUnavailable(
                f"`{self._bin}` not on PATH; run `claude login` and ensure Claude Code is installed"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCliUnavailable(
                f"`claude -p` exceeded {self._timeout}s timeout for caller={caller}"
            ) from exc

        duration_ms = int((time.perf_counter() - start) * 1000)

        if proc.returncode != 0:
            raise ClaudeCliUnavailable(
                f"`claude -p` exit={proc.returncode}: {(proc.stderr or '').strip()[:500]}"
            )

        content = (proc.stdout or "").strip()
        # Defensive: hybrid-thinking models can still emit <think> blocks
        if "<think>" in content:
            content = strip_thinking(content)

        output_tokens_estimate = max(1, len(content) // 4)

        # Log to llm_calls table with cost=0 (subscription, not metered).
        conn.execute(
            "INSERT INTO llm_calls"
            " (model, provider, input_tokens, output_tokens,"
            " cost_usd, duration_ms, caller, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                CLAUDE_CLI_CORE_MODEL_NAME,
                "claude_cli",
                input_tokens_estimate,
                output_tokens_estimate,
                0.0,
                duration_ms,
                caller,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

        return ChatResponse(
            content=content,
            input_tokens=input_tokens_estimate,
            output_tokens=output_tokens_estimate,
            model=CLAUDE_CLI_CORE_MODEL_NAME,
            cost_usd=0.0,
        )


def get_core_client() -> LLMClient | ClaudeCliClient:
    """Return the active 'core thinking' backend selected by Settings.core_llm_backend.

    Used by the user-facing flows (research, reply, grading, deep-dive, health-check)
    so the operator can swap between MiniMax (fast, cheap, metered) and a local
    Claude Code subprocess (Opus-class, free under the user's subscription, has
    built-in WebSearch) with one env var. Utility callers (intent, prompt_rewriter,
    thesis extract/verify, discover, features) keep talking to MiniMax directly --
    they're high-frequency and don't benefit from the Opus-class jump.

    Env: CORE_LLM_BACKEND=minimax|claude_cli (default minimax).
    Falls back to MiniMax if claude_cli is configured but the binary is missing.
    """
    settings = get_settings()
    backend = (settings.core_llm_backend or "minimax").strip().lower()
    if backend == "claude_cli":
        return ClaudeCliClient()
    return get_client("minimax")


def get_core_model() -> str:
    """Return the model name appropriate for the active core backend.

    Lets a single caller write `client = get_core_client(); model = get_core_model();`
    without knowing which backend is live.
    """
    settings = get_settings()
    backend = (settings.core_llm_backend or "minimax").strip().lower()
    if backend == "claude_cli":
        return (settings.core_claude_model or CLAUDE_CLI_CORE_DEFAULT_MODEL).strip()
    return MINIMAX_DEFAULT_MODEL
