"""stock.intent -- classify inbound WeChat messages into question / instruction / ack."""
from __future__ import annotations

import logging
import sqlite3
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from stock.config import get_settings
from stock.models import (
    ChatMessage,
    ChatResponse,
    CostCeilingError,
    check_cost_ceiling,
    get_core_client,
    get_core_model,
    parse_llm_json,
)

logger = logging.getLogger(__name__)

INTENT_PROMPT_PATH: str = "prompts/intent_classify.txt"
INTENT_MAX_TOKENS: int = 200
VALID_INTENTS: tuple[str, ...] = ("question", "instruction", "ack", "unknown")


class IntentResult(BaseModel):
    """Structured output of the intent classifier."""

    intent: str
    confidence: float
    summary: str = ""
    suggested_topic: str | None = None


@lru_cache(maxsize=1)
def _load_intent_prompt() -> tuple[str, str]:
    """Load and split the intent classification prompt."""
    path = Path(INTENT_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Intent prompt not found at {INTENT_PROMPT_PATH}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


def _coerce_intent(raw: str) -> str:
    """Normalize an LLM-returned intent string to one of VALID_INTENTS."""
    cleaned = (raw or "").strip().lower()
    if cleaned in VALID_INTENTS:
        return cleaned
    return "unknown"


def classify(
    text: str, *, recipient: str, conn: sqlite3.Connection
) -> IntentResult:
    """Classify an inbound WeChat reply via a cheap MiniMax call.

    Failures (cost ceiling, parse errors, network) downgrade to
    `IntentResult(intent="unknown", confidence=0.0)`.
    """
    if not text or not text.strip():
        return IntentResult(intent="unknown", confidence=0.0)

    settings = get_settings()
    try:
        check_cost_ceiling(conn, settings)
    except CostCeilingError:
        logger.warning("Intent classify skipped: cost ceiling reached")
        return IntentResult(intent="unknown", confidence=0.0)

    system_template, user_template = _load_intent_prompt()
    system_prompt = system_template
    user_message = user_template.format(
        recipient=recipient,
        text=text.strip(),
    )

    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    try:
        client = get_core_client()
        response: ChatResponse = client.chat(
            messages=messages,
            model=get_core_model(),
            max_tokens=INTENT_MAX_TOKENS,
            conn=conn,
            caller="intent.classify",
            cached_system=system_prompt,
        )
    except CostCeilingError:
        return IntentResult(intent="unknown", confidence=0.0)
    except Exception:
        logger.exception("Intent classify LLM call failed")
        return IntentResult(intent="unknown", confidence=0.0)

    try:
        payload = parse_llm_json(response.content)
    except Exception as exc:
        logger.warning(
            "Intent classify: LLM returned non-JSON output (%s); raw=%r",
            exc, (response.content or "")[:200],
        )
        return IntentResult(intent="unknown", confidence=0.0)

    intent = _coerce_intent(str(payload.get("intent", "unknown")))
    confidence = float(payload.get("confidence", 0.0) or 0.0)
    confidence = max(0.0, min(1.0, confidence))
    summary = str(payload.get("summary", "") or "")
    suggested_topic = payload.get("suggested_topic")
    if suggested_topic is not None:
        suggested_topic = str(suggested_topic)
    return IntentResult(
        intent=intent,
        confidence=confidence,
        summary=summary,
        suggested_topic=suggested_topic,
    )
