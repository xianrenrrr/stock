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
# Weekly track (boss 2026-06-18): predict Sunday, score the following Saturday.
# 1950 = 5 trading days * 390 min, used purely as the horizon marker that
# distinguishes a weekly prediction row from a daily one in the predictions
# table. due_at is computed by compute_weekly_due_at, not from these minutes.
WEEKLY_HORIZON_MINUTES: int = 1950


def compute_weekly_due_at(created_at: datetime) -> str:
    """Due at the coming Saturday 00:00 UTC -- after that week's Friday close.

    A prediction made on Sunday gets entry = the prior Friday close and exit =
    the next Friday close (score_due picks the earliest bar at/after due_at),
    i.e. a full Friday-to-Friday trading week.
    """
    # Saturday == weekday 5. Advance to the next Saturday strictly in the future.
    due = created_at.replace(hour=0, minute=0, second=0, microsecond=0)
    due += timedelta(days=1)
    while due.weekday() != 5:
        due += timedelta(days=1)
    return due.isoformat()
PRICE_LOOKBACK: int = 10
AI_INFRA_BREADTH_MIN_OBSERVATIONS: int = 5
AI_INFRA_BREADTH_THRESHOLD: float = 0.65
AI_INFRA_MEDIAN_RETURN_THRESHOLD: float = 0.015
AI_INFRA_BEARISH_BREADTH_FLOOR: float = 0.50
CALIBRATION_NEUTRAL_PROB: float = 0.50
PEER_READTHROUGH_DOWNCALL_MIN: float = 0.47
PEER_READTHROUGH_DOWNCALL_FLOOR: float = 0.50
AI_INFRA_TICKERS: set[str] = {
    "AAOI", "ACMR", "AMAT", "AMD", "AOSL", "ASML", "AVGO", "CAMT", "COHR",
    "CRDO", "DELL", "ETN", "KLAC", "LITE", "LRCX", "MRVL", "MTSI", "MU",
    "MXL", "NVDA", "SMCI", "SMTC", "TSM", "VRT", "VST",
}
SEMI_MEMORY_TICKERS: set[str] = AI_INFRA_TICKERS | {"INTC", "SNDK", "WDC"}
AI_INFRA_SECTOR_LEADERS: set[str] = {"AMD", "AVGO", "MRVL", "MU", "NVDA", "SMCI"}
AI_INFRA_KEYWORDS: tuple[str, ...] = (
    "ai demand", "ai infrastructure", "ai hardware", "semiconductor",
    "semis", "wafer", "hbm", "memory", "gpu", "optics", "optical",
    "power", "cooling", "data center", "datacenter", "nvidia",
)
PEER_READTHROUGH_KEYWORDS: tuple[str, ...] = (
    "peer read-through", "peer/sector", "read-through", "broadcom", "avgo",
    "single peer", "sector earnings read",
)
FRESH_HARD_CATALYSTS: set[str] = {
    "earnings", "guidance", "earnings_guidance", "m&a", "merger",
    "acquisition", "fda", "contract",
}
POST_CATALYST_EXHAUSTION_RETURN_THRESHOLD: float = 0.08
POST_CATALYST_EXHAUSTION_CAP: float = 0.51
STALE_UPCALL_CAP: float = 0.50
CONFIRMING_VOLUME_MULTIPLE: float = 1.2


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


def _has_aged_positive_hard_catalyst(
    features: list[dict[str, Any]], as_of: datetime
) -> bool:
    """Return true for positive hard catalysts in the day-2/day-3 decay window."""
    for feat in features:
        catalyst = str(feat.get("catalyst_type", "")).strip().lower()
        if catalyst not in FRESH_HARD_CATALYSTS:
            continue
        sentiment = str(feat.get("sentiment", "")).strip().lower()
        if sentiment not in {"bullish", "positive"}:
            continue
        ts = _parse_feature_ts(feat.get("ts"))
        if ts is None:
            continue
        age = as_of - ts
        if timedelta(hours=24) < age <= timedelta(days=3):
            return True
    return False


