"""stock.prompt_rewriter -- Opus-driven editing of prompts/research.txt + data/rules/current.md."""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from stock.config import get_settings
from stock.models import (
    ChatMessage,
    ChatResponse,
    CostCeilingError,
    check_cost_ceiling,
    get_client,
)

logger = logging.getLogger(__name__)

REWRITE_PROMPT_PATH: str = "prompts/rewrite_prompt.txt"
REWRITE_MAX_TOKENS: int = 1500
OPUS_BUDGET_THRESHOLD: float = 1.0
OPUS_MODEL: str = "claude-opus-4-7"
MINIMAX_FALLBACK_MODEL: str = "MiniMax-M1-80k"
ALLOWED_TARGETS: tuple[str, ...] = (
    "prompts/research.txt",
    "data/rules/current.md",
    "prompts/intent_classify.txt",
    "prompts/reply.txt",
)
RATE_LIMIT_HOURS: int = 24
DIFF_SIZE_BUFFER: int = 2000


class RewriteProposal(BaseModel):
    """One staged rewrite proposed by the Opus editor."""

    target_path: str
    before_text: str
    after_text: str
    rationale: str
    cost_usd: float = 0.0
    triggered_by_conversation_id: int | None = None
    low_confidence: bool = False


@lru_cache(maxsize=1)
def _load_rewrite_prompt() -> tuple[str, str]:
    """Load and split the rewrite_prompt template."""
    path = Path(REWRITE_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Rewrite prompt not found at {REWRITE_PROMPT_PATH}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


def _read_file_or_default(path: str, default: str = "") -> str:
    """Read a file's content, returning default when missing."""
    p = Path(path)
    if not p.exists():
        return default
    return p.read_text(encoding="utf-8")


def _gather_instruction_excerpt(
    conn: sqlite3.Connection, conversation_ids: list[int]
) -> tuple[str, str]:
    """Build (instruction_summary, conversation_excerpt) from given turn IDs."""
    if not conversation_ids:
        return "(none)", "(none)"

    placeholders = ",".join("?" * len(conversation_ids))
    rows = conn.execute(
        f"SELECT id, run_id, recipient, direction, body, intent, created_at"
        f" FROM conversations WHERE id IN ({placeholders})"
        f" ORDER BY created_at ASC",
        conversation_ids,
    ).fetchall()

    summary_lines: list[str] = []
    excerpt_lines: list[str] = []
    for row in rows:
        cid, _run_id, recipient, direction, body, intent, ts = row
        body_short = str(body).replace("\n", " ")[:240]
        if intent == "instruction" and direction == "inbound":
            summary_lines.append(f"- [{recipient}] {body_short}")
        excerpt_lines.append(
            f"- [{ts[:16]}] {recipient} {direction}: \"{body_short}\""
        )

    summary = "\n".join(summary_lines) or "(no instruction-typed turns)"
    excerpt = "\n".join(excerpt_lines)
    return summary, excerpt


def _choose_provider_and_model(conn: sqlite3.Connection) -> tuple[str, str]:
    """Pick claude-opus when headroom permits, else MiniMax fallback."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        return ("minimax", MINIMAX_FALLBACK_MODEL)

    today_midnight = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0) FROM llm_calls WHERE created_at >= ?",
        (today_midnight,),
    ).fetchone()
    today_spend: float = row[0] if row else 0.0
    remaining = settings.daily_cost_ceiling_usd - today_spend
    if remaining >= OPUS_BUDGET_THRESHOLD:
        return ("claude", OPUS_MODEL)
    return ("minimax", MINIMAX_FALLBACK_MODEL)


_PATCH_RE = re.compile(r"<patch>(.*?)</patch>", re.DOTALL | re.IGNORECASE)
_TARGET_RE = re.compile(r"<target>\s*(.*?)\s*</target>", re.DOTALL | re.IGNORECASE)
_BEFORE_RE = re.compile(
    r"<before>(?:\s*<!\[CDATA\[)?(.*?)(?:\]\]>\s*)?</before>", re.DOTALL | re.IGNORECASE
)
_AFTER_RE = re.compile(
    r"<after>(?:\s*<!\[CDATA\[)?(.*?)(?:\]\]>\s*)?</after>", re.DOTALL | re.IGNORECASE
)
_RATIONALE_RE = re.compile(
    r"<rationale>\s*(.*?)\s*</rationale>", re.DOTALL | re.IGNORECASE
)


def parse_patches(text: str) -> list[tuple[str, str, str, str]]:
    """Parse <patch> blocks from the LLM output. Returns (target, before, after, rationale)."""
    out: list[tuple[str, str, str, str]] = []
    for block in _PATCH_RE.findall(text):
        target_match = _TARGET_RE.search(block)
        before_match = _BEFORE_RE.search(block)
        after_match = _AFTER_RE.search(block)
        rationale_match = _RATIONALE_RE.search(block)
        if not (target_match and before_match and after_match):
            continue
        out.append(
            (
                target_match.group(1).strip(),
                before_match.group(1),
                after_match.group(1),
                (rationale_match.group(1) if rationale_match else "").strip(),
            )
        )
    return out


def propose_rewrite(
    conversation_ids: list[int], conn: sqlite3.Connection
) -> list[RewriteProposal]:
    """Ask the Opus rewriter to draft byte-exact patches based on instructions."""
    if not conversation_ids:
        return []

    settings = get_settings()
    try:
        check_cost_ceiling(conn, settings)
    except CostCeilingError:
        logger.warning("propose_rewrite skipped: cost ceiling reached")
        return []

    instruction_summary, conversation_excerpt = _gather_instruction_excerpt(
        conn, conversation_ids
    )
    research_prompt = _read_file_or_default("prompts/research.txt")
    current_rules = _read_file_or_default("data/rules/current.md", "(no rules yet)")

    system_template, user_template = _load_rewrite_prompt()
    user_message = user_template.format(
        instruction_summary=instruction_summary,
        conversation_excerpt=conversation_excerpt,
        research_prompt=research_prompt,
        current_rules=current_rules,
    )

    provider, model = _choose_provider_and_model(conn)
    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    try:
        client = get_client(provider)
        response: ChatResponse = client.chat(
            messages=messages,
            model=model,
            max_tokens=REWRITE_MAX_TOKENS,
            conn=conn,
            caller="prompt_rewriter.propose",
            cached_system=system_template,
        )
    except CostCeilingError:
        return []
    except Exception:
        logger.exception("propose_rewrite LLM call failed")
        return []

    parsed = parse_patches(response.content)
    proposals: list[RewriteProposal] = []
    triggered_by = conversation_ids[0] if conversation_ids else None
    for target, before, after, rationale in parsed:
        if target not in ALLOWED_TARGETS:
            logger.warning("propose_rewrite rejected disallowed target=%s", target)
            continue
        if not before:
            continue
        if len(after) > 2 * len(before) + DIFF_SIZE_BUFFER:
            logger.warning(
                "propose_rewrite rejected oversized diff for %s", target
            )
            continue
        proposals.append(
            RewriteProposal(
                target_path=target,
                before_text=before,
                after_text=after,
                rationale=rationale,
                cost_usd=response.cost_usd,
                triggered_by_conversation_id=triggered_by,
                low_confidence=(provider != "claude"),
            )
        )
    return proposals


def _last_applied_for_path(
    conn: sqlite3.Connection, target_path: str
) -> str | None:
    """Return the most recent applied_at for a target path."""
    row = conn.execute(
        "SELECT MAX(applied_at) FROM prompt_rewrites"
        " WHERE target_path = ? AND applied = 1",
        (target_path,),
    ).fetchone()
    return row[0] if row and row[0] else None


def _under_rate_limit(
    conn: sqlite3.Connection, target_path: str
) -> bool:
    """True when an apply for the same path happened within RATE_LIMIT_HOURS."""
    last = _last_applied_for_path(conn, target_path)
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RATE_LIMIT_HOURS)
    return last_dt > cutoff


def apply_rewrite(
    proposal: RewriteProposal,
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
) -> int | None:
    """Apply a proposal byte-exactly. Returns prompt_rewrites.id when applied."""
    if proposal.target_path not in ALLOWED_TARGETS:
        raise ValueError(f"target {proposal.target_path} not in ALLOWED_TARGETS")

    target_path = Path(proposal.target_path)
    if not target_path.exists():
        # Stage as not-applied for human review
        return _stage(conn, proposal, applied=False)

    if _under_rate_limit(conn, proposal.target_path):
        logger.info(
            "apply_rewrite rate-limited for %s; staging unapplied",
            proposal.target_path,
        )
        return _stage(conn, proposal, applied=False)

    current = target_path.read_text(encoding="utf-8")
    if proposal.before_text not in current:
        # Cannot match verbatim; stage for human review
        return _stage(conn, proposal, applied=False)

    new_content = current.replace(proposal.before_text, proposal.after_text, 1)
    if dry_run:
        return None

    target_path.write_text(new_content, encoding="utf-8")
    return _stage(conn, proposal, applied=True)


def _stage(
    conn: sqlite3.Connection, proposal: RewriteProposal, *, applied: bool
) -> int:
    """Insert a prompt_rewrites row and return its id."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO prompt_rewrites (target_path, before_text, after_text,"
        " rationale, triggered_by_conversation_id, cost_usd, applied,"
        " applied_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            proposal.target_path, proposal.before_text, proposal.after_text,
            proposal.rationale, proposal.triggered_by_conversation_id,
            proposal.cost_usd, 1 if applied else 0,
            now if applied else None, now,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)


def revert_rewrite(rewrite_id: int, conn: sqlite3.Connection) -> bool:
    """Restore the original `before_text` content for a previously-applied rewrite."""
    row = conn.execute(
        "SELECT target_path, before_text, after_text, applied"
        " FROM prompt_rewrites WHERE id = ?",
        (rewrite_id,),
    ).fetchone()
    if row is None:
        return False
    target_path, before_text, after_text, applied = row
    if not applied:
        return False
    p = Path(str(target_path))
    if not p.exists():
        return False
    current = p.read_text(encoding="utf-8")
    if str(after_text) not in current:
        return False
    new_content = current.replace(str(after_text), str(before_text), 1)
    p.write_text(new_content, encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE prompt_rewrites SET applied = 0, applied_at = ? WHERE id = ?",
        (now, rewrite_id),
    )
    conn.commit()
    return True
