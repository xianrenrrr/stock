"""tests.test_thesis -- atomic claim extraction + post-hoc verification (F16)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock import thesis
from stock.thesis import (
    ThesisStats,
    compute_thesis_stats,
    extract_theses,
    format_thesis_block,
    list_for_prediction,
    verify_due_theses,
    verify_thesis,
)


def _insert_prediction(
    conn: sqlite3.Connection,
    *,
    ticker: str = "NVDA",
    direction: str = "up",
    prob_up: float = 0.78,
    rationale: str = "Earnings beat on AI revenue plus a guidance raise into year-end.",
    key_factors: list[str] | None = None,
    created_at: str = "2026-04-29T14:00:00+00:00",
    due_at: str = "2026-04-30T21:00:00+00:00",
) -> int:
    """Insert a minimal prediction row, return its id."""
    cursor = conn.execute(
        "INSERT INTO predictions ("
        "  ticker, horizon_minutes, direction, prob_up, confidence,"
        "  rationale, key_factors_json, model_used, created_at, due_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticker, 390, direction, prob_up, 0.7, rationale,
         json.dumps(key_factors or ["earnings_beat", "guidance_raise"]),
         "test-model", created_at, due_at),
    )
    conn.commit()
    return cursor.lastrowid or 0


def _insert_outcome(
    conn: sqlite3.Connection, *, prediction_id: int, actual_return: float = 0.04,
    direction_hit: int = 1,
) -> None:
    """Insert a scored outcome for the prediction."""
    conn.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (prediction_id, actual_return, direction_hit, 0.04,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def _patch_minimax(content: str, cost: float = 0.0005) -> object:
    """Build the (mock_get_client, mock_check_ceiling) patch context."""
    response = MagicMock(content=content, cost_usd=cost)
    client = MagicMock()
    client.chat.return_value = response
    return client


# -- extract_theses --


def test_extract_theses_persists_atomic_claims(mem_db: sqlite3.Connection) -> None:
    """Happy path: LLM returns 3 atomic claims, all rows are persisted with chain consistency."""
    pid = _insert_prediction(mem_db)
    fake_response = json.dumps({
        "claims": [
            {"claim_text": "NVDA will report an EPS beat in Q-after-2026-04-29",
             "claim_type": "catalyst", "verifiable_by": "earnings_release"},
            {"claim_text": "NVDA forward guidance will be raised vs prior",
             "claim_type": "catalyst", "verifiable_by": "earnings_release"},
            {"claim_text": "AI capex cycle is early-innings for HBM-exposed names",
             "claim_type": "supply_chain", "verifiable_by": "tier1_news_headline"},
        ],
        "chain_consistency": "supports",
        "chain_consistency_reason": "Both catalysts point to upside.",
    })
    client = _patch_minimax(fake_response)

    with (
        patch("stock.thesis.check_cost_ceiling"),
        patch("stock.thesis.get_core_client", return_value=client),
    ):
        rows = extract_theses(pid, mem_db)

    assert len(rows) == 3
    assert {r.claim_type for r in rows} == {"catalyst", "supply_chain"}
    assert all(r.chain_consistency == "supports" for r in rows)
    persisted = list_for_prediction(mem_db, pid)
    assert len(persisted) == 3


def test_extract_theses_idempotent(mem_db: sqlite3.Connection) -> None:
    """A second extract call returns existing rows without calling the LLM again."""
    pid = _insert_prediction(mem_db)
    fake_response = json.dumps({
        "claims": [{"claim_text": "x", "claim_type": "catalyst", "verifiable_by": "n"}],
        "chain_consistency": "neutral", "chain_consistency_reason": "",
    })
    client = _patch_minimax(fake_response)

    with (
        patch("stock.thesis.check_cost_ceiling"),
        patch("stock.thesis.get_core_client", return_value=client) as mock_factory,
    ):
        first = extract_theses(pid, mem_db)
        second = extract_theses(pid, mem_db)

    assert len(first) == 1
    assert len(second) == 1
    # Only one LLM call across both extracts
    assert mock_factory.call_count == 1


def test_extract_theses_invalid_claim_type_coerced(mem_db: sqlite3.Connection) -> None:
    """An LLM-emitted unknown claim_type is snapped to 'sentiment' rather than dropped."""
    pid = _insert_prediction(mem_db)
    fake_response = json.dumps({
        "claims": [{"claim_text": "x", "claim_type": "vibes", "verifiable_by": "n"}],
        "chain_consistency": "weird", "chain_consistency_reason": "",
    })
    client = _patch_minimax(fake_response)

    with (
        patch("stock.thesis.check_cost_ceiling"),
        patch("stock.thesis.get_core_client", return_value=client),
    ):
        rows = extract_theses(pid, mem_db)

    assert rows[0].claim_type == "sentiment"
    assert rows[0].chain_consistency == "neutral"


def test_extract_theses_json_parse_failure_returns_empty(
    mem_db: sqlite3.Connection,
) -> None:
    """LLM returns garbage -> we log + return [] rather than raising."""
    pid = _insert_prediction(mem_db)
    client = _patch_minimax("not json at all")
    with (
        patch("stock.thesis.check_cost_ceiling"),
        patch("stock.thesis.get_core_client", return_value=client),
    ):
        rows = extract_theses(pid, mem_db)
    assert rows == []


def test_extract_theses_caps_at_five(mem_db: sqlite3.Connection) -> None:
    """LLM returns 7 claims; only first 5 persisted (atomic-not-explosive guard)."""
    pid = _insert_prediction(mem_db)
    fake_response = json.dumps({
        "claims": [
            {"claim_text": f"claim {i}", "claim_type": "catalyst",
             "verifiable_by": "x"}
            for i in range(7)
        ],
        "chain_consistency": "neutral", "chain_consistency_reason": "",
    })
    client = _patch_minimax(fake_response)

    with (
        patch("stock.thesis.check_cost_ceiling"),
        patch("stock.thesis.get_core_client", return_value=client),
    ):
        rows = extract_theses(pid, mem_db)
    assert len(rows) == 5


# -- verify_thesis --


def _seed_thesis(
    conn: sqlite3.Connection, *, prediction_id: int, claim_type: str = "catalyst",
    claim_text: str = "Guidance will be raised vs prior",
) -> int:
    """Insert an ungraded thesis row tied to a prediction."""
    cursor = conn.execute(
        "INSERT INTO prediction_theses ("
        "  prediction_id, claim_text, claim_type, verifiable_by,"
        "  chain_consistency, created_at"
        ") VALUES (?, ?, ?, ?, 'neutral', ?)",
        (prediction_id, claim_text, claim_type, "earnings_release",
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return cursor.lastrowid or 0


def test_verify_thesis_supported(mem_db: sqlite3.Connection) -> None:
    """LLM returns 'supported' verdict, row updated with verdict+confidence+evidence."""
    pid = _insert_prediction(mem_db)
    _insert_outcome(mem_db, prediction_id=pid)
    tid = _seed_thesis(mem_db, prediction_id=pid)

    fake_response = json.dumps({
        "verdict": "supported",
        "confidence": 0.85,
        "evidence_text": "NVDA Q-end press release explicitly raised FY guidance.",
        "evidence_source": "news_headline",
    })
    client = _patch_minimax(fake_response)

    with (
        patch("stock.thesis.check_cost_ceiling"),
        patch("stock.thesis.get_core_client", return_value=client),
    ):
        result = verify_thesis(tid, mem_db)

    assert result is not None
    row = mem_db.execute(
        "SELECT verdict, confidence, evidence_source FROM prediction_theses WHERE id = ?",
        (tid,),
    ).fetchone()
    assert row[0] == "supported"
    assert row[1] == pytest.approx(0.85)
    assert row[2] == "news_headline"


def test_verify_thesis_skips_when_no_outcome(mem_db: sqlite3.Connection) -> None:
    """No outcome row -> verify returns None without calling the LLM."""
    pid = _insert_prediction(mem_db)
    tid = _seed_thesis(mem_db, prediction_id=pid)

    with (
        patch("stock.thesis.check_cost_ceiling"),
        patch("stock.thesis.get_core_client") as mock_factory,
    ):
        result = verify_thesis(tid, mem_db)

    assert result is None
    mock_factory.assert_not_called()


def test_verify_thesis_invalid_verdict_coerced(mem_db: sqlite3.Connection) -> None:
    """An LLM-emitted bogus verdict snaps to 'unverified' rather than crashing."""
    pid = _insert_prediction(mem_db)
    _insert_outcome(mem_db, prediction_id=pid)
    tid = _seed_thesis(mem_db, prediction_id=pid)

    fake_response = json.dumps({
        "verdict": "ABSOLUTELY_YES", "confidence": "high",
        "evidence_text": "x", "evidence_source": "news_headline",
    })
    client = _patch_minimax(fake_response)
    with (
        patch("stock.thesis.check_cost_ceiling"),
        patch("stock.thesis.get_core_client", return_value=client),
    ):
        verify_thesis(tid, mem_db)

    row = mem_db.execute(
        "SELECT verdict, confidence FROM prediction_theses WHERE id = ?", (tid,),
    ).fetchone()
    assert row[0] == "unverified"
    assert row[1] == 0.0  # bogus confidence string -> coerced to 0


def test_verify_due_theses_iterates_all_pending(mem_db: sqlite3.Connection) -> None:
    """verify_due_theses walks every ungraded thesis whose prediction is scored."""
    pid1 = _insert_prediction(mem_db, ticker="NVDA")
    _insert_outcome(mem_db, prediction_id=pid1)
    _seed_thesis(mem_db, prediction_id=pid1)
    _seed_thesis(mem_db, prediction_id=pid1, claim_type="supply_chain",
                 claim_text="HBM cycle still early")

    pid2 = _insert_prediction(mem_db, ticker="AMD")
    _insert_outcome(mem_db, prediction_id=pid2)
    _seed_thesis(mem_db, prediction_id=pid2)

    pid3 = _insert_prediction(mem_db, ticker="MSFT")  # unscored
    _seed_thesis(mem_db, prediction_id=pid3)

    fake_response = json.dumps({
        "verdict": "unverified", "confidence": 0.5,
        "evidence_text": "", "evidence_source": "none",
    })
    client = _patch_minimax(fake_response)

    with (
        patch("stock.thesis.check_cost_ceiling"),
        patch("stock.thesis.get_core_client", return_value=client),
    ):
        graded = verify_due_theses(mem_db)

    assert len(graded) == 3  # only the 3 scored ones, MSFT thesis stays ungraded
    pending = mem_db.execute(
        "SELECT COUNT(*) FROM prediction_theses WHERE verdict IS NULL"
    ).fetchone()[0]
    assert pending == 1  # the MSFT thesis


# -- compute_thesis_stats --


def test_compute_thesis_stats_right_direction_wrong_reason(
    mem_db: sqlite3.Connection,
) -> None:
    """A 'refuted' catalyst on a directional hit triggers the RDWR counter."""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=12)).isoformat()
    pid = _insert_prediction(mem_db, ticker="NVDA", created_at=recent)
    _insert_outcome(mem_db, prediction_id=pid, actual_return=0.04, direction_hit=1)

    # Two claims: one catalyst refuted, one sentiment supported
    mem_db.execute(
        "INSERT INTO prediction_theses (prediction_id, claim_text, claim_type,"
        " verdict, evidence_text, created_at) VALUES (?, ?, 'catalyst',"
        " 'refuted', ?, ?)",
        (pid, "Guidance will be raised", "actual support came from HBM demand", recent),
    )
    mem_db.execute(
        "INSERT INTO prediction_theses (prediction_id, claim_text, claim_type,"
        " verdict, created_at) VALUES (?, ?, 'sentiment', 'supported', ?)",
        (pid, "Sentiment improving", recent),
    )
    mem_db.commit()

    stats = compute_thesis_stats(mem_db, hours=36)
    assert stats.total == 2
    assert stats.refuted == 1
    assert stats.supported == 1
    assert stats.right_direction_wrong_reason == 1
    assert stats.right_direction_wrong_reason_examples
    assert f"prediction_id={pid}" in stats.right_direction_wrong_reason_examples[0]
    assert "NVDA up" in stats.right_direction_wrong_reason_examples[0]
    assert "Guidance will be raised" in stats.right_direction_wrong_reason_examples[0]
    assert stats.by_type["catalyst"]["refuted"] == 1

    block = format_thesis_block(stats)
    assert "Right direction wrong reason examples:" in block
    assert f"prediction_id={pid}" in block


def test_compute_thesis_stats_does_not_count_rdwr_when_direction_missed(
    mem_db: sqlite3.Connection,
) -> None:
    """Refuted catalyst on a *missed* direction is not RDWR (it's just plain wrong)."""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=12)).isoformat()
    pid = _insert_prediction(mem_db, ticker="NVDA", created_at=recent)
    _insert_outcome(mem_db, prediction_id=pid, actual_return=-0.04, direction_hit=0)

    mem_db.execute(
        "INSERT INTO prediction_theses (prediction_id, claim_text, claim_type,"
        " verdict, created_at) VALUES (?, ?, 'catalyst', 'refuted', ?)",
        (pid, "Guidance raise", recent),
    )
    mem_db.commit()

    stats = compute_thesis_stats(mem_db, hours=36)
    assert stats.right_direction_wrong_reason == 0


def test_compute_thesis_stats_empty(mem_db: sqlite3.Connection) -> None:
    """No theses -> zero stats, well-formed by_type dict."""
    stats = compute_thesis_stats(mem_db, hours=36)
    assert stats.total == 0
    assert "catalyst" in stats.by_type


def test_format_thesis_block_empty() -> None:
    """Empty stats -> human-readable placeholder, never crashes."""
    stats = ThesisStats(
        total=0, supported=0, refuted=0, unverified=0, pending=0,
        right_direction_wrong_reason=0, by_type={},
    )
    assert "no theses" in format_thesis_block(stats)


# -- ticker detection --


def test_detect_tickers_filters_stopwords() -> None:
    """Common all-caps non-tickers ('AI', 'API', etc.) are filtered out."""
    from stock.research import _detect_tickers_in_text

    text = "what's the AI play on NVDA right now? also AMD vs MU?"
    out = _detect_tickers_in_text(text)
    # 'AI' filtered; first two real tickers retained, capped at 2
    assert "AI" not in out
    assert out == ["NVDA", "AMD"]


def test_detect_tickers_handles_a_share_suffix() -> None:
    """A-share / HK suffix forms (600584.SS) are recognized."""
    from stock.research import _detect_tickers_in_text

    out = _detect_tickers_in_text("看一下 600584.SS 和 0700.HK")
    assert "600584.SS" in out
    assert "0700.HK" in out