def _has_fresh_directional_hard_catalyst(
    output: PredictionOutput, features: list[dict[str, Any]], as_of: datetime
) -> bool:
    """Return true when a fresh hard catalyst supports the raw direction."""
    expected_sentiments = (
        {"bullish", "positive"} if output.direction == "up" else {"bearish", "negative"}
    )
    for feat in features:
        catalyst = str(feat.get("catalyst_type", "")).strip().lower()
        if catalyst not in FRESH_HARD_CATALYSTS:
            continue
        sentiment = str(feat.get("sentiment", "")).strip().lower()
        if sentiment not in expected_sentiments:
            continue
        ts = _parse_feature_ts(feat.get("ts"))
        if ts is None:
            continue
        age = as_of - ts
        if timedelta(0) <= age <= timedelta(hours=24):
            return True
    return False


# Exogenous geopolitical/macro-shock catalysts the predictor otherwise treats as
# passive "backdrop". When one is fresh AND risk-on, a relief rally can run over
# mild down-fades issued on "no fresh company-specific hard catalyst" -- the
# 2026-06-12 Iran-peace semiconductor rally (0981.HK, 688981.SS) is the case.
GEOPOLITICAL_CATALYST_LEXICON: tuple[str, ...] = (
    "iran", "hormuz", "sanction", "tariff", "ceasefire", "opec",
    "geopolit", "israel", "strait", "peace deal", "russia", "ukraine",
)


def _has_active_geopolitical_riskon(
    features: list[dict[str, Any]], as_of: datetime
) -> bool:
    """True when a fresh (<=24h) feature is a bullish/risk-on geopolitical catalyst.

    Text-scan (not catalyst_type) so it is independent of the news-feature
    extractor's taxonomy, which does not emit a geopolitical class.
    """
    for feat in features:
        text = (
            str(feat.get("summary", "")) + " " + str(feat.get("title", ""))
        ).lower()
        if not any(kw in text for kw in GEOPOLITICAL_CATALYST_LEXICON):
            continue
        sentiment = str(feat.get("sentiment", "")).strip().lower()
        if sentiment not in {"bullish", "positive", "risk-on"}:
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
    sorted_returns = sorted(returns.values())
    midpoint = len(sorted_returns) // 2
    if len(sorted_returns) % 2:
        median_return = sorted_returns[midpoint]
    else:
        median_return = (
            sorted_returns[midpoint - 1] + sorted_returns[midpoint]
        ) / 2
    leader_positive = any(
        returns.get(leader, -1.0) >= 0 for leader in AI_INFRA_SECTOR_LEADERS
    )
    return (
        positive_share >= AI_INFRA_BREADTH_THRESHOLD
        and median_return > AI_INFRA_MEDIAN_RETURN_THRESHOLD
        and leader_positive
    )


def _text_mentions_ai_infra(output: PredictionOutput) -> bool:
    text = " ".join(
        [output.rationale, *[str(f) for f in output.key_factors]]
    ).lower()
    return any(keyword in text for keyword in AI_INFRA_KEYWORDS)


def _text_mentions_peer_readthrough(output: PredictionOutput) -> bool:
    text = " ".join(
        [output.rationale, *[str(f) for f in output.key_factors]]
    ).lower()
    return any(keyword in text for keyword in PEER_READTHROUGH_KEYWORDS)


def _has_stale_or_thematic_news(features: list[dict[str, Any]]) -> bool:
    for feat in features:
        novelty = str(feat.get("novelty", "")).strip().lower()
        catalyst = str(feat.get("catalyst_type", "")).strip().lower()
        summary = str(feat.get("summary", "")).strip().lower()
        if novelty in {"low", "stale", "repeated", "thematic"}:
            return True
        if catalyst in {"theme", "thematic", "analyst", "sector"} and any(
            word in summary for word in ("repeat", "theme", "sector", "narrative")
        ):
            return True
    return False


