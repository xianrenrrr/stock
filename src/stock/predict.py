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
    get_core_client,
    get_core_model,
    parse_llm_json,
)

logger = logging.getLogger(__name__)

PREDICT_PROMPT_PATH: str = "prompts/predict.txt"
RULES_DIR: str = "data/rules"
DEFAULT_HORIZON_MINUTES: int = 390
PRICE_LOOKBACK: int = 10
AI_INFRA_BREADTH_MIN_OBSERVATIONS: int = 5
AI_INFRA_BREADTH_THRESHOLD: float = 0.65
AI_INFRA_BEARISH_BREADTH_FLOOR: float = 0.49
AI_INFRA_TICKERS: set[str] = {
    "AMAT", "AMD", "ASML", "AVGO", "COHR", "CRDO", "DELL", "ETN", "KLAC",
    "LITE", "LRCX", "MRVL", "MTSI", "MU", "MXL", "NVDA", "SMCI", "SMTC",
    "TSM", "VRT", "VST",
}
AI_INFRA_SECTOR_LEADERS: set[str] = {"AMD", "AVGO", "MU", "NVDA", "SMCI"}
AI_INFRA_KEYWORDS: tuple[str, ...] = (
    "ai demand", "ai infrastructure", "ai hardware", "semiconductor",
    "semis", "wafer", "hbm", "memory", "gpu", "optics", "optical",
    "power", "cooling", "data center", "datacenter", "nvidia",
)
FRESH_HARD_CATALYSTS: set[str] = {
    "earnings", "guidance", "earnings_guidance", "m&a", "merger",
    "acquisition", "fda", "contract",
}


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


def _parse_feature_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _has_fresh_hard_catalyst(
    features: list[dict[str, Any]], as_of: datetime
) -> bool:
    """Return true when a recent feature is strong enough to override stale-tape caps."""
    for feat in features:
        catalyst = str(feat.get("catalyst_type", "")).strip().lower()
        if catalyst not in FRESH_HARD_CATALYSTS:
            continue
        ts = _parse_feature_ts(feat.get("ts"))
        if ts is None:
            continue
        age = as_of - ts
        if timedelta(0) <= age <= timedelta(hours=24):
            return True
    return False


def _has_fresh_negative_hard_catalyst(
    features: list[dict[str, Any]], as_of: datetime
) -> bool:
    """Return true when a fresh hard catalyst is explicitly bearish."""
    for feat in features:
        catalyst = str(feat.get("catalyst_type", "")).strip().lower()
        if catalyst not in FRESH_HARD_CATALYSTS:
            continue
        sentiment = str(feat.get("sentiment", "")).strip().lower()
        if sentiment not in {"bearish", "negative"}:
            continue
        ts = _parse_feature_ts(feat.get("ts"))
        if ts is None:
            continue
        age = as_of - ts
        if timedelta(0) <= age <= timedelta(hours=24):
            return True
    return False


def _recent_return(prices: list[dict[str, Any]], bars: int = 2) -> float | None:
    if len(prices) <= bars:
        return None
    start = float(prices[-(bars + 1)]["c"])
    end = float(prices[-1]["c"])
    if start <= 0:
        return None
    return (end - start) / start


def _latest_return_for_ticker(ticker: str, conn: sqlite3.Connection) -> float | None:
    rows = conn.execute(
        "SELECT c FROM prices WHERE ticker = ? ORDER BY ts DESC LIMIT 2",
        (ticker,),
    ).fetchall()
    if len(rows) < 2:
        return None
    latest = float(rows[0][0])
    prior = float(rows[1][0])
    if prior <= 0:
        return None
    return (latest - prior) / prior


def _ai_infra_breadth_positive(conn: sqlite3.Connection) -> bool:
    returns: dict[str, float] = {}
    for peer in AI_INFRA_TICKERS:
        ret = _latest_return_for_ticker(peer, conn)
        if ret is not None:
            returns[peer] = ret

    if len(returns) < AI_INFRA_BREADTH_MIN_OBSERVATIONS:
        return False

    positive_share = sum(1 for ret in returns.values() if ret > 0) / len(returns)
    leader_positive = any(
        returns.get(leader, 0.0) > 0 for leader in AI_INFRA_SECTOR_LEADERS
    )
    return positive_share >= AI_INFRA_BREADTH_THRESHOLD and leader_positive


