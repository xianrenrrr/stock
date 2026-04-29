"""stock.memory -- embedding and retrieval for prediction cases."""
from __future__ import annotations

import json
import logging
import sqlite3
import struct
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

EMBEDDING_DIM: int = 384
EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
DEFAULT_K: int = 5
RETRIEVAL_OVERSAMPLE: int = 5

_model: Any = None


class RetrievedCase(BaseModel):
    """A past prediction case retrieved by vector similarity."""

    prediction_id: int
    ticker: str
    direction: str
    prob_up: float
    confidence: float
    rationale: str
    actual_return: float
    direction_hit: bool
    brier: float
    feature_summary: str
    similarity: float


def _get_model() -> Any:
    """Lazy-load the SentenceTransformer model on first use."""
    global _model  # noqa: PLW0603
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def embed(text: str) -> list[float]:
    """Encode text into a normalized 384-dim embedding vector."""
    if not text.strip():
        raise ValueError("Cannot embed empty text")

    model = _get_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()  # type: ignore[no-any-return]


def _serialize_embedding(embedding: list[float]) -> bytes:
    """Convert a float list to raw float32 bytes for sqlite-vec."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def _extract_feature_text(feature_json: str | None) -> str:
    """Parse feature_context_json into a readable text summary."""
    if feature_json is None:
        return "No feature context available."

    # Parse the JSON string
    try:
        data: dict[str, Any] = json.loads(feature_json)
    except (json.JSONDecodeError, TypeError):
        return "Invalid feature context."

    # Extract features list from the context
    features: list[dict[str, Any]] = data.get("features", [])
    if not features:
        return "No features available."

    # Build a readable summary from up to 5 features
    parts: list[str] = []
    for feat in features[:5]:
        title = feat.get("title", "untitled")
        sentiment = feat.get("sentiment", "unknown")
        catalyst = feat.get("catalyst_type", "unknown")
        summary = feat.get("summary", "")
        parts.append(f"{title}: sentiment={sentiment}, catalyst={catalyst}. {summary}")

    return " | ".join(parts)


def index_outcome(prediction_id: int, conn: sqlite3.Connection) -> None:
    """Embed a scored prediction case and store in the vec0 table."""
    # Load prediction row
    pred_row = conn.execute(
        "SELECT ticker, direction, prob_up, confidence, rationale, feature_context_json"
        " FROM predictions WHERE id = ?",
        (prediction_id,),
    ).fetchone()
    if pred_row is None:
        raise ValueError(f"Prediction {prediction_id} not found")

    ticker, direction, prob_up, confidence, rationale, feature_json = pred_row

    # Load outcome row
    outcome_row = conn.execute(
        "SELECT actual_return, direction_hit FROM outcomes WHERE prediction_id = ?",
        (prediction_id,),
    ).fetchone()
    if outcome_row is None:
        raise ValueError(f"Outcome for prediction {prediction_id} not found")

    actual_return, direction_hit = outcome_row

    # Build text representation for embedding
    feature_text = _extract_feature_text(feature_json)
    case_text = (
        f"Ticker: {ticker}. {feature_text} "
        f"Predicted {direction} with prob_up={prob_up:.2f}, confidence={confidence:.2f}. "
        f"Rationale: {rationale}. "
        f"Outcome: return={actual_return:.4f}, hit={'yes' if direction_hit else 'no'}."
    )

    # Embed and store (delete first for idempotency — vec0 does not support OR REPLACE)
    vector = embed(case_text)
    blob = _serialize_embedding(vector)
    conn.execute(
        "DELETE FROM case_embeddings WHERE prediction_id = ?", (prediction_id,)
    )
    conn.execute(
        "INSERT INTO case_embeddings (prediction_id, embedding) VALUES (?, ?)",
        (prediction_id, blob),
    )
    conn.commit()
    logger.info("Indexed outcome for prediction %d", prediction_id)


def retrieve(
    ticker: str,
    query_embedding: list[float],
    conn: sqlite3.Connection,
    k: int = DEFAULT_K,
) -> list[RetrievedCase]:
    """Find the K most similar past cases for a ticker via sqlite-vec."""
    # Serialize query embedding for vec0
    query_blob = _serialize_embedding(query_embedding)
    fetch_count = max(k * RETRIEVAL_OVERSAMPLE, 25)

    # Over-fetch from vec0 (no ticker filter in virtual table)
    vec_rows = conn.execute(
        "SELECT prediction_id, distance FROM case_embeddings"
        " WHERE embedding MATCH ? AND k = ?",
        (query_blob, fetch_count),
    ).fetchall()

    if not vec_rows:
        return []

    # Build distance lookup
    distances: dict[int, float] = {row[0]: row[1] for row in vec_rows}
    pred_ids = list(distances.keys())

    # Filter by ticker with a single query
    placeholders = ",".join("?" * len(pred_ids))
    detail_rows = conn.execute(
        f"SELECT p.id, p.ticker, p.direction, p.prob_up, p.confidence,"
        f"       p.rationale, p.feature_context_json,"
        f"       o.actual_return, o.direction_hit, o.brier"
        f" FROM predictions p"
        f" JOIN outcomes o ON p.id = o.prediction_id"
        f" WHERE p.id IN ({placeholders}) AND p.ticker = ?",
        (*pred_ids, ticker),
    ).fetchall()

    # Build result objects
    cases: list[RetrievedCase] = []
    for row in detail_rows:
        pid = row[0]
        distance = distances[pid]
        feature_text = _extract_feature_text(row[6])
        cases.append(RetrievedCase(
            prediction_id=pid,
            ticker=row[1],
            direction=row[2],
            prob_up=row[3],
            confidence=row[4],
            rationale=row[5],
            actual_return=row[7],
            direction_hit=bool(row[8]),
            brier=row[9],
            feature_summary=feature_text,
            similarity=max(0.0, 1.0 - distance),
        ))

    # Sort by similarity descending, return top k
    cases.sort(key=lambda c: c.similarity, reverse=True)
    return cases[:k]


def format_retrieved_cases(cases: list[RetrievedCase]) -> str:
    """Format retrieved cases into a text block for prompt injection."""
    if not cases:
        return "No historical cases available yet."

    blocks: list[str] = []
    for idx, case in enumerate(cases, 1):
        outcome_label = "correct" if case.direction_hit else "wrong"
        block = (
            f"Case {idx} (similarity: {case.similarity:.2f}):\n"
            f"  Context: {case.feature_summary[:200]}\n"
            f"  Predicted: {case.direction} (prob_up={case.prob_up:.2f})\n"
            f"  Outcome: {case.actual_return:+.2%} return ({outcome_label})\n"
            f"  Rationale: {case.rationale[:150]}"
        )
        blocks.append(block)

    return "\n\n".join(blocks)
