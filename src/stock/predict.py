"""stock.predict -- run a single-ticker prediction cycle."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from stock.bandit import select_arm
from stock.calibrate import calibrate
from stock.features import extract_features
from stock.memory import embed, format_retrieved_cases, retrieve
from stock.models import (
    ChatMessage,
    get_client,
    parse_llm_json,
)

logger = logging.getLogger(__name__)

PREDICT_PROMPT_PATH: str = "prompts/predict.txt"
RULES_DIR: str = "data/rules"
DEFAULT_HORIZON_MINUTES: int = 390
PRICE_LOOKBACK: int = 10


class PredictionOutput(BaseModel):
    """Raw LLM prediction response."""

    direction: str
    prob_up: float
    expected_return_bps: float
    confidence: float
    rationale: str
    key_factors: list[str]


class PredictionResult(BaseModel):
    """Result returned to callers after a prediction is stored."""

    prediction_id: int
    ticker: str
    direction: str
    prob_up: float
    prob_up_calibrated: float | None
    confidence: float
    rationale: str
    created_at: str
    due_at: str


@lru_cache(maxsize=1)
def load_predict_prompt() -> tuple[str, str]:
    """Load and split the prediction prompt into system and user templates."""
    path = Path(PREDICT_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Prediction prompt not found at {PREDICT_PROMPT_PATH}")
    text = path.read_text(encoding="utf-8")

    # Split on [SYSTEM] and [USER] markers
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


def _load_current_rules(conn: sqlite3.Connection) -> tuple[str, int | None]:
    """Load current rules text from disk and the latest version number from DB."""
    # Read rules text from disk
    rules_path = Path(RULES_DIR) / "current.md"
    if rules_path.exists():
        rules_text = rules_path.read_text(encoding="utf-8").strip()
    else:
        rules_text = "No rules established yet."

    # Look up the latest version number
    row = conn.execute("SELECT MAX(version) FROM rules").fetchone()
    rules_version: int | None = row[0] if row and row[0] is not None else None
    return rules_text, rules_version


def get_recent_prices(
    ticker: str, conn: sqlite3.Connection, limit: int = PRICE_LOOKBACK
) -> list[dict[str, Any]]:
    """Return recent price bars for a ticker, oldest first."""
    rows = conn.execute(
        "SELECT ts, o, h, l, c, v FROM prices"
        " WHERE ticker = ? ORDER BY ts DESC LIMIT ?",
        (ticker, limit),
    ).fetchall()

    if not rows:
        raise ValueError(
            f"No price data for {ticker}. Run 'stock ingest prices {ticker}' first."
        )

    return [
        {"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]}
        for r in reversed(rows)
    ]


def get_recent_features(
    ticker: str, conn: sqlite3.Connection
) -> list[dict[str, Any]]:
    """Return recently extracted feature summaries for a ticker."""
    rows = conn.execute(
        "SELECT f.json, n.title, n.ts FROM features f"
        " JOIN news n ON f.news_id = n.id"
        " WHERE n.ticker = ? ORDER BY n.ts DESC LIMIT 20",
        (ticker,),
    ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        feature_data: dict[str, Any] = json.loads(row[0])
        feature_data["title"] = row[1]
        feature_data["ts"] = row[2]
        results.append(feature_data)
    return results


def compute_due_at(created_at: datetime, horizon_minutes: int) -> str:
    """Compute the ISO timestamp when a prediction should be scored."""
    # US market close conservatively at 21:00 UTC
    market_close_today = created_at.replace(
        hour=21, minute=0, second=0, microsecond=0
    )

    # Determine the base market close
    if created_at < market_close_today:
        base = market_close_today
    else:
        base = market_close_today + timedelta(days=1)

    # Skip weekends for base
    while base.weekday() >= 5:
        base += timedelta(days=1)

    # For 1-day horizon, advance to next weekday close
    if horizon_minutes == DEFAULT_HORIZON_MINUTES:
        due = base + timedelta(days=1)
        while due.weekday() >= 5:
            due += timedelta(days=1)
    else:
        due = base + timedelta(minutes=horizon_minutes)

    return due.isoformat()


def _format_feature_summary(features: list[dict[str, Any]]) -> str:
    """Format extracted features into a readable text block for the prompt."""
    if not features:
        return "No features available."

    lines: list[str] = []
    for feat in features:
        line = (
            f"- [{feat.get('ts', 'unknown')}] {feat.get('title', 'untitled')}: "
            f"sentiment={feat.get('sentiment', '?')}, "
            f"catalyst={feat.get('catalyst_type', '?')}, "
            f"novelty={feat.get('novelty', '?')}, "
            f"sensitivity={feat.get('time_sensitivity', '?')}"
        )
        summary = feat.get("summary", "")
        if summary:
            line += f"\n  {summary}"
        lines.append(line)
    return "\n".join(lines)


def _format_price_history(prices: list[dict[str, Any]]) -> str:
    """Format price bars into a markdown table for the prompt."""
    lines: list[str] = ["Date | Open | High | Low | Close | Volume"]
    lines.append("--- | --- | --- | --- | --- | ---")
    for bar in prices:
        lines.append(
            f"{bar['ts']} | {bar['o']:.2f} | {bar['h']:.2f} | "
            f"{bar['l']:.2f} | {bar['c']:.2f} | {bar['v']}"
        )
    return "\n".join(lines)


def predict_ticker(
    ticker: str, conn: sqlite3.Connection
) -> PredictionResult:
    """Run a full single-ticker prediction cycle."""
    # Ensure all news has features extracted
    extract_features(ticker, conn)

    # Load recent price data
    prices = get_recent_prices(ticker, conn)

    # Load recent feature summaries
    features = get_recent_features(ticker, conn)
    if not features:
        raise ValueError(
            f"No features for {ticker}. Run 'stock ingest news {ticker}' first."
        )

    # Load and split the prompt template
    system_template, user_template = load_predict_prompt()

    # Load current rules from disk and track version
    rules_text, rules_version = _load_current_rules(conn)
    system_prompt = system_template.format(rules=rules_text)

    # Build user message with all context
    feature_summary = _format_feature_summary(features)
    price_history = _format_price_history(prices)

    # Retrieve similar past prediction cases
    query_embedding = embed(feature_summary)
    retrieved = retrieve(ticker, query_embedding, conn)
    retrieved_text = format_retrieved_cases(retrieved)
    retrieved_ids = [c.prediction_id for c in retrieved]

    user_message = user_template.format(
        ticker=ticker,
        horizon="1 trading day",
        feature_summary=feature_summary,
        price_count=len(prices),
        price_history=price_history,
        retrieved_cases=retrieved_text,
    )

    # Select strategy arm via Thompson sampling bandit
    arm = select_arm(ticker, conn)

    # Call LLM for prediction using bandit-selected arm
    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    client = get_client(arm.provider)
    response = client.chat(
        messages=messages,
        model=arm.model,
        max_tokens=500,
        conn=conn,
        caller="predict.predict_ticker",
        cached_system=system_prompt,
    )

    # Parse and validate LLM response
    parsed = parse_llm_json(response.content)
    output = PredictionOutput(**parsed)

    # Clamp prob_up to [0.0, 1.0]
    if output.prob_up < 0.0 or output.prob_up > 1.0:
        logger.warning("prob_up=%.4f outside [0, 1], clamping", output.prob_up)
        output.prob_up = max(0.0, min(1.0, output.prob_up))

    # Clamp confidence to [0.0, 1.0]
    if output.confidence < 0.0 or output.confidence > 1.0:
        logger.warning("confidence=%.4f outside [0, 1], clamping", output.confidence)
        output.confidence = max(0.0, min(1.0, output.confidence))

    # Validate direction, infer from prob_up if invalid
    if output.direction not in ("up", "down"):
        logger.warning(
            "direction='%s' invalid, inferring from prob_up", output.direction
        )
        output.direction = "up" if output.prob_up >= 0.5 else "down"

    # Apply calibration to raw prob_up
    calibrated_prob = calibrate(output.prob_up, conn)

    # Compute timestamps
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    due_at = compute_due_at(now, DEFAULT_HORIZON_MINUTES)

    # Build context JSON for auditing
    feature_context = json.dumps({
        "features": features,
        "prices": prices,
        "retrieved_case_ids": retrieved_ids,
    })

    # Insert prediction row
    cursor = conn.execute(
        "INSERT INTO predictions ("
        "  ticker, horizon_minutes, direction, prob_up, prob_up_calibrated,"
        "  expected_return_bps, confidence, rationale, key_factors_json,"
        "  model_used, strategy_arm, rules_version, retrieved_case_ids,"
        "  created_at, due_at, feature_context_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ticker,
            DEFAULT_HORIZON_MINUTES,
            output.direction,
            output.prob_up,
            calibrated_prob,
            output.expected_return_bps,
            output.confidence,
            output.rationale,
            json.dumps(output.key_factors),
            arm.model,
            arm.strategy_arm,
            rules_version,
            json.dumps(retrieved_ids) if retrieved_ids else None,
            created_at,
            due_at,
            feature_context,
        ),
    )
    conn.commit()

    # F16: best-effort thesis extraction. Failures (cost ceiling, JSON parse,
    # network) are logged and swallowed -- the prediction is still valid even
    # if its rationale never gets decomposed.
    prediction_id = int(cursor.lastrowid or 0)
    try:
        from stock.thesis import extract_theses

        extract_theses(prediction_id, conn)
    except Exception:
        logger.exception("predict: thesis extract failed for prediction %d", prediction_id)

    return PredictionResult(
        prediction_id=prediction_id,
        ticker=ticker,
        direction=output.direction,
        prob_up=output.prob_up,
        prob_up_calibrated=calibrated_prob,
        confidence=output.confidence,
        rationale=output.rationale,
        created_at=created_at,
        due_at=due_at,
    )
