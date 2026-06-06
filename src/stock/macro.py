"""stock.macro -- daily US macro/economic regime digest fed into predictions.

Per-ticker focus misses the macro driver (Fed rate path, jobs, liquidity) that
moves the WHOLE market. This generates a daily US macro snapshot via the
web-search-capable core LLM, persists it as research_reports(kind='macro'), and
exposes a compact block injected as SHARED context into every prediction and the
daily note -- so a single-name read can be overridden by the macro tide. The
macro note also flows into the knowledge base.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from stock.config import get_settings
from stock.models import check_cost_ceiling

logger = logging.getLogger(__name__)

MACRO_PROMPT_PATH: str = "prompts/macro.txt"
MACRO_MAX_TOKENS: int = 1500
MACRO_BLOCK_MAX_CHARS: int = 1500


@lru_cache(maxsize=1)
def _load_macro_prompt() -> tuple[str, str]:
    path = Path(MACRO_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Macro prompt not found at {MACRO_PROMPT_PATH}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


def generate_macro_digest(
    conn: sqlite3.Connection, *, language: str | None = None,
) -> int | None:
    """Generate + persist today's US macro snapshot. Returns the research_id."""
    # Lazy import: research imports many modules; macro is also imported widely.
    from stock.research import _core_chat, _persist_research

    settings = get_settings()
    check_cost_ceiling(conn, settings)
    lang = (language or settings.research_language or "zh").strip() or "zh"

    system_prompt, user_template = _load_macro_prompt()
    user_message = user_template.format(
        now_utc=datetime.now(timezone.utc).isoformat(timespec="minutes"),
        language=lang,
        max_chars=MACRO_BLOCK_MAX_CHARS,
    )
    response = _core_chat(
        messages=[{"role": "user", "content": user_message}],
        max_tokens=MACRO_MAX_TOKENS,
        conn=conn,
        caller="macro.digest",
        cached_system=system_prompt,
    )
    body = (response.content or "").strip()
    if not body:
        logger.warning("macro digest produced empty body")
        return None
    if "Not financial advice" not in body:
        body = body.rstrip() + "\n\nNot financial advice."
    research_id = _persist_research(
        conn, kind="macro", topic="US macro regime", layer_focus="macro",
        body=body, cost_usd=response.cost_usd,
    )
    logger.info("Macro digest generated: research_id=%s", research_id)
    return research_id


def format_macro_block(
    conn: sqlite3.Connection, *, max_chars: int = MACRO_BLOCK_MAX_CHARS, max_age_days: int = 4,
) -> str:
    """Return the latest macro snapshot for the prediction/daily prompt, or a
    placeholder if none/stale."""
    row = conn.execute(
        "SELECT body, created_at FROM research_reports"
        " WHERE kind = 'macro' AND created_at >= datetime('now', ?)"
        " ORDER BY id DESC LIMIT 1",
        (f"-{int(max_age_days)} days",),
    ).fetchone()
    if not row or not row[0]:
        return "(no recent US macro snapshot -- macro regime unknown)"
    body, created_at = row
    return f"[as of {str(created_at)[:16]} UTC]\n{str(body).strip()[:max_chars]}"
