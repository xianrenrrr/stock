"""stock.learn -- post-outcome learning: bandit, calibration, and weekly reflection."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from stock.bandit import get_ticker_bucket, update_arm_posterior
from stock.calibrate import fit_calibration
from stock.config import get_settings
from stock.models import ChatMessage, ChatResponse, check_cost_ceiling, get_client

logger = logging.getLogger(__name__)


def update_bandit(prediction_id: int, conn: sqlite3.Connection) -> None:
    """Update bandit posteriors for a scored prediction."""
    # Look up prediction arm and ticker
    pred_row = conn.execute(
        "SELECT strategy_arm, ticker FROM predictions WHERE id = ?",
        (prediction_id,),
    ).fetchone()
    if pred_row is None:
        raise ValueError(f"Prediction {prediction_id} not found")

    strategy_arm, ticker = pred_row

    # Skip pre-F05 predictions that have no arm tracked
    if strategy_arm is None:
        return

    # Look up the outcome direction hit
    outcome_row = conn.execute(
        "SELECT direction_hit FROM outcomes WHERE prediction_id = ?",
        (prediction_id,),
    ).fetchone()
    if outcome_row is None:
        raise ValueError(f"Outcome for prediction {prediction_id} not found")

    # Update bandit posteriors
    reward = float(outcome_row[0])
    bucket = get_ticker_bucket(ticker)
    update_arm_posterior(strategy_arm, bucket, reward, conn)
    conn.commit()


def refit_calibration(conn: sqlite3.Connection) -> int | None:
    """Refit the calibration model on accumulated outcomes."""
    version = fit_calibration(conn)
    if version is None:
        logger.info("Calibration refit skipped: too few samples")
    else:
        logger.info("Calibration model refitted, version %d", version)
    return version


# ---------------------------------------------------------------------------
# Weekly reflection
# ---------------------------------------------------------------------------

RULES_DIR: str = "data/rules"
REFLECT_PROMPT_PATH: str = "prompts/reflect.txt"
OPUS_BUDGET_THRESHOLD: float = 1.0
OPUS_MODEL: str = "claude-opus-4-6"
REFLECT_MAX_TOKENS: int = 2000


class ReflectResult(BaseModel):
    """Result of a weekly reflection run."""

    version: int
    provider: str
    model: str
    dry_run: bool
    rules_text: str
    prediction_count: int
    scored_count: int


@lru_cache(maxsize=1)
def _load_reflect_prompt() -> tuple[str, str]:
    """Load and split the reflection prompt on [SYSTEM]/[USER] markers."""
    path = Path(REFLECT_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Reflection prompt not found at {REFLECT_PROMPT_PATH}")
    text = path.read_text(encoding="utf-8")

    # Split on markers
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


def _choose_reflect_provider(conn: sqlite3.Connection) -> tuple[str, str]:
    """Pick provider and model for reflection based on budget and API key availability."""
    settings = get_settings()

    # No Anthropic key means MiniMax only
    if not settings.anthropic_api_key:
        return ("minimax", "MiniMax-M1-80k")

    # Check remaining daily budget
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
    return ("minimax", "MiniMax-M1-80k")


def _get_recent_prediction_outcomes(
    conn: sqlite3.Connection, days: int = 7
) -> list[dict[str, str | float | int | None]]:
    """Query predictions with outcomes from the last N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = conn.execute(
        "SELECT p.id, p.ticker, p.direction, p.prob_up, p.confidence,"
        "       p.rationale, p.key_factors_json, p.created_at,"
        "       o.actual_return, o.direction_hit, o.brier"
        " FROM predictions p"
        " JOIN outcomes o ON p.id = o.prediction_id"
        " WHERE p.created_at >= ?"
        " ORDER BY p.created_at ASC",
        (cutoff,),
    ).fetchall()

    return [
        {
            "id": r[0],
            "ticker": r[1],
            "direction": r[2],
            "prob_up": r[3],
            "confidence": r[4],
            "rationale": r[5],
            "key_factors_json": r[6],
            "created_at": r[7],
            "actual_return": r[8],
            "direction_hit": r[9],
            "brier": r[10],
        }
        for r in rows
    ]


def _format_prediction_outcomes(
    rows: list[dict[str, str | float | int | None]],
) -> str:
    """Format prediction+outcome rows into readable text for the prompt."""
    if not rows:
        return "No scored predictions in the review period."

    lines: list[str] = []
    for row in rows:
        # Parse key factors if available
        key_factors_str = ""
        kf_raw = row.get("key_factors_json")
        if kf_raw and isinstance(kf_raw, str):
            try:
                factors = json.loads(kf_raw)
                if isinstance(factors, list):
                    key_factors_str = ", ".join(str(f) for f in factors)
            except (json.JSONDecodeError, TypeError):
                pass

        # Format the date prefix
        created = str(row.get("created_at", "unknown"))[:10]
        ticker = row.get("ticker", "???")
        direction = row.get("direction", "?")
        prob_up = row.get("prob_up")
        confidence = row.get("confidence")
        actual_return = row.get("actual_return")
        direction_hit = row.get("direction_hit")
        brier = row.get("brier")
        rationale = row.get("rationale", "")

        prob_str = f"{prob_up:.2f}" if isinstance(prob_up, (int, float)) else "?"
        conf_str = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "?"
        ret_str = f"{actual_return:+.1%}" if isinstance(actual_return, (int, float)) else "?"
        hit_str = "YES" if direction_hit else "NO"
        brier_str = f"{brier:.2f}" if isinstance(brier, (int, float)) else "?"

        block = (
            f"[{created}] {ticker} | Predicted: {direction} (prob={prob_str}, conf={conf_str})\n"
            f"  Outcome: {ret_str} | Hit: {hit_str} | Brier: {brier_str}\n"
            f"  Rationale: {rationale}"
        )
        if key_factors_str:
            block += f"\n  Key factors: {key_factors_str}"
        lines.append(block)

    return "\n\n".join(lines)


