"""stock.features -- LLM-based feature extraction for news articles."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from stock.models import (
    ChatMessage,
    CostCeilingError,
    get_core_client,
    get_core_model,
    parse_llm_json,
)

logger = logging.getLogger(__name__)

FEATURE_PROMPT_PATH: str = "prompts/feature.txt"
MAX_BODY_CHARS: int = 5000


class NewsFeatures(BaseModel):
    """Structured features extracted from a single news article."""

    sentiment: str
    novelty: str
    catalyst_type: str
    time_sensitivity: str
    summary: str


class FeatureResult(BaseModel):
    """Result of extracting features for one news item."""

    news_id: int
    features: NewsFeatures


@lru_cache(maxsize=1)
def load_feature_prompt() -> str:
    """Load the feature extraction prompt template from disk."""
    path = Path(FEATURE_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Feature prompt not found at {FEATURE_PROMPT_PATH}")
    return path.read_text(encoding="utf-8")


def get_unfeatured_news(
    ticker: str, conn: sqlite3.Connection
) -> list[tuple[int, str, str, str]]:
    """Return news items that do not yet have extracted features."""
    rows = conn.execute(
        "SELECT n.id, n.title, n.body, n.ticker FROM news n"
        " LEFT JOIN features f ON n.id = f.news_id"
        " WHERE n.ticker = ? AND f.id IS NULL ORDER BY n.ts DESC",
        (ticker,),
    ).fetchall()
    return [(int(row[0]), str(row[1]), str(row[2]), str(row[3])) for row in rows]


def extract_single(
    news_id: int,
    title: str,
    body: str,
    ticker: str,
    conn: sqlite3.Connection,
) -> FeatureResult:
    """Extract structured features for a single news article via LLM."""
    # Load and format the prompt template
    template = load_feature_prompt()
    truncated_body = body[:MAX_BODY_CHARS]
    prompt = template.format(ticker=ticker, title=title, body=truncated_body)

    # Call the active core backend (claude_cli or minimax via CORE_LLM_BACKEND)
    messages: list[ChatMessage] = [{"role": "user", "content": prompt}]
    client = get_core_client()
    model = get_core_model()
    response = client.chat(
        messages=messages,
        model=model,
        max_tokens=300,
        conn=conn,
        caller="features.extract_single",
        cached_system=(
            "You are a financial news feature extraction engine. "
            "Always respond with valid JSON only. "
            "Never include markdown code fences or commentary."
        ),
    )

    # Parse and validate the JSON response
    parsed = parse_llm_json(response.content)
    features = NewsFeatures(**parsed)

    # Store in the features table
    conn.execute(
        "INSERT INTO features (news_id, json, model, ts) VALUES (?, ?, ?, ?)",
        (
            news_id,
            json.dumps(parsed),
            model,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()

    return FeatureResult(news_id=news_id, features=features)


def extract_features(
    ticker: str, conn: sqlite3.Connection
) -> list[FeatureResult]:
    """Extract features for all unfeatured news items, stopping on cost ceiling."""
    unfeatured = get_unfeatured_news(ticker, conn)
    results: list[FeatureResult] = []

    for news_id, title, body, tick in unfeatured:
        try:
            result = extract_single(news_id, title, body, tick, conn)
            results.append(result)
        except CostCeilingError:
            logger.warning(
                "Cost ceiling reached during feature extraction, returning partial results"
            )
            break
        except json.JSONDecodeError as exc:
            # MiniMax occasionally returns empty or truncated content even on 200 OK.
            # Skip just this news item rather than failing the whole ticker.
            logger.warning(
                "Skipping news_id=%s: MiniMax returned unparseable JSON (%s)",
                news_id, exc,
            )
            continue
        except Exception:
            logger.exception(
                "Skipping news_id=%s: unexpected feature-extraction failure", news_id,
            )
            continue

    return results
