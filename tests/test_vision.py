"""tests.test_vision -- F18 image extraction + feedback formatting."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock import vision
from stock.config import get_settings
from stock.vision import (
    ImageExtraction,
    extract_image_info,
    format_extraction_as_feedback,
)


@pytest.fixture
def tmp_png(tmp_path: Path) -> Path:
    """Write a 1x1 PNG (8 bytes of header + minimal IDAT) to a temp path."""
    # 67-byte minimal valid PNG, hand-built so tests don't need Pillow installed.
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"  # signature
        b"\x00\x00\x00\rIHDR"  # IHDR chunk
        b"\x00\x00\x00\x01\x00\x00\x00\x01"  # 1x1
        b"\x08\x06\x00\x00\x00"  # 8-bit RGBA
        b"\x1f\x15\xc4\x89"  # IHDR CRC
        b"\x00\x00\x00\rIDAT"
        b"x\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    p = tmp_path / "test.png"
    p.write_bytes(png_bytes)
    return p


def _seed_settings(
    monkeypatch: pytest.MonkeyPatch, *,
    anthropic_key: str = "", minimax_key: str = "",
) -> None:
    """Stub get_settings everywhere it's used so .env on disk doesn't leak in."""
    fake = MagicMock()
    fake.anthropic_api_key = anthropic_key
    fake.minimax_api_key = minimax_key
    fake.minimax_base_url = ""
    fake.daily_cost_ceiling_usd = 1.0
    monkeypatch.setattr("stock.vision.get_settings", lambda: fake)


# -- backend selection + stub fallback --


def test_extract_returns_stub_when_no_keys(
    mem_db: sqlite3.Connection, tmp_png: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither anthropic nor minimax key -> stub extraction, no LLM call."""
    _seed_settings(monkeypatch)
    try:
        with (
            patch("stock.vision._call_anthropic_vision") as m_a,
            patch("stock.vision._call_minimax_vision") as m_m,
        ):
            result = extract_image_info(tmp_png, mem_db, caption="x")
        m_a.assert_not_called()
        m_m.assert_not_called()
        assert result.backend == "stub"
        assert result.cost_usd == 0.0
        assert result.ticker_mentions == []
    finally:
        get_settings.cache_clear()


