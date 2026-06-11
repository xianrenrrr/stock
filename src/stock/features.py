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
    get_utility_client,
    get_utility_model,
    parse_llm_json,
)

logger = logging.getLogger(__name__)

FEATURE_PROMPT_PATH: str = "prompts/feature.txt"
FEATURE_BATCH_PROMPT_PATH: str = "prompts/feature_batch.txt"
MAX_BODY_CHARS: int = 5000
# Batched extraction (quota lever): one LLM call per BATCH_SIZE articles
# instead of one per article (~430 calls/day -> ~60). Bodies get a tighter
# cap in batch mode so 8 articles still fit comfortably in one prompt.
BATCH_SIZE: int = 8
MAX_BODY_CHARS_BATCH: int = 2500
BATCH_TOKENS_BASE: int = 200
BATCH_TOKENS_PER_ITEM: int = 150


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


@lru_cache(maxsize=1)
def load_feature_batch_prompt() -> str:
    """Load the batched feature extraction prompt template from disk."""
    path = Path(FEATURE_BATCH_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Batch feature prompt not found at {FEATURE_BATCH_PROMPT_PATH}")
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

    # Feature extraction is a cheap, high-frequency classifier -> fast utility
    # lane (Claude haiku) instead of the slow codex core backend.
    messages: list[ChatMessage] = [{"role": "user", "content": prompt}]
    client = get_utility_client()
    model = get_utility_model()
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


def _store_features(
    news_id: int, parsed: dict, model: str, conn: sqlite3.Connection
) -> FeatureResult:
    features = NewsFeatures(**parsed)
    conn.execute(
        "INSERT INTO features (news_id, json, model, ts) VALUES (?, ?, ?, ?)",
        (news_id, json.dumps(parsed), model, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return FeatureResult(news_id=news_id, features=features)


def extract_batch(
    items: list[tuple[int, str, str, str]],
    conn: sqlite3.Connection,
) -> list[FeatureResult]:
    """Extract features for up to BATCH_SIZE articles in ONE LLM call.

    Returns results for the ids the model answered; ids it skipped stay
    unfeatured and are retried on the next ingest cycle. Raises on transport
    or whole-response parse failure so the caller can fall back to singles.
    """
    template = load_feature_batch_prompt()
    blocks: list[str] = []
    for news_id, title, body, ticker in items:
        blocks.append(
            f"### Article id={news_id} (ticker {ticker})\n"
            f"Title: {title}\n"
            f"Text:\n{body[:MAX_BODY_CHARS_BATCH]}"
        )
    prompt = template.format(articles="\n\n".join(blocks))

    messages: list[ChatMessage] = [{"role": "user", "content": prompt}]
    client = get_utility_client()
    model = get_utility_model()
    response = client.chat(
        messages=messages,
        model=model,
        max_tokens=BATCH_TOKENS_BASE + BATCH_TOKENS_PER_ITEM * len(items),
        conn=conn,
        caller="features.extract_batch",
        cached_system=(
            "You are a financial news feature extraction engine. "
            "Always respond with valid JSON only. "
            "Never include markdown code fences or commentary."
        ),
    )

    parsed = parse_llm_json(response.content)
    entries = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(entries, list):
        raise json.JSONDecodeError("batch response missing 'items' array", "", 0)

    valid_ids = {news_id for news_id, _t, _b, _tk in items}
    results: list[FeatureResult] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            news_id = int(entry.pop("id"))
        except (KeyError, TypeError, ValueError):
            continue
        if news_id not in valid_ids:
            logger.warning("batch features: model invented id %s, ignoring", news_id)
            continue
        try:
            results.append(_store_features(news_id, entry, model, conn))
        except Exception:  # noqa: BLE001 -- one bad entry must not sink the batch
            logger.exception("batch features: bad entry for news_id=%s", news_id)
    missing = valid_ids - {r.news_id for r in results}
    if missing:
        logger.warning(
            "batch features: %d/%d articles unanswered, will retry next cycle",
            len(missing), len(items),
        )
    return results


def extract_features(
    ticker: str, conn: sqlite3.Connection
) -> list[FeatureResult]:
    """Extract features for all unfeatured news, batched, stopping on cost ceiling.

    Articles are processed BATCH_SIZE per LLM call; if a batch response is
    unparseable the batch falls back to per-article calls so a single bad
    response cannot strand a whole cycle's news.
    """
    unfeatured = get_unfeatured_news(ticker, conn)
    results: list[FeatureResult] = []

    for start in range(0, len(unfeatured), BATCH_SIZE):
        chunk = unfeatured[start:start + BATCH_SIZE]
        if len(chunk) > 1:
            try:
                results.extend(extract_batch(chunk, conn))
                continue
            except CostCeilingError:
                logger.warning(
                    "Cost ceiling reached during feature extraction, returning partial results"
                )
                break
            except Exception as exc:  # noqa: BLE001 -- fall back to singles
                logger.warning(
                    "batch feature extraction failed (%s); falling back to singles", exc,
                )

        for news_id, title, body, tick in chunk:
            try:
                results.append(extract_single(news_id, title, body, tick, conn))
            except CostCeilingError:
                logger.warning(
                    "Cost ceiling reached during feature extraction, returning partial results"
                )
                return results
            except json.JSONDecodeError as exc:
                # LLMs can occasionally return empty or truncated content.
                # Skip just this news item rather than failing the whole ticker.
                logger.warning(
                    "Skipping news_id=%s: feature LLM returned unparseable JSON (%s)",
                    news_id, exc,
                )
                continue
            except Exception:
                logger.exception(
                    "Skipping news_id=%s: unexpected feature-extraction failure", news_id,
                )
                continue

    return results