def _format_stats_summary(
    rows: list[dict[str, str | float | int | None]],
) -> str:
    """Compute and format aggregate stats from prediction+outcome rows."""
    total = len(rows)
    if total == 0:
        return "No scored predictions in the review period."

    # Compute aggregate metrics
    hits = sum(1 for r in rows if r.get("direction_hit"))
    briers: list[float] = []
    returns_list: list[float] = []
    for r in rows:
        bval = r.get("brier")
        if isinstance(bval, (int, float)):
            briers.append(float(bval))
        rval = r.get("actual_return")
        if isinstance(rval, (int, float)):
            returns_list.append(float(rval))

    hit_rate = hits / total if total > 0 else 0.0
    mean_brier = sum(briers) / len(briers) if briers else 0.0
    total_return_bps = sum(r * 10000 for r in returns_list) if returns_list else 0.0

    return (
        f"Predictions scored: {total}\n"
        f"Hit rate: {hit_rate:.1%}\n"
        f"Mean Brier score: {mean_brier:.4f}\n"
        f"Total return: {total_return_bps:+.0f} bps"
    )


def _get_current_rules_text() -> str:
    """Read the current rules document from disk."""
    path = Path(RULES_DIR) / "current.md"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return "No rules established yet."


def _get_next_version(conn: sqlite3.Connection) -> int:
    """Return the next rules version number."""
    row = conn.execute("SELECT MAX(version) FROM rules").fetchone()
    current = row[0] if row and row[0] is not None else 0
    return current + 1


def _extract_rules_text(raw_response: str) -> str:
    """Extract rules content from between <rules> tags, or use full response."""
    match = re.search(r"<rules>(.*?)</rules>", raw_response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw_response.strip()


def _ensure_seed_rules(conn: sqlite3.Connection) -> None:
    """Insert seed rules into the DB if the rules table is empty."""
    # Check if rules table already has rows
    row = conn.execute("SELECT COUNT(*) FROM rules").fetchone()
    if row and row[0] > 0:
        return

    # Read seed file
    seed_path = Path(RULES_DIR) / "v001.md"
    if not seed_path.exists():
        return

    content = seed_path.read_text(encoding="utf-8").strip()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO rules (version, text, reflection_input_ids, created_at)"
        " VALUES (?, ?, ?, ?)",
        (1, content, None, now),
    )
    conn.commit()


def reflect_weekly(
    conn: sqlite3.Connection, *, dry_run: bool = False
) -> ReflectResult:
    """Run weekly reflection: analyze recent outcomes and produce updated rules."""
    # Ensure seed rules exist in the database
    _ensure_seed_rules(conn)

    # Load recent prediction+outcome pairs
    rows = _get_recent_prediction_outcomes(conn)
    prediction_count = len(rows)

    # Format data for the prompt
    prediction_outcomes = _format_prediction_outcomes(rows)
    stats_summary = _format_stats_summary(rows)

    # Read current rules from disk
    current_rules = _get_current_rules_text()

    # Choose provider and model based on budget
    provider, model = _choose_reflect_provider(conn)

    # Load and format the reflection prompt
    system_template, user_template = _load_reflect_prompt()
    system_prompt = system_template
    user_message = user_template.format(
        current_rules=current_rules,
        stats_summary=stats_summary,
        prediction_outcomes=prediction_outcomes,
    )

    # Check cost ceiling before calling LLM
    settings = get_settings()
    check_cost_ceiling(conn, settings)

    # Call LLM for reflection
    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    client = get_client(provider)
    response: ChatResponse = client.chat(
        messages=messages,
        model=model,
        max_tokens=REFLECT_MAX_TOKENS,
        conn=conn,
        caller="learn.reflect_weekly",
        cached_system=system_prompt,
    )

    # Extract the rules document from the LLM response
    rules_text = _extract_rules_text(response.content)
    if not rules_text:
        raise RuntimeError("Reflection produced empty rules")

    # In dry-run mode, return without writing
    if dry_run:
        return ReflectResult(
            version=_get_next_version(conn),
            provider=provider,
            model=model,
            dry_run=True,
            rules_text=rules_text,
            prediction_count=prediction_count,
            scored_count=prediction_count,
        )

    # Compute next version and write files
    version = _get_next_version(conn)
    rules_dir = Path(RULES_DIR)
    rules_dir.mkdir(parents=True, exist_ok=True)

    # Write versioned rules file
    version_path = rules_dir / f"v{version:03d}.md"
    version_path.write_text(rules_text + "\n", encoding="utf-8")

    # Overwrite current.md
    current_path = rules_dir / "current.md"
    current_path.write_text(rules_text + "\n", encoding="utf-8")

    # Insert into rules table
    now = datetime.now(timezone.utc).isoformat()
    input_ids = [r["id"] for r in rows]
    conn.execute(
        "INSERT INTO rules (version, text, reflection_input_ids, created_at)"
        " VALUES (?, ?, ?, ?)",
        (version, rules_text, json.dumps(input_ids), now),
    )
    conn.commit()

    logger.info("Reflection v%03d written (%s/%s), %d predictions reviewed",
                version, provider, model, prediction_count)

    return ReflectResult(
        version=version,
        provider=provider,
        model=model,
        dry_run=False,
        rules_text=rules_text,
        prediction_count=prediction_count,
        scored_count=prediction_count,
    )
