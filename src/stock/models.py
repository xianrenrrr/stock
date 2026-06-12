"""stock.models -- unified LLM client layer with cost control."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
import threading
import time
from collections import deque
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

# Legacy MiniMax constants are kept only so old DB rows/tests can still be read.
# Runtime LLM work is Codex CLI first. MiniMax must not be an automatic fallback.
MINIMAX_BASE_URL: str = "https://api.minimaxi.com/v1"
MINIMAX_DEFAULT_MODEL: str = "MiniMax-M2.5-highspeed"
MINIMAX_HTTP_TIMEOUT_SECS: float = 60.0
# Cap retries low for the legacy explicit MiniMax client.
MINIMAX_MAX_RETRIES: int = 1

PRICING: dict[str, dict[str, float]] = {
    "MiniMax-M1-80k": {"input": 0.30, "output": 1.20},
    "MiniMax-M2.5": {"input": 0.40, "output": 1.60},
    "MiniMax-M2.5-highspeed": {"input": 0.20, "output": 0.80},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    # claude_cli + codex_cli backends = locally-spawned subprocesses; cost is paid via
    # the user's Claude Code / ChatGPT subscriptions, not metered through our API
    # keys. We log cost_usd=0 so the daily ceiling doesn't block, but token counts
    # (estimated) still flow into llm_calls for visibility.
    "claude-code-session": {"input": 0.0, "output": 0.0},
    "codex-cli-session": {"input": 0.0, "output": 0.0},
}

# F17: subprocess Claude Code session as a swappable core backend. Has built-in
# WebSearch so the prompt can ground itself; our existing Tavily/Serper layer
# stays available for autonomous discovery.
CLAUDE_CLI_CORE_BIN: str = "claude"
# Boss directive 2026-06-11: Claude (Fable 5) over codex everywhere. This is
# the fallback when CORE_CLAUDE_MODEL is unset and the model used by the
# codex->claude fallback paths. Operator override lives in .env.
CLAUDE_CLI_CORE_DEFAULT_MODEL: str = "claude-fable-5"
CLAUDE_CLI_CORE_TIMEOUT_SECS: int = 600
CLAUDE_CLI_CORE_MODEL_NAME: str = "claude-code-session"  # the key in PRICING

# F17b: subprocess Codex CLI session as the new default core backend. ChatGPT-
# logged-in user pays via their subscription; we log cost=0. When this fails
# (timeout / missing binary / non-zero exit) we fall back to the Claude CLI
# subprocess transparently via CodexWithClaudeFallback below.
CODEX_CLI_CORE_BIN: str = "codex"
CODEX_CLI_CORE_DEFAULT_MODEL: str = ""  # blank = let codex pick its default
CODEX_CLI_CORE_TIMEOUT_SECS: int = 600
CODEX_CLI_CORE_MODEL_NAME: str = "codex-cli-session"  # the key in PRICING

# F17c: credit/usage-limit detection + circuit breaker. When codex hits a
# ChatGPT-plan quota it may EITHER exit non-zero with a limit message in
# stderr (already caught) OR exit 0 and emit a "rate-limited" apology into
# the response file (would pass through silently otherwise). We scan both
# channels for known signatures, record a hit, and after a small threshold
# in a short window we open the circuit -- routing every subsequent core
# call straight to claude_cli for a cooldown period rather than hammering
# a known-capped backend (e.g. 26 watchlist predictions back-to-back).
#
# Patterns are conservative: clearly part of an error/refusal message, not
# generic content. Tighten if false positives appear in production.
_CODEX_CREDIT_LIMIT_RE = re.compile(
    r"rate[\s_-]?limit"
    r"|quota[ ]?exceeded"
    r"|usage[ ]?limit"
    r"|credit[ ]?limit"
    r"|plan[ ]?(limit|quota)"
    r"|weekly[ ]?limit"
    r"|HTTP[ ]?429"
    r"|too[ ]many[ ]requests"
    r"|exceeded[ ]your"
    r"|reached[ ]your"               # "you've reached your ... limit"
    r"|out[ ]of[ ](credit|quota|token)"  # "out of credits/quota/tokens"
    r"|run[ ]out[ ]of"               # "you've run out of ..."
    r"|insufficient[ ](credit|quota|balance)",
    re.IGNORECASE,
)

CODEX_CIRCUIT_HITS_THRESHOLD: int = 2          # this many hits ...
CODEX_CIRCUIT_WINDOW_SECS: float = 300.0       # ... within this window ...
CODEX_CIRCUIT_COOLDOWN_SECS: float = 1800.0    # ... opens the breaker for this long

_codex_circuit_lock = threading.Lock()
_codex_circuit_hits: deque[float] = deque(maxlen=CODEX_CIRCUIT_HITS_THRESHOLD * 4)
_codex_circuit_open_until: float = 0.0  # epoch seconds when circuit re-arms

_REASONING_EFFORT_VALUES: set[str] = {"low", "medium", "high", "xhigh", "max"}


def _clean_reasoning_effort(value: str, *, default: str) -> str:
    """Normalize CLI effort settings, falling back instead of crashing jobs."""
    effort = (value or "").strip().lower()
    if effort in _REASONING_EFFORT_VALUES:
        return effort
    fallback = default if default in _REASONING_EFFORT_VALUES else "high"
    if effort:
        logger.warning("invalid reasoning effort %r; using %s", value, fallback)
    return fallback


def _reasoning_effort_for_caller(caller: str, settings: Settings) -> str:
    """Use max/xhigh only for prediction work; keep general calls cheaper."""
    base = _clean_reasoning_effort(
        getattr(settings, "core_reasoning_effort", "high"), default="high",
    )
    prediction = _clean_reasoning_effort(
        getattr(settings, "prediction_reasoning_effort", "max"), default="max",
    )
    normalized = (caller or "").lower()
    if normalized.startswith("predict.") or ".predict." in normalized:
        return prediction
    return base


def _record_codex_credit_hit() -> None:
    """Record a credit-limit hit; open the breaker if threshold reached within window."""
    global _codex_circuit_open_until
    now = time.time()
    with _codex_circuit_lock:
        _codex_circuit_hits.append(now)
        # Drop entries outside the window so old hits don't keep triggering opens
        cutoff = now - CODEX_CIRCUIT_WINDOW_SECS
        while _codex_circuit_hits and _codex_circuit_hits[0] < cutoff:
            _codex_circuit_hits.popleft()
        if (
            len(_codex_circuit_hits) >= CODEX_CIRCUIT_HITS_THRESHOLD
            and now >= _codex_circuit_open_until
        ):
            _codex_circuit_open_until = now + CODEX_CIRCUIT_COOLDOWN_SECS
            logger.warning(
                "codex credit-limit breaker OPEN until %s -- routing core calls"
                " to claude_cli for the next %d minutes",
                datetime.fromtimestamp(
                    _codex_circuit_open_until, tz=timezone.utc,
                ).isoformat(),
                int(CODEX_CIRCUIT_COOLDOWN_SECS / 60),
            )


def _is_codex_circuit_open() -> bool:
    """Return True if the codex circuit is currently open (skip codex entirely)."""
    with _codex_circuit_lock:
        return time.time() < _codex_circuit_open_until


def _codex_circuit_reset() -> None:
    """Manually clear circuit state. Used by tests; can also be exposed via CLI later."""
    global _codex_circuit_open_until
    with _codex_circuit_lock:
        _codex_circuit_hits.clear()
        _codex_circuit_open_until = 0.0


def _looks_like_codex_credit_limit(*chunks: str) -> bool:
    """Return True if any of `chunks` matches a known credit/limit signature."""
    for chunk in chunks:
        if chunk and _CODEX_CREDIT_LIMIT_RE.search(chunk):
            return True
    return False


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
            raise RuntimeError(
                "MiniMax provider is retired. Route LLM calls through get_core_client()."
            )
        if provider == "claude":
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
        raise RuntimeError(
            "MiniMax runtime client is retired. Route LLM calls through "
            "get_core_client() so they use Codex CLI."
        )
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
    self-ground without going through our Tavily/Serper layer.
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
        # we still call it so a runaway subprocess loop is visible to ops.
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

        # Pipe the prompt via stdin instead of argv. Windows CreateProcess has
        # a 32 KB total command-line limit; the daily research prompt with all
        # its context blocks (watchlist + news + supply chain + thesis +
        # discovery + holdings) easily exceeds that and the call would silently
        # fail. `claude -p` reads from stdin when
        # the positional prompt arg is omitted.
        start = time.perf_counter()
        # Windows: pass CREATE_NO_WINDOW so subprocess.run doesn't flash a
        # cmd.exe / claude.exe console window for every call. The processes
        # still run, just hidden. Boss observed flashing during high-frequency
        # ingest cycles; this kills the visible noise without changing behavior.
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW
        effort = _reasoning_effort_for_caller(caller, settings)

        try:
            proc = subprocess.run(
                [
                    self._bin, "-p",
                    "--model", model or CLAUDE_CLI_CORE_DEFAULT_MODEL,
                    "--effort", effort,
                    "--output-format", "text",
                    "--dangerously-skip-permissions",
                ],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._timeout,
                creationflags=creation_flags,
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

        # Plan I, claude-first: detect subscription usage-limit exhaustion the
        # same way F17c does for codex. Claude Code prints a short apology
        # ("You've reached your usage limit ...") either on stderr with a
        # non-zero exit OR as a short stdout body with exit 0. Persist the
        # event so retry_quota_leftovers re-runs the killed job after the ~5h
        # window refreshes. Long stdout is real model output and is never
        # scanned -- a research note may legitimately contain "rate limit".
        stdout_text = (proc.stdout or "").strip()
        short_stdout = stdout_text if len(stdout_text) < 500 else ""
        if _looks_like_codex_credit_limit(proc.stderr or "", short_stdout):
            detail = ((proc.stderr or "").strip() or stdout_text)[:300]
            try:
                from stock.quota import record_usage_limit_event

                record_usage_limit_event(conn, "claude_cli", caller, detail=detail)
            except Exception:
                logger.exception("usage-limit event persist failed (non-fatal)")
            raise ClaudeCliUnavailable(
                f"claude hit usage limit for caller={caller}: {detail}"
            )

        if proc.returncode != 0:
            raise ClaudeCliUnavailable(
                f"`claude -p` exit={proc.returncode}: {(proc.stderr or '').strip()[:500]}"
            )

        content = stdout_text
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


class CodexCliUnavailable(RuntimeError):
    """Raised when the `codex` binary isn't installed or the subprocess fails non-recoverably."""


