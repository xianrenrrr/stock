"""stock.feedback_router -- categorize a boss instruction as a research deep-dive
request vs a system feature request.

Background: every boss "instruction" (per stock.intent) used to be enqueued as an
equity deep-dive (orchestrator -> action_queue -> research.generate_deep_dive). That
misroutes product/feature feedback ("can you split CN/US reports", "make notes
shorter") into the equity-research generator, which then emits a nonsensical
supply-chain note about a code change. This classifier splits instructions so a
feature request is captured as a feature request instead of a deep-dive.

Mirrors stock.intent: cheap utility-model call, JSON output, all failures degrade
to a safe default ("deep_dive") so the boss still gets a research note rather than a
silent stash -- the same fail-open bias intent.classify uses for "unknown".
"""
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
    get_utility_client,
    get_utility_model,
    parse_llm_json,
)

logger = logging.getLogger(__name__)

FEEDBACK_PROMPT_PATH: str = "prompts/feedback_categorize.txt"
FEEDBACK_MAX_TOKENS: int = 200
# "deep_dive": research/analysis request -> equity deep-dive queue (legacy default).
# "feature_request": change to the AI助手 system itself (code/product/report format).
# "other": neither (greeting, vague) -> treat as deep_dive downstream (fail-open).
VALID_CATEGORIES: tuple[str, ...] = ("deep_dive", "feature_request", "other")
# Safe default: keep the legacy behavior (treat as a research deep-dive) when the
# classifier cannot decide, so the boss never loses a genuine research ask.
DEFAULT_CATEGORY: str = "deep_dive"


class FeedbackCategory(BaseModel):
    """Structured output of the feedback categorizer."""

    category: str
    confidence: float
    summary: str = ""


@lru_cache(maxsize=1)
def _load_feedback_prompt() -> tuple[str, str]:
    """Load and split the feedback categorization prompt on the [USER] marker."""
    path = Path(FEEDBACK_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(
            f"Feedback prompt not found at {FEEDBACK_PROMPT_PATH}"
        )
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


def _coerce_category(raw: str) -> str:
    """Normalize an LLM-returned category to one of VALID_CATEGORIES."""
    cleaned = (raw or "").strip().lower()
    if cleaned in VALID_CATEGORIES:
        return cleaned
    return DEFAULT_CATEGORY


def categorize_feedback(
    text: str, *, recipient: str, conn: sqlite3.Connection
) -> FeedbackCategory:
    """Categorize a boss instruction as 'deep_dive' / 'feature_request' / 'other'.

    Failures (cost ceiling, parse errors, network) degrade to the safe default
    ``FeedbackCategory(category="deep_dive", confidence=0.0)`` so the legacy
    deep-dive path still runs and no research ask is silently dropped.
    """
    if not text or not text.strip():
        return FeedbackCategory(category=DEFAULT_CATEGORY, confidence=0.0)

    settings = get_settings()
    try:
        check_cost_ceiling(conn, settings)
    except CostCeilingError:
        logger.warning("Feedback categorize skipped: cost ceiling reached")
        return FeedbackCategory(category=DEFAULT_CATEGORY, confidence=0.0)

    system_template, user_template = _load_feedback_prompt()
    user_message = user_template.format(recipient=recipient, text=text.strip())

    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    try:
        client = get_utility_client()
        response: ChatResponse = client.chat(
            messages=messages,
            model=get_utility_model(),
            max_tokens=FEEDBACK_MAX_TOKENS,
            conn=conn,
            caller="feedback_router.categorize",
            cached_system=system_template,
        )
    except CostCeilingError:
        return FeedbackCategory(category=DEFAULT_CATEGORY, confidence=0.0)
    except Exception:
        logger.exception("Feedback categorize LLM call failed")
        return FeedbackCategory(category=DEFAULT_CATEGORY, confidence=0.0)

    try:
        payload = parse_llm_json(response.content)
    except Exception as exc:
        logger.warning(
            "Feedback categorize: LLM returned non-JSON output (%s); raw=%r",
            exc, (response.content or "")[:200],
        )
        return FeedbackCategory(category=DEFAULT_CATEGORY, confidence=0.0)

    category = _coerce_category(str(payload.get("category", DEFAULT_CATEGORY)))
    confidence = float(payload.get("confidence", 0.0) or 0.0)
    confidence = max(0.0, min(1.0, confidence))
    summary = str(payload.get("summary", "") or "")
    return FeedbackCategory(
        category=category, confidence=confidence, summary=summary
    )