def test_extract_anthropic_happy_path(
    mem_db: sqlite3.Connection, tmp_png: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic returns valid JSON -> extraction parsed, llm_calls row written."""
    _seed_settings(monkeypatch, anthropic_key="x")
    fake_json = json.dumps({
        "description": "Daily candlestick chart of NVDA, last 6 months, uptrend.",
        "extracted_text": "NVDA 145.32 +2.4%\nVolume 320M",
        "ticker_mentions": ["NVDA"],
        "suspected_topic": "NVDA momentum check",
        "user_intent": "question",
    })
    try:
        with (
            patch("stock.vision._call_anthropic_vision",
                  return_value=(fake_json, 1200, 80, 0.0234, 1500)) as m_a,
            patch("stock.vision._call_minimax_vision") as m_m,
        ):
            result = extract_image_info(tmp_png, mem_db, caption="check")
        m_a.assert_called_once()
        m_m.assert_not_called()
        assert result.backend == "anthropic"
        assert result.ticker_mentions == ["NVDA"]
        assert result.user_intent == "question"
        assert "uptrend" in result.description.lower()
        # llm_calls row present
        row = mem_db.execute(
            "SELECT provider, model, cost_usd FROM llm_calls WHERE caller = 'vision.extract_image_info'"
        ).fetchone()
        assert row == ("anthropic", "claude-opus-4-7", pytest.approx(0.0234))
    finally:
        get_settings.cache_clear()


def test_extract_falls_back_to_minimax_on_anthropic_failure(
    mem_db: sqlite3.Connection, tmp_png: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic raises -> MiniMax tried -> success."""
    _seed_settings(monkeypatch, anthropic_key="x", minimax_key="y")
    fake_json = json.dumps({
        "description": "Screenshot of broker app showing AVGO position.",
        "extracted_text": "AVGO +3.2%",
        "ticker_mentions": ["AVGO"],
        "suspected_topic": "AVGO position",
        "user_intent": "share",
    })
    try:
        with (
            patch("stock.vision._call_anthropic_vision",
                  side_effect=RuntimeError("anthropic 503")),
            patch("stock.vision._call_minimax_vision",
                  return_value=(fake_json, 800, 40, 0.0008, 900)) as m_m,
        ):
            result = extract_image_info(tmp_png, mem_db)
        m_m.assert_called_once()
        assert result.backend == "minimax"
        assert result.ticker_mentions == ["AVGO"]
    finally:
        get_settings.cache_clear()


def test_extract_returns_stub_on_double_failure(
    mem_db: sqlite3.Connection, tmp_png: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both backends raise -> stub extraction, never raises to caller."""
    _seed_settings(monkeypatch, anthropic_key="x", minimax_key="y")
    try:
        with (
            patch("stock.vision._call_anthropic_vision",
                  side_effect=RuntimeError("anthropic boom")),
            patch("stock.vision._call_minimax_vision",
                  side_effect=RuntimeError("minimax boom")),
        ):
            result = extract_image_info(tmp_png, mem_db)
        assert result.backend == "stub"
    finally:
        get_settings.cache_clear()


def test_extract_invalid_extension_returns_stub(
    mem_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported extension (.bmp) -> read fails inside _read_and_encode -> stub."""
    _seed_settings(monkeypatch, anthropic_key="x")
    bmp = tmp_path / "x.bmp"
    bmp.write_bytes(b"BM")
    try:
        with patch("stock.vision._call_anthropic_vision") as m_a:
            result = extract_image_info(bmp, mem_db)
        m_a.assert_not_called()
        assert result.backend == "stub"
    finally:
        get_settings.cache_clear()


def test_extract_oversized_image_returns_stub(
    mem_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Image > 8MB -> stub, no LLM call."""
    _seed_settings(monkeypatch, anthropic_key="x")
    huge = tmp_path / "huge.png"
    # PNG header + giant payload
    huge.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * (9 * 1024 * 1024))
    try:
        with patch("stock.vision._call_anthropic_vision") as m_a:
            result = extract_image_info(huge, mem_db)
        m_a.assert_not_called()
        assert result.backend == "stub"
    finally:
        get_settings.cache_clear()


# -- ticker filtering --


def test_extract_filters_stopword_tickers(
    mem_db: sqlite3.Connection, tmp_png: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM emits 'AI' and 'CEO' as tickers; both are stopword-filtered."""
    _seed_settings(monkeypatch, anthropic_key="x")
    fake_json = json.dumps({
        "description": "x",
        "extracted_text": "",
        "ticker_mentions": ["AI", "NVDA", "CEO", "AVGO", "USD"],
        "suspected_topic": "",
        "user_intent": "share",
    })
    try:
        with patch("stock.vision._call_anthropic_vision",
                   return_value=(fake_json, 100, 20, 0.001, 500)):
            result = extract_image_info(tmp_png, mem_db)
        assert result.ticker_mentions == ["NVDA", "AVGO"]
    finally:
        get_settings.cache_clear()


def test_extract_picks_up_regex_tickers_from_ocr(
    mem_db: sqlite3.Connection, tmp_png: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM emits no tickers but extracted_text contains them -> regex backfills."""
    _seed_settings(monkeypatch, anthropic_key="x")
    fake_json = json.dumps({
        "description": "Group chat screenshot",
        "extracted_text": "看一下 600584.SS 和 NVDA 的走势",
        "ticker_mentions": [],
        "suspected_topic": "compare",
        "user_intent": "question",
    })
    try:
        with patch("stock.vision._call_anthropic_vision",
                   return_value=(fake_json, 100, 20, 0.001, 500)):
            result = extract_image_info(tmp_png, mem_db)
        assert "NVDA" in result.ticker_mentions
        assert "600584.SS" in result.ticker_mentions
    finally:
        get_settings.cache_clear()


# -- intent coercion + JSON parse robustness --


def test_extract_invalid_intent_coerced_to_unknown(
    mem_db: sqlite3.Connection, tmp_png: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM emits 'BUY' as user_intent -> coerced to 'unknown'."""
    _seed_settings(monkeypatch, anthropic_key="x")
    fake_json = json.dumps({
        "description": "x", "extracted_text": "", "ticker_mentions": [],
        "suspected_topic": "", "user_intent": "BUY",
    })
    try:
        with patch("stock.vision._call_anthropic_vision",
                   return_value=(fake_json, 100, 20, 0.001, 500)):
            result = extract_image_info(tmp_png, mem_db)
        assert result.user_intent == "unknown"
    finally:
        get_settings.cache_clear()


def test_extract_handles_prose_wrapped_json(
    mem_db: sqlite3.Connection, tmp_png: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM wraps JSON in narrative; regex pulls the {...} block."""
    _seed_settings(monkeypatch, anthropic_key="x")
    raw = (
        'Sure, here is the analysis:\n'
        '{"description": "chart of TSLA", "extracted_text": "TSLA",'
        ' "ticker_mentions": ["TSLA"], "suspected_topic": "TSLA",'
        ' "user_intent": "share"}\n'
        'Let me know if you have other questions.'
    )
    try:
        with patch("stock.vision._call_anthropic_vision",
                   return_value=(raw, 100, 50, 0.002, 600)):
            result = extract_image_info(tmp_png, mem_db)
        assert "TSLA" in result.ticker_mentions
        assert "chart" in result.description.lower()
    finally:
        get_settings.cache_clear()


# -- format_extraction_as_feedback --


def test_format_feedback_has_image_and_summary_markers() -> None:
    """The feedback string is multi-line tagged so F13's classifier can parse it."""
    extraction = ImageExtraction(
        description="Chart of NVDA showing breakout above 150.",
        extracted_text="NVDA 152.45 +3.1%",
        ticker_mentions=["NVDA"],
        suspected_topic="NVDA breakout",
        user_intent="question",
        backend="anthropic", cost_usd=0.01, duration_ms=900,
    )
    text = format_extraction_as_feedback(
        extraction, image_filename="test.png", caption="check this",
    )
    assert "[caption] check this" in text
    assert "[image] test.png" in text
    assert "[summary] Chart of NVDA" in text
    assert "[topic] NVDA breakout" in text
    assert "[tickers] NVDA" in text
    assert "[ocr] NVDA 152.45" in text


def test_format_feedback_omits_empty_blocks() -> None:
    """When tickers + ocr empty, no [tickers]/[ocr] lines appear."""
    extraction = ImageExtraction(
        description="Unrelated meme image",
        extracted_text="",
        ticker_mentions=[],
        suspected_topic="meme",
        user_intent="share",
        backend="stub", cost_usd=0.0, duration_ms=0,
    )
    text = format_extraction_as_feedback(extraction, image_filename="meme.png")
    assert "[image] meme.png" in text
    assert "[summary] Unrelated meme image" in text
    assert "[topic] meme" in text
    assert "[tickers]" not in text
    assert "[ocr]" not in text
