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
}


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
