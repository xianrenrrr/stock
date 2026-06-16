"""tests.test_predict -- prediction pipeline tests."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock.bandit import BanditSelection
from stock.config import Settings
from stock.models import ChatResponse, CostCeilingError
from stock.predict import (
    PredictionOutput,
    PredictionResult,
    _preserve_supported_calibration_direction,
    apply_probability_guardrails,
    compute_due_at,
    get_recent_features,
    get_recent_prices,
    predict_ticker,
)

VALID_PREDICTION_JSON: str = json.dumps({
    "direction": "up",
    "prob_up": 0.65,
    "expected_return_bps": 50,
    "confidence": 0.7,
    "rationale": "Strong earnings and positive momentum.",
    "key_factors": ["earnings beat", "positive momentum"],
})

VALID_FEATURE_JSON: str = json.dumps({
    "sentiment": "bullish",
    "novelty": "high",
    "catalyst_type": "earnings",
    "time_sensitivity": "days",
    "summary": "Strong earnings beat expectations.",
})


def test_probability_guardrails_cap_stale_ai_negative_tape() -> None:
    """Stale AI/semis bullish calls are capped when recent tape is negative."""
    output = PredictionOutput(
        direction="up",
        prob_up=0.64,
        expected_return_bps=90,
        confidence=0.7,
        rationale="AI demand and semiconductor equipment demand remain supportive.",
        key_factors=["AI infrastructure", "positive momentum"],
    )
    features = [{
        "catalyst_type": "analyst",
        "ts": "2026-05-17T12:00:00+00:00",
    }]
    prices = [
        {"ts": "2026-05-15", "c": 100.0},
        {"ts": "2026-05-18", "c": 98.0},
        {"ts": "2026-05-19", "c": 97.0},
    ]

    adjusted = apply_probability_guardrails(
        "AMAT",
        output,
        features,
        prices,
        as_of=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
    )

    assert adjusted.prob_up == pytest.approx(0.52)
    assert adjusted.confidence <= 0.52
    assert "Probability capped" in adjusted.rationale


def test_probability_guardrails_preserve_fresh_hard_catalyst() -> None:
    """Fresh earnings/guidance catalysts can override the stale narrative cap."""
    output = PredictionOutput(
        direction="up",
        prob_up=0.64,
        expected_return_bps=90,
        confidence=0.7,
        rationale="AI demand and semiconductor equipment demand remain supportive.",
        key_factors=["earnings beat", "AI infrastructure"],
    )
    features = [{
        "catalyst_type": "earnings",
        "ts": "2026-05-19T12:00:00+00:00",
    }]
    prices = [
        {"ts": "2026-05-15", "c": 100.0},
        {"ts": "2026-05-18", "c": 98.0},
        {"ts": "2026-05-19", "c": 97.0},
    ]

    adjusted = apply_probability_guardrails(
        "AMAT",
        output,
        features,
        prices,
        as_of=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
    )

    assert adjusted.prob_up == pytest.approx(0.64)


def test_probability_guardrails_cap_stale_thematic_upcall_without_confirmation() -> None:
    """Stale/thematic up-calls without fresh catalysts are capped at neutral."""
    output = PredictionOutput(
        direction="up",
        prob_up=0.54,
        expected_return_bps=40,
        confidence=0.58,
        rationale="Short-term price action is confirming up on a repeated theme.",
        key_factors=["confirming up", "stale narrative"],
    )
    features = [{
        "catalyst_type": "theme",
        "novelty": "repeated",
        "summary": "Repeated sector narrative without new company-specific news.",
        "ts": "2026-05-19T12:00:00+00:00",
    }]
    prices = [
        {"ts": "2026-05-15", "c": 100.0, "v": 1000},
        {"ts": "2026-05-18", "c": 101.0, "v": 1000},
        {"ts": "2026-05-19", "c": 102.0, "v": 1050},
    ]

    adjusted = apply_probability_guardrails(
        "AAPL",
        output,
        features,
        prices,
        as_of=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
    )

    assert adjusted.prob_up == pytest.approx(0.50)
    assert adjusted.confidence <= 0.50
    assert adjusted.expected_return_bps == 0
    assert "stale/thematic" in adjusted.rationale


def test_probability_guardrails_floor_down_into_geopolitical_riskon() -> None:
    """A mild down-fade into a fresh risk-on geopolitical catalyst is floored.

    Regression for the 2026-06-12 Iran-peace semiconductor relief rally, where
    down-fades (0981.HK, 688981.SS) were issued on 'no fresh company-specific
    hard catalyst' and run over by the macro relief rally.
    """
    output = PredictionOutput(
        direction="down",
        prob_up=0.49,
        expected_return_bps=-30,
        confidence=0.55,
        rationale="Failed gap-up; no fresh company-specific hard catalyst.",
        key_factors=["extended", "technical fade"],
    )
    features = [{
        "sentiment": "bullish",
        "catalyst_type": "macro",
        "summary": "Trump Iran peace deal sparks semiconductor relief rally.",
        "ts": "2026-06-12T11:00:00+00:00",
    }]
    prices = [
        {"ts": "2026-06-10", "c": 70.0, "v": 1000},
        {"ts": "2026-06-11", "c": 73.0, "v": 1100},
        {"ts": "2026-06-12", "c": 75.5, "v": 1200},
    ]

    adjusted = apply_probability_guardrails(
        "0981.HK",
        output,
        features,
        prices,
        as_of=datetime(2026, 6, 12, 14, 0, tzinfo=timezone.utc),
    )

    assert adjusted.prob_up == pytest.approx(0.50)
    assert adjusted.expected_return_bps >= 0
    assert "geopolitical" in adjusted.rationale


def test_probability_guardrails_skip_upcall_cap_under_geopolitical_riskon() -> None:
    """A stale/thematic up-call is NOT capped when a fresh risk-on geo catalyst is live."""
    output = PredictionOutput(
        direction="up",
        prob_up=0.62,
        expected_return_bps=80,
        confidence=0.68,
        rationale="AI/semis demand stays supportive into the relief rally.",
        key_factors=["AI infrastructure", "risk-on tape"],
    )
    features = [{
        "sentiment": "bullish",
        "catalyst_type": "macro",
        "novelty": "high",
        "summary": "Iran ceasefire fuels broad semiconductor risk-on rally.",
        "ts": "2026-06-12T11:00:00+00:00",
    }]
    prices = [
        {"ts": "2026-06-10", "c": 100.0, "v": 1000},
        {"ts": "2026-06-11", "c": 103.0, "v": 1100},
        {"ts": "2026-06-12", "c": 106.0, "v": 1200},
    ]

    adjusted = apply_probability_guardrails(
        "AMAT",
        output,
        features,
        prices,
        as_of=datetime(2026, 6, 12, 14, 0, tzinfo=timezone.utc),
    )

    assert adjusted.prob_up == pytest.approx(0.62)


def test_probability_guardrails_cap_post_catalyst_exhaustion() -> None:
    """Day-2/day-3 hard-catalyst continuations are capped after an 8%+ rally."""
    output = PredictionOutput(
        direction="up",
        prob_up=0.56,
        expected_return_bps=70,
        confidence=0.62,
        rationale="Earnings beat, confirming volume, and AI infrastructure breadth.",
        key_factors=["earnings beat", "confirming volume", "AI infrastructure"],
    )
    features = [{
        "catalyst_type": "earnings",
        "sentiment": "bullish",
        "ts": "2026-05-17T12:00:00+00:00",
    }]
    prices = [
        {"ts": "2026-05-15", "c": 100.0},
        {"ts": "2026-05-18", "c": 106.0},
        {"ts": "2026-05-19", "c": 109.0},
    ]

    adjusted = apply_probability_guardrails(
        "DELL",
        output,
        features,
        prices,
        as_of=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
    )

    assert adjusted.prob_up == pytest.approx(0.51)
    assert adjusted.confidence <= 0.51
    assert adjusted.expected_return_bps == 10
    assert "post-catalyst exhaustion" in adjusted.rationale


def _seed_ai_infra_peer_breadth(conn: sqlite3.Connection) -> None:
    for ticker, prior, latest in [
        ("AMD", 100.0, 108.0),
        ("AVGO", 100.0, 104.0),
        ("MU", 100.0, 110.0),
        ("NVDA", 100.0, 103.0),
        ("SMCI", 100.0, 102.0),
        ("DELL", 100.0, 99.0),
    ]:
        conn.execute(
            "INSERT INTO prices (ticker, ts, o, h, l, c, v)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, "2026-05-18", prior, prior, prior, prior, 1000000),
        )
        conn.execute(
            "INSERT INTO prices (ticker, ts, o, h, l, c, v)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, "2026-05-19", latest, latest, latest, latest, 1000000),
        )
    conn.commit()


def test_probability_guardrails_floor_ai_bearish_positive_breadth(
    mem_db: sqlite3.Connection,
) -> None:
    """Broad positive AI/semis tape forces bearish stale calls to neutral."""
    _seed_ai_infra_peer_breadth(mem_db)
    output = PredictionOutput(
        direction="down",
        prob_up=0.46,
        expected_return_bps=-40,
        confidence=0.7,
        rationale="Mostly repeated bullish AI-memory narrative; profit-taking risk.",
        key_factors=["AI infrastructure", "extended up"],
    )
    features = [{
        "catalyst_type": "analyst",
        "sentiment": "neutral",
        "ts": "2026-05-19T12:00:00+00:00",
    }]
    prices = [
        {"ts": "2026-05-18", "c": 100.0},
        {"ts": "2026-05-19", "c": 108.0},
    ]

    adjusted = apply_probability_guardrails(
        "MU",
        output,
        features,
        prices,
        as_of=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
        conn=mem_db,
    )

    assert adjusted.prob_up == pytest.approx(0.50)
    assert adjusted.confidence <= 0.50
    assert adjusted.expected_return_bps == 0
    assert "Probability floored" in adjusted.rationale


def test_probability_guardrails_floor_peer_readthrough_downcall_without_confirmation() -> None:
    """Low-confidence single-peer read-through down-calls are neutralized."""
    output = PredictionOutput(
        direction="down",
        prob_up=0.47,
        expected_return_bps=-30,
        confidence=0.56,
        rationale=(
            "Negative peer/sector earnings read-through from Broadcom's soft "
            "AI guidance pressures semiconductors."
        ),
        key_factors=["peer read-through", "Broadcom soft AI guidance"],
    )
    features = [{
        "catalyst_type": "sector",
        "sentiment": "neutral",
        "ts": "2026-06-08T12:00:00+00:00",
    }]
    prices = [
        {"ts": "2026-06-04", "c": 100.0, "v": 1000},
        {"ts": "2026-06-05", "c": 100.5, "v": 1000},
        {"ts": "2026-06-08", "c": 100.0, "v": 1050},
    ]

    adjusted = apply_probability_guardrails(
        "INTC",
        output,
        features,
        prices,
        as_of=datetime(2026, 6, 8, 14, 0, tzinfo=timezone.utc),
    )

    assert adjusted.prob_up == pytest.approx(0.50)
    assert adjusted.confidence <= 0.50
    assert adjusted.expected_return_bps == 0
    assert "single-peer read-through" in adjusted.rationale


def test_probability_guardrails_preserve_peer_readthrough_with_down_volume() -> None:
    """Confirming downside volume allows low-confidence peer-read-through down-calls."""
    output = PredictionOutput(
        direction="down",
        prob_up=0.47,
        expected_return_bps=-30,
        confidence=0.56,
        rationale="Negative peer read-through from Broadcom weighs on memory.",
        key_factors=["peer read-through", "confirming volume"],
    )
    features = [{
        "catalyst_type": "sector",
        "sentiment": "neutral",
        "ts": "2026-06-08T12:00:00+00:00",
    }]
    prices = [
        {"ts": "2026-06-02", "c": 102.0, "v": 1000},
        {"ts": "2026-06-03", "c": 101.0, "v": 1000},
        {"ts": "2026-06-04", "c": 100.5, "v": 1000},
        {"ts": "2026-06-05", "c": 100.0, "v": 1000},
        {"ts": "2026-06-08", "c": 99.0, "v": 1600},
    ]

    adjusted = apply_probability_guardrails(
        "MU",
        output,
        features,
        prices,
        as_of=datetime(2026, 6, 8, 14, 0, tzinfo=timezone.utc),
    )

    assert adjusted.prob_up == pytest.approx(0.47)
    assert "single-peer read-through" not in adjusted.rationale


def test_probability_guardrails_require_strong_ai_group_median(
    mem_db: sqlite3.Connection,
) -> None:
    """Weakly positive AI/semis breadth is not enough to override bearish calls."""
    for ticker, prior, latest in [
        ("AMD", 100.0, 100.1),
        ("AVGO", 100.0, 100.2),
        ("MU", 100.0, 100.3),
        ("NVDA", 100.0, 100.4),
        ("SMCI", 100.0, 99.0),
    ]:
        mem_db.execute(
            "INSERT INTO prices (ticker, ts, o, h, l, c, v)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, "2026-05-18", prior, prior, prior, prior, 1000000),
        )
        mem_db.execute(
            "INSERT INTO prices (ticker, ts, o, h, l, c, v)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, "2026-05-19", latest, latest, latest, latest, 1000000),
        )
    mem_db.commit()
    output = PredictionOutput(
        direction="down",
        prob_up=0.46,
        expected_return_bps=-40,
        confidence=0.7,
        rationale="Failed candle despite an AI infrastructure narrative.",
        key_factors=["AI infrastructure", "failed candle"],
    )
    features = [{
        "catalyst_type": "analyst",
        "sentiment": "neutral",
        "ts": "2026-05-19T12:00:00+00:00",
    }]
    prices = [
        {"ts": "2026-05-18", "c": 100.0},
        {"ts": "2026-05-19", "c": 99.0},
    ]

    adjusted = apply_probability_guardrails(
        "COHR",
        output,
        features,
        prices,
        as_of=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
        conn=mem_db,
    )

    assert adjusted.prob_up == pytest.approx(0.46)
    assert "Probability floored" not in adjusted.rationale


def test_probability_guardrails_allow_stale_ai_upcall_with_breadth_and_volume(
    mem_db: sqlite3.Connection,
) -> None:
    """Supportive AI breadth plus confirming volume exempts stale up-calls."""
    _seed_ai_infra_peer_breadth(mem_db)
    output = PredictionOutput(
        direction="up",
        prob_up=0.54,
        expected_return_bps=40,
        confidence=0.58,
        rationale="AI infrastructure tape is confirming up despite stale news.",
        key_factors=["AI infrastructure", "confirming volume"],
    )
    features = [{
        "catalyst_type": "theme",
        "novelty": "stale",
        "summary": "Repeated AI infrastructure sector narrative.",
        "ts": "2026-05-19T12:00:00+00:00",
    }]
    prices = [
        {"ts": "2026-05-14", "c": 99.0, "v": 1000},
        {"ts": "2026-05-15", "c": 100.0, "v": 1000},
        {"ts": "2026-05-18", "c": 101.0, "v": 1000},
        {"ts": "2026-05-19", "c": 102.0, "v": 1600},
    ]

    adjusted = apply_probability_guardrails(
        "MU",
        output,
        features,
        prices,
        as_of=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
        conn=mem_db,
    )

    assert adjusted.prob_up == pytest.approx(0.54)
    assert "stale/thematic" not in adjusted.rationale


def test_probability_guardrails_preserve_fresh_negative_hard_catalyst(
    mem_db: sqlite3.Connection,
) -> None:
    """A fresh bearish hard catalyst can override positive sector breadth."""
    _seed_ai_infra_peer_breadth(mem_db)
    output = PredictionOutput(
        direction="down",
        prob_up=0.46,
        expected_return_bps=-40,
        confidence=0.7,
        rationale="Guidance cut offsets the AI infrastructure tape.",
        key_factors=["guidance cut", "AI infrastructure"],
    )
    features = [{
        "catalyst_type": "guidance",
        "sentiment": "bearish",
        "ts": "2026-05-19T12:00:00+00:00",
    }]
    prices = [
        {"ts": "2026-05-18", "c": 100.0},
        {"ts": "2026-05-19", "c": 108.0},
    ]

    adjusted = apply_probability_guardrails(
        "MU",
        output,
        features,
        prices,
        as_of=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
        conn=mem_db,
    )

    assert adjusted.prob_up == pytest.approx(0.46)


def test_calibration_direction_guard_preserves_fresh_bullish_catalyst(
    mem_db: sqlite3.Connection,
) -> None:
    """Calibration cannot flip a fresh bullish hard-catalyst call below neutral."""
    output = PredictionOutput(
        direction="up",
        prob_up=0.54,
        expected_return_bps=30,
        confidence=0.55,
        rationale="Fresh earnings beat supports upside.",
        key_factors=["earnings beat"],
    )
    features = [{
        "catalyst_type": "earnings",
        "sentiment": "bullish",
        "ts": "2026-05-19T12:00:00+00:00",
    }]

    adjusted = _preserve_supported_calibration_direction(
        "DELL",
        output,
        features,
        0.47,
        mem_db,
        as_of=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
    )

    assert adjusted == pytest.approx(0.50)


def test_calibration_direction_guard_preserves_fresh_bearish_catalyst(
    mem_db: sqlite3.Connection,
) -> None:
    """Calibration cannot flip a fresh bearish hard-catalyst call above neutral."""
    output = PredictionOutput(
        direction="down",
        prob_up=0.46,
        expected_return_bps=-30,
        confidence=0.55,
        rationale="Fresh guidance cut supports downside.",
        key_factors=["guidance cut"],
    )
    features = [{
        "catalyst_type": "guidance",
        "sentiment": "bearish",
        "ts": "2026-05-19T12:00:00+00:00",
    }]

    adjusted = _preserve_supported_calibration_direction(
        "ORCL",
        output,
        features,
        0.53,
        mem_db,
        as_of=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
    )

    assert adjusted == pytest.approx(0.50)


def test_calibration_direction_guard_keeps_unsupported_crossing(
    mem_db: sqlite3.Connection,
) -> None:
    """Unsupported raw calls still receive the stored calibration result."""
    output = PredictionOutput(
        direction="up",
        prob_up=0.54,
        expected_return_bps=30,
        confidence=0.55,
        rationale="Short-term price action is positive.",
        key_factors=["top-quartile close"],
    )
    features = [{
        "catalyst_type": "analyst",
        "sentiment": "neutral",
        "ts": "2026-05-19T12:00:00+00:00",
    }]

    adjusted = _preserve_supported_calibration_direction(
        "AAPL",
        output,
        features,
        0.47,
        mem_db,
        as_of=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
    )

    assert adjusted == pytest.approx(0.47)


def _mock_chat_response(content: str = VALID_PREDICTION_JSON) -> ChatResponse:
    return ChatResponse(
        content=content,
        input_tokens=200,
        output_tokens=100,
        model="MiniMax-M1-80k",
        cost_usd=0.001,
    )


def _seed_data(conn: sqlite3.Connection) -> None:
    """Insert test news, features, and prices for AAPL."""
    now = datetime.now(timezone.utc).isoformat()

    # Insert news
    conn.execute(
        "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("AAPL", "test", "https://example.com/test", "AAPL earnings beat",
         "Apple reported strong earnings", now, now),
    )
    news_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Insert features
    conn.execute(
        "INSERT INTO features (news_id, json, model, ts) VALUES (?, ?, ?, ?)",
        (news_id, VALID_FEATURE_JSON, "MiniMax-M1-80k", now),
    )

    # Insert prices
    for idx in range(10):
        ts = f"2026-04-{15 - idx:02d}"
        conn.execute(
            "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", ts, 150.0 + idx, 155.0 + idx, 148.0 + idx, 152.0 + idx, 1000000),
        )
    conn.commit()


@patch("stock.predict.calibrate", side_effect=lambda prob, conn: prob)
@patch("stock.predict.select_arm")
@patch("stock.predict.retrieve", return_value=[])
@patch("stock.predict.embed", return_value=[0.0] * 384)
@patch("stock.predict.load_predict_prompt")
@patch("stock.predict.extract_features", return_value=[])
@patch("stock.predict.get_core_model", return_value="codex-cli-session")
@patch("stock.predict.get_core_client")
def test_predict_ticker_inserts_prediction(
    mock_get: MagicMock,
    mock_model: MagicMock,
    _mock_extract: MagicMock,
    mock_prompt: MagicMock,
    _mock_embed: MagicMock,
    _mock_retrieve: MagicMock,
    mock_select: MagicMock,
    _mock_calibrate: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """predict_ticker inserts a row into predictions and returns PredictionResult."""
    _seed_data(mem_db)
    mock_select.return_value = BanditSelection(
        strategy_arm="minimax/default", provider="minimax", model="MiniMax-M1-80k"
    )
    mock_prompt.return_value = ("{rules}", "{ticker} {horizon} {feature_summary} "
                                "{price_count} {price_history} {retrieved_cases}")
    mock_client = MagicMock()
    mock_get.return_value = mock_client
    mock_client.chat.return_value = _mock_chat_response()

    result = predict_ticker("AAPL", mem_db)

    assert isinstance(result, PredictionResult)
    assert result.ticker == "AAPL"
    assert result.direction == "up"
    assert result.prob_up == pytest.approx(0.65)

    row = mem_db.execute("SELECT * FROM predictions").fetchone()
    assert row is not None


@patch("stock.predict.extract_features", return_value=[])
def test_predict_ticker_raises_no_prices(
    _mock_extract: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """ValueError raised when no prices exist for the ticker."""
    with pytest.raises(ValueError, match="No price data"):
        predict_ticker("AAPL", mem_db)


@patch("stock.predict.load_predict_prompt")
@patch("stock.predict.extract_features", return_value=[])
@patch("stock.predict.get_core_model", return_value="codex-cli-session")
@patch("stock.predict.get_core_client")
def test_predict_ticker_raises_no_features(
    mock_get: MagicMock,
    mock_model: MagicMock,
    _mock_extract: MagicMock,
    mock_prompt: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """ValueError raised when no features exist after extraction."""
    for idx in range(3):
        mem_db.execute(
            "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", f"2026-04-{15 - idx:02d}", 150.0, 155.0, 148.0, 152.0, 1000000),
        )
    mem_db.commit()

    with pytest.raises(ValueError, match="No features"):
        predict_ticker("AAPL", mem_db)


@patch("stock.predict.calibrate", side_effect=lambda prob, conn: prob)
@patch("stock.predict.select_arm")
@patch("stock.predict.retrieve", return_value=[])
@patch("stock.predict.embed", return_value=[0.0] * 384)
@patch("stock.predict.load_predict_prompt")
@patch("stock.predict.extract_features", return_value=[])
@patch("stock.predict.get_core_model", return_value="codex-cli-session")
@patch("stock.predict.get_core_client")
def test_predict_ticker_handles_code_fences(
    mock_get: MagicMock,
    mock_model: MagicMock,
    _mock_extract: MagicMock,
    mock_prompt: MagicMock,
    _mock_embed: MagicMock,
    _mock_retrieve: MagicMock,
    mock_select: MagicMock,
    _mock_calibrate: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """JSON wrapped in code fences is parsed correctly."""
    _seed_data(mem_db)
    mock_select.return_value = BanditSelection(
        strategy_arm="minimax/default", provider="minimax", model="MiniMax-M1-80k"
    )
    mock_prompt.return_value = ("{rules}", "{ticker} {horizon} {feature_summary} "
                                "{price_count} {price_history} {retrieved_cases}")
    fenced = f"```json\n{VALID_PREDICTION_JSON}\n```"
    mock_client = MagicMock()
    mock_get.return_value = mock_client
    mock_client.chat.return_value = _mock_chat_response(fenced)

    result = predict_ticker("AAPL", mem_db)
    assert result.direction == "up"


@patch("stock.predict.calibrate", side_effect=lambda prob, conn: prob)
@patch("stock.predict.select_arm")
@patch("stock.predict.retrieve", return_value=[])
@patch("stock.predict.embed", return_value=[0.0] * 384)
@patch("stock.predict.load_predict_prompt")
@patch("stock.predict.extract_features", return_value=[])
@patch("stock.predict.get_core_model", return_value="codex-cli-session")
@patch("stock.predict.get_core_client")
def test_predict_ticker_clamps_prob_up(
    mock_get: MagicMock,
    mock_model: MagicMock,
    _mock_extract: MagicMock,
    mock_prompt: MagicMock,
    _mock_embed: MagicMock,
    _mock_retrieve: MagicMock,
    mock_select: MagicMock,
    _mock_calibrate: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """prob_up outside [0, 1] is clamped."""
    _seed_data(mem_db)
    mock_select.return_value = BanditSelection(
        strategy_arm="minimax/default", provider="minimax", model="MiniMax-M1-80k"
    )
    mock_prompt.return_value = ("{rules}", "{ticker} {horizon} {feature_summary} "
                                "{price_count} {price_history} {retrieved_cases}")
    bad_json = json.dumps({
        "direction": "up",
        "prob_up": 1.5,
        "expected_return_bps": 50,
        "confidence": 0.7,
        "rationale": "test",
        "key_factors": ["test"],
    })
    mock_client = MagicMock()
    mock_get.return_value = mock_client
    mock_client.chat.return_value = _mock_chat_response(bad_json)

    result = predict_ticker("AAPL", mem_db)
    assert result.prob_up == pytest.approx(1.0)


@patch("stock.predict.calibrate", side_effect=lambda prob, conn: prob)
@patch("stock.predict.select_arm")
@patch("stock.predict.retrieve", return_value=[])
@patch("stock.predict.embed", return_value=[0.0] * 384)
@patch("stock.predict.load_predict_prompt")
@patch("stock.predict.extract_features", return_value=[])
@patch("stock.predict.get_core_model", return_value="codex-cli-session")
@patch("stock.predict.get_core_client")
def test_predict_ticker_cost_ceiling(
    mock_get: MagicMock,
    mock_model: MagicMock,
    _mock_extract: MagicMock,
    mock_prompt: MagicMock,
    _mock_embed: MagicMock,
    _mock_retrieve: MagicMock,
    mock_select: MagicMock,
    _mock_calibrate: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """CostCeilingError from LLM call propagates."""
    _seed_data(mem_db)
    mock_select.return_value = BanditSelection(
        strategy_arm="minimax/default", provider="minimax", model="MiniMax-M1-80k"
    )
    mock_prompt.return_value = ("{rules}", "{ticker} {horizon} {feature_summary} "
                                "{price_count} {price_history} {retrieved_cases}")
    mock_client = MagicMock()
    mock_get.return_value = mock_client
    mock_client.chat.side_effect = CostCeilingError("ceiling")

    with pytest.raises(CostCeilingError):
        predict_ticker("AAPL", mem_db)


def test_compute_due_at_weekday() -> None:
    """Monday 10:00 UTC gives Tuesday 21:00 UTC as due."""
    monday = datetime(2026, 4, 13, 10, 0, tzinfo=timezone.utc)
    result = compute_due_at(monday, 390)
    assert "2026-04-14T21:00:00" in result


def test_compute_due_at_friday_evening() -> None:
    """Friday 22:00 UTC skips weekend, gives Tuesday 21:00 UTC."""
    friday = datetime(2026, 4, 10, 22, 0, tzinfo=timezone.utc)
    result = compute_due_at(friday, 390)
    assert "2026-04-14T21:00:00" in result


@patch("stock.predict.calibrate", side_effect=lambda prob, conn: prob)
@patch("stock.predict.select_arm")
@patch("stock.predict.retrieve", return_value=[])
@patch("stock.predict.embed", return_value=[0.0] * 384)
@patch("stock.predict.load_predict_prompt")
@patch("stock.predict.extract_features", return_value=[])
@patch("stock.predict.get_core_model", return_value="codex-cli-session")
@patch("stock.predict.get_core_client")
def test_prediction_row_structure(
    mock_get: MagicMock,
    mock_model: MagicMock,
    _mock_extract: MagicMock,
    mock_prompt: MagicMock,
    _mock_embed: MagicMock,
    _mock_retrieve: MagicMock,
    mock_select: MagicMock,
    _mock_calibrate: MagicMock,
    env_settings: Settings,
    mem_db: sqlite3.Connection,
) -> None:
    """Verify F05 columns are populated and F06 columns are NULL."""
    _seed_data(mem_db)
    mock_select.return_value = BanditSelection(
        strategy_arm="minimax/default", provider="minimax", model="MiniMax-M1-80k"
    )
    mock_prompt.return_value = ("{rules}", "{ticker} {horizon} {feature_summary} "
                                "{price_count} {price_history} {retrieved_cases}")
    mock_client = MagicMock()
    mock_get.return_value = mock_client
    mock_client.chat.return_value = _mock_chat_response()

    predict_ticker("AAPL", mem_db)

    cursor = mem_db.execute("SELECT * FROM predictions")
    assert cursor.description is not None
    col_names = [desc[0] for desc in cursor.description]
    row = cursor.fetchone()
    assert row is not None
    row_dict = dict(zip(col_names, row))

    # F05 columns should now be populated
    assert row_dict["prob_up_calibrated"] is not None
    assert row_dict["strategy_arm"] == "minimax/default"
    assert row_dict["model_used"] == "MiniMax-M1-80k"

    # F06 column still NULL
    assert row_dict["rules_version"] is None
    assert row_dict["retrieved_case_ids"] is None or row_dict["retrieved_case_ids"] == "[]"

    # Required columns should be populated
    assert row_dict["ticker"] == "AAPL"
    assert row_dict["direction"] == "up"
    assert row_dict["feature_context_json"] is not None

    # feature_context_json contains retrieved_case_ids
    ctx = json.loads(row_dict["feature_context_json"])
    assert "retrieved_case_ids" in ctx
    assert isinstance(ctx["retrieved_case_ids"], list)


def test_get_recent_prices_returns_oldest_first(
    env_settings: Settings, mem_db: sqlite3.Connection
) -> None:
    """Prices are returned in chronological (oldest-first) order."""
    for idx in range(5):
        mem_db.execute(
            "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", f"2026-04-{10 + idx:02d}", 150.0, 155.0, 148.0, 152.0, 1000000),
        )
    mem_db.commit()

    prices = get_recent_prices("AAPL", mem_db)
    assert len(prices) == 5
    assert prices[0]["ts"] < prices[-1]["ts"]


def test_get_recent_prices_raises_when_empty(
    env_settings: Settings, mem_db: sqlite3.Connection
) -> None:
    """ValueError raised when no prices exist."""
    with pytest.raises(ValueError, match="No price data"):
        get_recent_prices("AAPL", mem_db)


def test_get_recent_features_returns_data(
    env_settings: Settings, mem_db: sqlite3.Connection
) -> None:
    """Features joined with news titles are returned."""
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("AAPL", "test", "https://example.com/x", "Test title", "body", now, now),
    )
    mem_db.execute(
        "INSERT INTO features (news_id, json, model, ts) VALUES (?, ?, ?, ?)",
        (1, VALID_FEATURE_JSON, "test", now),
    )
    mem_db.commit()

    features = get_recent_features("AAPL", mem_db)
    assert len(features) == 1
    assert features[0]["title"] == "Test title"
    assert features[0]["sentiment"] == "bullish"
