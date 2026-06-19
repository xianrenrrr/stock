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


# --- §5 auto-improve loop wiring ---------------------------------------------


def _scored(conn, *, knowledge, hit, created_days_ago=1, manifest=None):
    import json
    from datetime import datetime, timedelta, timezone
    created = (datetime.now(timezone.utc) - timedelta(days=created_days_ago)).isoformat()
    fc = {"knowledge_item_count": knowledge}
    if manifest is not None:
        fc["context_manifest"] = manifest
    cur = conn.execute(
        "INSERT INTO predictions (ticker, horizon_minutes, direction, prob_up,"
        " expected_return_bps, confidence, rationale, key_factors_json,"
        " model_used, created_at, due_at, feature_context_json)"
        " VALUES ('NVDA',390,'up',0.6,50,0.6,'r','[]','m',?,?,?)",
        (created, created, json.dumps(fc)),
    )
    conn.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, 0.01, ?, 0.2, ?)",
        (cur.lastrowid, 1 if hit else 0, created),
    )
    conn.commit()


def test_ablation_verdict_cut_and_keep(mem_db):
    from stock import ablation
    # market_tape_h0 ships 2026-06-11; make WITH (recent) hurt vs WITHOUT (old).
    # 50 recent predictions all miss; 50 old predictions all hit -> tape hurts big.
    for _ in range(50):
        _scored(mem_db, knowledge=0, hit=False, created_days_ago=1)   # after ship
    for _ in range(50):
        _scored(mem_db, knowledge=0, hit=True, created_days_ago=40)   # before ship
    verdicts = {v["signal"]: v for v in ablation.ablation_verdicts(mem_db, days=60)}
    tape = verdicts["market_tape_h0"]
    assert tape["verdict"] == "cut"
    assert tape["delta_pp"] <= ablation.HURT_THRESHOLD_PP


def test_disabled_blocks_reads_latest_recorded_verdict(mem_db):
    from datetime import datetime, timezone

    from stock import ablation
    now = datetime.now(timezone.utc).isoformat()
    # Older 'keep' then newer 'cut' -> the newer one wins -> disabled.
    mem_db.execute(
        "INSERT INTO signal_ablation (signal, delta_pp, n_with, n_without,"
        " actionable, verdict, recorded_at) VALUES"
        " ('market_tape_h0', 2.0, 50, 50, 1, 'keep', '2026-06-01T00:00:00+00:00')",
    )
    mem_db.execute(
        "INSERT INTO signal_ablation (signal, delta_pp, n_with, n_without,"
        " actionable, verdict, recorded_at) VALUES"
        " ('market_tape_h0', -5.0, 50, 50, 1, 'cut', ?)",
        (now,),
    )
    mem_db.commit()
    assert ablation.disabled_blocks(mem_db) == {"market_tape_h0"}


def test_only_gateable_blocks_can_be_disabled(mem_db):
    from datetime import datetime, timezone

    from stock import ablation
    # knowledge_base is NOT gateable even if a 'cut' verdict is recorded.
    mem_db.execute(
        "INSERT INTO signal_ablation (signal, delta_pp, n_with, n_without,"
        " actionable, verdict, recorded_at) VALUES"
        " ('knowledge_base', -9.0, 99, 99, 1, 'cut', ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    mem_db.commit()
    assert ablation.disabled_blocks(mem_db) == set()


def test_insufficient_sample_is_not_actionable(mem_db):
    from stock import ablation
    for _ in range(5):
        _scored(mem_db, knowledge=2, hit=True)
    for _ in range(5):
        _scored(mem_db, knowledge=0, hit=False)
    v = {x["signal"]: x for x in ablation.ablation_verdicts(mem_db, days=30)}
    assert v["knowledge_base"]["verdict"] == "insufficient"  # n<40 each side


def test_record_and_format_verdicts(mem_db):
    from stock import ablation
    verdicts = [
        {"signal": "market_tape_h0", "delta_pp": -5.0, "n_with": 50,
         "n_without": 50, "actionable": True, "verdict": "cut"},
        {"signal": "knowledge_base", "delta_pp": 2.0, "n_with": 60,
         "n_without": 60, "actionable": True, "verdict": "keep"},
    ]
    ablation.record_verdicts(mem_db, verdicts)
    assert ablation.disabled_blocks(mem_db) == {"market_tape_h0"}
    block = ablation.format_ablation_verdict_block(verdicts, {"market_tape_h0"})
    assert "AUTO-DISABLED" in block and "ACTION TAKEN" in block