def _has_confirming_volume(prices: list[dict[str, Any]]) -> bool:
    if len(prices) < 3:
        return False
    latest = prices[-1]
    prior = prices[-2]
    try:
        latest_volume = float(latest["v"])
        prior_volumes = [float(bar["v"]) for bar in prices[-6:-1]]
        latest_close = float(latest["c"])
        prior_close = float(prior["c"])
    except (KeyError, TypeError, ValueError):
        return False
    if not prior_volumes or latest_close <= prior_close:
        return False
    avg_prior_volume = sum(prior_volumes) / len(prior_volumes)
    return avg_prior_volume > 0 and latest_volume >= avg_prior_volume * CONFIRMING_VOLUME_MULTIPLE


def _has_confirming_down_volume(prices: list[dict[str, Any]]) -> bool:
    if len(prices) < 3:
        return False
    latest = prices[-1]
    prior = prices[-2]
    try:
        latest_volume = float(latest["v"])
        prior_volumes = [float(bar["v"]) for bar in prices[-6:-1]]
        latest_close = float(latest["c"])
        prior_close = float(prior["c"])
    except (KeyError, TypeError, ValueError):
        return False
    if not prior_volumes or latest_close >= prior_close:
        return False
    avg_prior_volume = sum(prior_volumes) / len(prior_volumes)
    return avg_prior_volume > 0 and latest_volume >= avg_prior_volume * CONFIRMING_VOLUME_MULTIPLE


def _ai_infra_leaders_negative(conn: sqlite3.Connection) -> bool:
    negative = 0
    observed = 0
    for leader in AI_INFRA_SECTOR_LEADERS:
        ret = _latest_return_for_ticker(leader, conn)
        if ret is None:
            continue
        observed += 1
        if ret < 0:
            negative += 1
    return observed >= 2 and negative >= 2