def _text_mentions_ai_infra(output: PredictionOutput) -> bool:
    text = " ".join(
        [output.rationale, *[str(f) for f in output.key_factors]]
    ).lower()
    return any(keyword in text for keyword in AI_INFRA_KEYWORDS)


def apply_probability_guardrails(
    ticker: str,
    output: PredictionOutput,
    features: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    *,
    as_of: datetime | None = None,
    conn: sqlite3.Connection | None = None,
) -> PredictionOutput:
    """Apply deterministic caps learned from recent grading failures.

    The LLM remains the forecaster, but recent reviews showed repeated
    overconfidence in stale AI/semis/power/optics bullish narratives. These
    guardrails keep those narratives from independently pushing mild bullish
    calls into the 0.55-0.64 range when tape is already rolling over.
    """
    ticker_upper = ticker.upper()
    if ticker_upper not in AI_INFRA_TICKERS and not _text_mentions_ai_infra(output):
        return output

    now = as_of or datetime.now(timezone.utc)
    if (
        output.direction == "down"
        and output.prob_up < AI_INFRA_BEARISH_BREADTH_FLOOR
        and conn is not None
        and not _has_fresh_negative_hard_catalyst(features, now)
        and _ai_infra_breadth_positive(conn)
    ):
        logger.info(
            "prob_up breadth floor for %s: %.2f -> %.2f",
            ticker_upper, output.prob_up, AI_INFRA_BEARISH_BREADTH_FLOOR,
        )
        output.prob_up = AI_INFRA_BEARISH_BREADTH_FLOOR
        output.confidence = min(output.confidence, 1.0 - AI_INFRA_BEARISH_BREADTH_FLOOR)
        output.expected_return_bps = max(output.expected_return_bps, -10)
        output.rationale = (
            output.rationale.rstrip()
            + " Probability floored because AI/semis peer breadth is positive "
            "and there is no fresh negative hard catalyst."
        )
        return output

    if output.direction != "up":
        return output

    fresh_hard_catalyst = _has_fresh_hard_catalyst(features, now)
    recent_ret = _recent_return(prices, bars=2)
    negative_tape = recent_ret is not None and recent_ret < 0

    cap: float | None = None
    reason: str | None = None
    if negative_tape and not fresh_hard_catalyst:
        cap = 0.52
        reason = "AI/semis narrative with negative recent tape and no fresh hard catalyst"
    elif not fresh_hard_catalyst:
        cap = 0.55
        reason = "AI/semis narrative without a fresh hard catalyst"

    if cap is not None and output.prob_up > cap:
        logger.info(
            "prob_up guardrail for %s: %.2f -> %.2f (%s)",
            ticker_upper, output.prob_up, cap, reason,
        )
        output.prob_up = cap
        output.confidence = max(0.0, min(output.confidence, cap))
        output.expected_return_bps = min(output.expected_return_bps, int((cap - 0.5) * 1000))
        output.rationale = (
            output.rationale.rstrip()
            + f" Probability capped because {reason}."
        )

    return output


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

    # Select strategy arm via Thompson sampling bandit. The arm's `name` is
    # still recorded on the prediction row (so future bandit work can attribute
    # reward), but the provider/model fields are ignored: every core LLM call
    # routes through get_core_client() per the AI_INDEX convention, which
    # honors the operator's CORE_LLM_BACKEND selection (codex_cli with
    # claude_cli fallback). The hardcoded REGISTERED_ARMS pointed at a retired
    # MiniMax model and was 400'ing every prediction.
    arm = select_arm(ticker, conn)

    # Call LLM via the active core backend (codex_cli + claude_cli fallback)
    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    client = get_core_client()
    chosen_model = get_core_model()
    response = client.chat(
        messages=messages,
        model=chosen_model,
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

    output = apply_probability_guardrails(ticker, output, features, prices, conn=conn)

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
            response.model,
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