class CodexCliClient:
    """Subprocess-backed Codex CLI session. Same chat() shape as ClaudeCliClient.

    Each chat() call spawns `codex exec --skip-git-repo-check
    --dangerously-bypass-approvals-and-sandbox [-m model] -o <tmpfile>` with the
    prompt piped through stdin. The final-assistant message is read back from
    the `-o` file rather than parsed out of stdout -- codex stdout interleaves
    a header, the echoed prompt, and a token-usage footer alongside the
    response, so the dedicated `-o` channel is the only reliable extraction.

    Subprocess inherits the user's `codex login` (ChatGPT plan), so cost is
    logged as $0 against our daily ceiling -- same accounting model as
    ClaudeCliClient.
    """

    def __init__(
        self,
        *,
        bin_path: str = CODEX_CLI_CORE_BIN,
        timeout_secs: int = CODEX_CLI_CORE_TIMEOUT_SECS,
    ) -> None:
        # Resolve absolute path so subprocess.run finds codex.cmd on Windows
        # without shell=True (same .CMD trap as claude).
        import shutil
        resolved = shutil.which(bin_path)
        self._bin = resolved or bin_path
        self._timeout = timeout_secs

    @property
    def provider(self) -> str:
        """Return the provider name (matches LLMClient API)."""
        return "codex_cli"

    def chat(
        self,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        conn: sqlite3.Connection,
        caller: str,
        cached_system: str | None = None,
    ) -> ChatResponse:
        """Send a chat request to a `codex exec` subprocess; log usage; return response."""
        import os
        import subprocess
        import tempfile

        settings = get_settings()
        check_cost_ceiling(conn, settings)

        # Flatten the conversation the same way ClaudeCliClient does. codex exec
        # is one-shot and doesn't carry a /system slot, so we prepend the cached
        # system block as a delimited preamble.
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

        input_tokens_estimate = max(1, len(prompt) // 4)

        # Allocate a temp file for codex's final-message output. We use
        # delete=False because codex writes after we close our handle; we
        # remove it ourselves in the finally block.
        out_handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8",
        )
        out_path = out_handle.name
        out_handle.close()

        argv: list[str] = [
            self._bin, "exec",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            "-c",
            (
                "model_reasoning_effort="
                f"\"{_reasoning_effort_for_caller(caller, settings)}\""
            ),
            "-o", out_path,
        ]
        # Only pass -m if caller specified one; otherwise let codex pick its
        # configured default (currently gpt-5.5 on this machine).
        if model:
            argv.extend(["-m", model])

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW

        start = time.perf_counter()
        try:
            try:
                proc = subprocess.run(
                    argv,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self._timeout,
                    creationflags=creation_flags,
                )
            except FileNotFoundError as exc:
                raise CodexCliUnavailable(
                    f"`{self._bin}` not on PATH; install Codex CLI and run `codex login`"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise CodexCliUnavailable(
                    f"`codex exec` exceeded {self._timeout}s timeout for caller={caller}"
                ) from exc

            duration_ms = int((time.perf_counter() - start) * 1000)

            # Read out-file early -- both exit paths (success / non-zero) may
            # need to inspect it for the credit-limit signature.
            try:
                with open(out_path, encoding="utf-8") as f:
                    content = f.read().strip()
            except OSError as exc:
                raise CodexCliUnavailable(
                    f"`codex exec` finished but output file missing: {exc}"
                ) from exc

            if "<think>" in content:
                content = strip_thinking(content)

            # Credit/usage limit detection. Codex may EITHER exit non-zero with
            # the limit message in stderr, OR exit 0 with a "rate-limited"
            # apology in the response file. Treat both as CodexCliUnavailable
            # so the fallback wrapper drops to claude_cli, and record the hit
            # against the circuit breaker so we stop hammering a capped
            # backend across a 26-ticker fan-out.
            if _looks_like_codex_credit_limit(proc.stderr or "", content):
                _record_codex_credit_hit()
                # Plan I: persist the exhaustion so the orchestrator's
                # retry_quota_leftovers job can re-run the killed work after
                # the ~5h subscription window refreshes.
                try:
                    from stock.quota import record_usage_limit_event

                    record_usage_limit_event(
                        conn, "codex_cli", caller,
                        detail=((proc.stderr or "") or content)[:300].strip(),
                    )
                except Exception:
                    logger.exception("usage-limit event persist failed (non-fatal)")
                raise CodexCliUnavailable(
                    f"codex hit credit/usage limit for caller={caller}: "
                    f"{((proc.stderr or '') or content)[:300].strip()}"
                )

            if proc.returncode != 0:
                raise CodexCliUnavailable(
                    f"`codex exec` exit={proc.returncode}: {(proc.stderr or '').strip()[:500]}"
                )

            if not content:
                raise CodexCliUnavailable(
                    f"`codex exec` produced empty output for caller={caller}"
                )

            output_tokens_estimate = max(1, len(content) // 4)

            conn.execute(
                "INSERT INTO llm_calls"
                " (model, provider, input_tokens, output_tokens,"
                " cost_usd, duration_ms, caller, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    CODEX_CLI_CORE_MODEL_NAME,
                    "codex_cli",
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
                model=CODEX_CLI_CORE_MODEL_NAME,
                cost_usd=0.0,
            )
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass


class CodexWithClaudeFallback:
    """Try codex_cli first; on CodexCliUnavailable, fall back to claude_cli.

    This is what `get_core_client()` returns when core_llm_backend == "codex_cli"
    (the default). If both subprocess backends fail, the error propagates; we do
    not silently fall back to MiniMax.
    """

    def __init__(self) -> None:
        self._codex = CodexCliClient()
        self._claude = ClaudeCliClient()

    @property
    def provider(self) -> str:
        """Return the primary provider name; callers log this for visibility."""
        return "codex_cli"

    def chat(
        self,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        conn: sqlite3.Connection,
        caller: str,
        cached_system: str | None = None,
    ) -> ChatResponse:
        """Try codex; on failure log + fall back to claude_cli.

        The incoming `model` argument comes from `get_core_model()`, which for
        codex_cli backend returns "" (let codex pick) or whatever
        CORE_CODEX_MODEL was set to. That value is not a valid Claude model id,
        so on fallback we ignore it and use the Claude default explicitly.

        Circuit-breaker behavior: once enough credit-limit hits have accrued in
        a short window, we route every call directly to claude_cli for the
        cooldown period without touching codex at all. Avoids burning 26
        watchlist predictions each banging on a known-capped backend before
        falling back individually.
        """
        # Short-circuit when the breaker is open: skip codex, log distinctly
        if _is_codex_circuit_open():
            logger.info(
                "codex circuit open -- routing %s directly to claude_cli", caller,
            )
            return self._claude.chat(
                messages=messages,
                model=CLAUDE_CLI_CORE_DEFAULT_MODEL,
                max_tokens=max_tokens,
                conn=conn,
                caller=f"{caller}.codex_circuit_open_claude",
                cached_system=cached_system,
            )

        try:
            return self._codex.chat(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                conn=conn,
                caller=caller,
                cached_system=cached_system,
            )
        except CodexCliUnavailable as exc:
            logger.warning(
                "codex_cli unavailable (%s); falling back to claude_cli for caller=%s",
                exc, caller,
            )
            return self._claude.chat(
                messages=messages,
                model=CLAUDE_CLI_CORE_DEFAULT_MODEL,
                max_tokens=max_tokens,
                conn=conn,
                caller=f"{caller}.codex_fallback_claude",
                cached_system=cached_system,
            )


def get_core_client() -> LLMClient | ClaudeCliClient | CodexCliClient | CodexWithClaudeFallback:
    """Return the active backend selected by Settings.core_llm_backend.

    All LLM-touching modules route through this helper -- core flows
    (research, reply, grading, deep-dive, qa-dive) AND utility flows
    (features, intent, thesis, discover, events, self_review).

    Backend values:
      "codex_cli"  (default): codex exec via ChatGPT login, with claude_cli
                              as an automatic fallback on timeout / missing
                              binary / non-zero exit. Free under the user's
                              ChatGPT + Claude Code subscriptions.
      "claude_cli"          : pure Claude Code CLI (no codex layer).
      "minimax"             : legacy value; ignored and routed to codex_cli.
      anything else         : routed to codex_cli.

    A both-subprocess-failed scenario propagates `ClaudeCliUnavailable` to the
    caller; MiniMax is not used as a safety net.
    """
    settings = get_settings()
    backend = (settings.core_llm_backend or "codex_cli").strip().lower()
    if backend == "codex_cli":
        return CodexWithClaudeFallback()
    if backend == "claude_cli":
        return ClaudeCliClient()
    if backend == "minimax":
        logger.warning("CORE_LLM_BACKEND=minimax is legacy; using codex_cli")
        return CodexWithClaudeFallback()
    logger.warning("Unknown CORE_LLM_BACKEND=%s; using codex_cli", backend)
    return CodexWithClaudeFallback()


def get_core_model() -> str:
    """Return the model name appropriate for the active core backend.

    Lets a single caller write `client = get_core_client(); model = get_core_model();`
    without knowing which backend is live.
    """
    settings = get_settings()
    backend = (settings.core_llm_backend or "codex_cli").strip().lower()
    if backend == "codex_cli":
        # Blank -> CodexCliClient honors codex's own default. Callers that
        # really need a specific model can set CORE_CODEX_MODEL in .env.
        return (getattr(settings, "core_codex_model", "") or CODEX_CLI_CORE_DEFAULT_MODEL).strip()
    if backend == "claude_cli":
        return (settings.core_claude_model or CLAUDE_CLI_CORE_DEFAULT_MODEL).strip()
    return (getattr(settings, "core_codex_model", "") or CODEX_CLI_CORE_DEFAULT_MODEL).strip()


# Fast lane for high-frequency utility classifiers (feature extraction, intent
# classification). gpt-5.5 reasoning is overkill for cheap JSON tasks and the
# per-news / per-reply fan-out paid 20-50s of codex latency each. These route to
# a fast Claude haiku model via claude_cli, which is also the most reliable
# backend (it's the fallback for everything), so no extra fallback layer needed.
FAST_UTILITY_CLAUDE_MODEL: str = "claude-haiku-4-5-20251001"


class FastUtilityClient:
    """Fast Claude haiku for cheap high-frequency classifiers, with the core
    backend (codex -> claude) as a backstop.

    The primary is `claude -p` on a fast model. If that subprocess fails
    (ClaudeCliUnavailable: missing binary / timeout / non-zero exit), we fall
    back to the full core backend so a utility call is NEVER left without a
    safety net -- the same "claude is always behind it" guarantee the core
    path has, applied to the fast lane.
    """

    def __init__(self) -> None:
        self._fast = ClaudeCliClient()

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
        """Try fast haiku; on failure fall back to the core backend."""
        try:
            return self._fast.chat(
                messages=messages, model=model, max_tokens=max_tokens,
                conn=conn, caller=caller, cached_system=cached_system,
            )
        except ClaudeCliUnavailable as exc:
            logger.warning(
                "utility claude_cli unavailable (%s); falling back to core backend"
                " for caller=%s", exc, caller,
            )
            core = get_core_client()
            return core.chat(
                messages=messages, model=get_core_model(), max_tokens=max_tokens,
                conn=conn, caller=f"{caller}.utility_fallback_core",
                cached_system=cached_system,
            )


def get_utility_client() -> FastUtilityClient | CodexWithClaudeFallback | ClaudeCliClient:
    """Return a fast, low-latency client for high-frequency utility classifiers.

    Defaults to a fast claude_cli (haiku) lane WITH the core backend as a
    backstop. If `utility_claude_model` is set blank, fall back to the active
    core backend so the switch is reversible.
    """
    settings = get_settings()
    if (getattr(settings, "utility_claude_model", "") or "").strip():
        return FastUtilityClient()
    return get_core_client()


def get_utility_model() -> str:
    """Return the model id for the utility fast lane (haiku by default)."""
    settings = get_settings()
    configured = (getattr(settings, "utility_claude_model", "") or "").strip()
    if configured:
        return configured
    return get_core_model()
