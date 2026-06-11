"""tests.test_ablation -- signal with/without measurement."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from stock.ablation import compute_ablation, format_ablation


def _scored_prediction(
    conn: sqlite3.Connection,
    *,
    knowledge_count: int,
    hit: bool,
    brier: float,
    manifest: bool = False,
) -> None:
    fc = {"knowledge_item_count": knowledge_count}
    if manifest:
        fc["context_manifest"] = {"macro": "abc123"}
    created = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    cursor = conn.execute(
        "INSERT INTO predictions (ticker, horizon_minutes, direction, prob_up,"
        " expected_return_bps, confidence, rationale, key_factors_json,"
        " model_used, created_at, due_at, feature_context_json)"
        " VALUES ('NVDA', 390, 'up', 0.6, 50, 0.6, 'r', '[]', 'm', ?, ?, ?)",
        (created, created, json.dumps(fc)),
    )
    conn.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit,"
        " brier, scored_at)"
        " VALUES (?, 0.01, ?, ?, ?)",
        (cursor.lastrowid, 1 if hit else 0, brier, created),
    )
    conn.commit()


def test_knowledge_split(mem_db: sqlite3.Connection) -> None:
    for _ in range(3):
        _scored_prediction(mem_db, knowledge_count=2, hit=True, brier=0.10)
    for _ in range(2):
        _scored_prediction(mem_db, knowledge_count=0, hit=False, brier=0.40)

    report = compute_ablation(mem_db, days=30)

    with_s, without_s = report["signals"]["knowledge_base"]
    assert with_s["n"] == 3 and with_s["hit_rate"] == 1.0
    assert without_s["n"] == 2 and without_s["hit_rate"] == 0.0
    assert report["total_scored"] == 5


def test_manifest_split_and_formatting(mem_db: sqlite3.Connection) -> None:
    _scored_prediction(mem_db, knowledge_count=0, hit=True, brier=0.2, manifest=True)
    _scored_prediction(mem_db, knowledge_count=0, hit=False, brier=0.3)

    report = compute_ablation(mem_db, days=30)
    text = format_ablation(report)

    with_s, _without = report["signals"]["context_dag_h1"]
    assert with_s["n"] == 1
    assert "small sample!" in text
    assert "knowledge_base" in text and "delta" in text


def test_empty_db(mem_db: sqlite3.Connection) -> None:
    report = compute_ablation(mem_db, days=30)
    assert report["total_scored"] == 0
    assert "n=0" in format_ablation(report)