def _preserve_supported_calibration_direction(
    ticker: str,
    output: PredictionOutput,
    features: list[dict[str, Any]],
    calibrated_prob: float,
    conn: sqlite3.Connection,
    *,
    as_of: datetime | None = None,
) -> float:
    """Block calibration from crossing 0.50 on evidence-supported raw calls."""
    raw_prob = output.prob_up
    raw_up = raw_prob >= CALIBRATION_NEUTRAL_PROB
    calibrated_up = calibrated_prob >= CALIBRATION_NEUTRAL_PROB
    if raw_up == calibrated_up:
        return calibrated_prob

    now = as_of or datetime.now(timezone.utc)
    support = _has_fresh_directional_hard_catalyst(output, features, now)
    if (
        not support
        and raw_up
        and (ticker.upper() in AI_INFRA_TICKERS or _text_mentions_ai_infra(output))
    ):
        support = _ai_infra_breadth_positive(conn)
    if not support:
        return calibrated_prob

    logger.info(
        "calibration direction guard for %s: raw=%.2f calibrated=%.2f -> %.2f",
        ticker.upper(), raw_prob, calibrated_prob, CALIBRATION_NEUTRAL_PROB,
    )
    return CALIBRATION_NEUTRAL_PROB


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
    now = as_of or datetime.now(timezone.utc)
    ai_infra_context = ticker_upper in AI_INFRA_TICKERS or _text_mentions_ai_infra(output)
    semi_peer_context = (
        ticker_upper in SEMI_MEMORY_TICKERS
        or ai_infra_context
        or _text_mentions_peer_readthrough(output)
    )
    fresh_hard_catalyst = _has_fresh_hard_catalyst(features, now)
    active_geo_riskon = _has_active_geopolitical_riskon(features, now)

    # A fresh risk-on geopolitical catalyst (e.g. an Iran-peace relief rally) is a
    # real directional signal, not backdrop: do not cap up-calls into it, and floor
    # mild down-fades issued without a fresh negative hard catalyst toward neutral.
    if (
        active_geo_riskon
        and output.direction == "down"
        and output.prob_up < CALIBRATION_NEUTRAL_PROB
        and not _has_fresh_negative_hard_catalyst(features, now)
    ):
        logger.info(
            "geopolitical risk-on down-call floor for %s: %.2f -> %.2f",
            ticker_upper, output.prob_up, CALIBRATION_NEUTRAL_PROB,
        )
        output.prob_up = CALIBRATION_NEUTRAL_PROB
        output.confidence = min(output.confidence, CALIBRATION_NEUTRAL_PROB)
        output.expected_return_bps = max(output.expected_return_bps, 0)
        output.rationale = (
            output.rationale.rstrip()
            + " Probability floored to neutral: a fresh risk-on geopolitical"
            " catalyst is active and there is no fresh negative hard catalyst, so"
            " a mild down-fade into a relief rally is not supported."
        )
        return output

    if (
        output.direction == "up"
        and output.prob_up > STALE_UPCALL_CAP
        and not fresh_hard_catalyst
        and not active_geo_riskon
        and _has_stale_or_thematic_news(features)
    ):
        supported_exception = (
            ai_infra_context
            and conn is not None
            and _ai_infra_breadth_positive(conn)
            and _has_confirming_volume(prices)
        )
        if not supported_exception:
            logger.info(
                "stale up-call cap for %s: %.2f -> %.2f",
                ticker_upper, output.prob_up, STALE_UPCALL_CAP,
            )
            output.prob_up = STALE_UPCALL_CAP
            output.confidence = min(output.confidence, STALE_UPCALL_CAP)
            output.expected_return_bps = min(output.expected_return_bps, 0)
            output.rationale = (
                output.rationale.rstrip()
                + " Probability capped because the bullish setup is stale/thematic "
                "with no fresh hard catalyst and lacks both supportive breadth and "
                "confirming volume."
            )
            return output

    if (
        output.direction == "down"
        and PEER_READTHROUGH_DOWNCALL_MIN <= output.prob_up < CALIBRATION_NEUTRAL_PROB
        and semi_peer_context
        and _text_mentions_peer_readthrough(output)
        and not _has_fresh_negative_hard_catalyst(features, now)
        and not _has_confirming_down_volume(prices)
        and not (conn is not None and _ai_infra_leaders_negative(conn))
    ):
        logger.info(
            "peer read-through down-call floor for %s: %.2f -> %.2f",
            ticker_upper, output.prob_up, PEER_READTHROUGH_DOWNCALL_FLOOR,
        )
        output.prob_up = PEER_READTHROUGH_DOWNCALL_FLOOR
        output.confidence = min(output.confidence, PEER_READTHROUGH_DOWNCALL_FLOOR)
        output.expected_return_bps = max(output.expected_return_bps, 0)
        output.rationale = (
            output.rationale.rstrip()
            + " Probability floored to neutral because the down-call relies on "
            "single-peer read-through without a fresh negative hard catalyst, "
            "confirming downside volume, or multiple sector leaders moving down."
        )
        return output

    if not ai_infra_context:
        return output

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
        output.expected_return_bps = max(output.expected_return_bps, 0)
        output.rationale = (
            output.rationale.rstrip()
            + " Probability floored because AI/semis peer breadth is positive "
            "and there is no fresh negative hard catalyst."
        )
        return output

    if output.direction != "up":
        return output

    recent_ret = _recent_return(prices, bars=2)
    negative_tape = recent_ret is not None and recent_ret < 0
    aged_positive_hard_catalyst = _has_aged_positive_hard_catalyst(features, now)

    cap: float | None = None
    reason: str | None = None
    if active_geo_riskon:
        # Fresh risk-on geopolitical catalyst supports the up-call -- do not cap.
        cap = None
    elif (
        aged_positive_hard_catalyst
        and not fresh_hard_catalyst
        and recent_ret is not None
        and recent_ret > POST_CATALYST_EXHAUSTION_RETURN_THRESHOLD
    ):
        cap = POST_CATALYST_EXHAUSTION_CAP
        reason = "day-2/day-3 post-catalyst exhaustion after an 8%+ two-day reaction"
    elif negative_tape and not fresh_hard_catalyst:
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
    ticker: str, conn: sqlite3.Connection, *, weekly: bool = False
) -> PredictionResult:
    """Run a full single-ticker prediction cycle.

    weekly=True makes a 1-week-horizon call (predict Sunday, due the coming
    Saturday) instead of the default next-trading-day call.
    """
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

    # Knowledge base: feed our own prior deep research into the prediction so the
    # analysis we generated actually informs the quantitative call. Direct ticker
    # matches PLUS semantic (thematic) matches against the current news embedding,
    # so a relevant dive that never named the ticker still surfaces.
    from stock.knowledge import format_knowledge_block, gather_knowledge
    knowledge_items = gather_knowledge(
        conn, ticker, query_embedding=query_embedding,
    )
    knowledge_block = format_knowledge_block(knowledge_items)

    # H1 context DAG: shared blocks (macro regime, market internals, AI-infra
    # breadth) resolve through memoized nodes -- rendered once per batch, not
    # once per ticker -- and their content hashes go into the manifest below so
    # grading can attribute outcomes to specific context versions.
    from stock.context_graph import get_block
    macro_block, macro_hash = get_block(conn, "macro")
    internals_block, internals_hash = get_block(conn, "market_internals")
    breadth_block, breadth_hash = get_block(conn, "sector_breadth")

    # Plan H §5 auto-improve lever: the grading loop records ablation verdicts;
    # if the market-tape block (internals + breadth + live quote + earnings) is
    # measuring net-negative on hit rate, skip it here. Self-correcting: gated-off
    # predictions are still scored, so if removing it does not help the next
    # grading cycle re-enables it. Gov-trades is a separate signal, never gated.
    from stock.ablation import disabled_blocks
    from stock.ingest.gov_trades import format_gov_block
    from stock.market_context import format_earnings_line, format_live_quote_line
    tape_disabled = "market_tape_h0" in disabled_blocks(conn)

    market_parts: list[str] = []
    if tape_disabled:
        market_parts.append(
            "(market-tape block auto-disabled by the ablation loop: it measured"
            " net-negative on hit rate. It auto-reverts if removal does not help.)"
        )
    else:
        market_parts += [
            internals_block,
            breadth_block,
            format_live_quote_line(ticker, conn),
            format_earnings_line(ticker),
        ]
    gov_block = format_gov_block(ticker, conn)
    if gov_block:
        market_parts.append(gov_block)
    market_context = "\n".join(market_parts)
    context_manifest = {
        "macro": macro_hash,
        "market_internals": "disabled" if tape_disabled else internals_hash,
        "sector_breadth": "disabled" if tape_disabled else breadth_hash,
        "market_tape_disabled": tape_disabled,
    }

    user_message = user_template.format(
        ticker=ticker,
        horizon="1 trading week (close-to-close)" if weekly else "1 trading day",
        feature_summary=feature_summary,
        price_count=len(prices),
        price_history=price_history,
        retrieved_cases=retrieved_text,
        knowledge_block=knowledge_block,
        macro_block=macro_block,
        market_context=market_context,
    )

    # Select strategy arm via Thompson sampling bandit. The arm's `name` is
    # still recorded on the prediction row (so future bandit work can attribute
    # reward), but the provider/model fields are ignored: every core LLM call
    # routes through get_core_client() per the AI_INDEX convention, which
    # honors the operator's CORE_LLM_BACKEND selection (codex_cli with
    # claude_cli fallback).
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
    calibrated_prob = _preserve_supported_calibration_direction(
        ticker, output, features, calibrated_prob, conn
    )

    # Compute timestamps. Weekly predictions are due the coming Saturday; daily
    # ones the next trading-day close.
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    horizon_minutes = WEEKLY_HORIZON_MINUTES if weekly else DEFAULT_HORIZON_MINUTES
    due_at = (
        compute_weekly_due_at(now) if weekly
        else compute_due_at(now, DEFAULT_HORIZON_MINUTES)
    )

    # Build context JSON for auditing. knowledge_item_count instruments the
    # knowledge base for A/B: compare hit rate of predictions with vs without
    # research present (count>0) to measure whether the research is predictive.
    feature_context = json.dumps({
        "features": features,
        "prices": prices,
        "retrieved_case_ids": retrieved_ids,
        "knowledge_item_count": len(knowledge_items),
        "knowledge_direct": sum(1 for k in knowledge_items if k.via == "direct"),
        "knowledge_thematic": sum(1 for k in knowledge_items if k.via == "semantic"),
        "context_manifest": context_manifest,
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
            horizon_minutes,
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
