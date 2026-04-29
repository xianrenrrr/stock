"""tests.test_reflect -- weekly reflection tests."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock.config import Settings
from stock.learn import (
    _choose_reflect_provider,
    _ensure_seed_rules,
    _extract_rules_text,
    _format_prediction_outcomes,
    _format_stats_summary,
    _get_next_version,
    reflect_weekly,
)
from stock.models import ChatResponse, CostCeilingError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chat_response(content: str) -> ChatResponse:
    """Build a ChatResponse with canned content."""
    return ChatResponse(
        content=content,
        input_tokens=100,
        output_tokens=200,
        model="test-model",
        cost_usd=0.01,
    )


def _insert_prediction_and_outcome(
    conn: sqlite3.Connection,
    ticker: str = "AAPL",
    direction: str = "up",
    prob_up: float = 0.72,
    confidence: float = 0.65,
    rationale: str = "Strong earnings beat with positive forward guidance.",
    key_factors: list[str] | None = None,
    actual_return: float = 0.013,
    direction_hit: int = 1,
    brier: float = 0.08,
    created_at: str | None = None,
) -> int:
    """Insert a prediction + outcome pair and return the prediction id."""
    if key_factors is None:
        key_factors = ["earnings beat", "positive guidance"]
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()

    cursor = conn.execute(
        "INSERT INTO predictions ("
        "  ticker, horizon_minutes, direction, prob_up, confidence,"
        "  rationale, key_factors_json, model_used, created_at, due_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticker, 390, direction, prob_up, confidence, rationale,
         json.dumps(key_factors), "test-model", created_at, created_at),
    )
    pred_id = cursor.lastrowid or 0

    conn.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (pred_id, actual_return, direction_hit, brier, created_at),
    )
    conn.commit()
    return pred_id


def _write_prompt(tmp_path: Path) -> None:
    """Write a minimal reflection prompt to tmp_path."""
    prompt = (
        "[SYSTEM]\nYou are a reviewer.\n\n[USER]\n"
        "## Current rules\n{current_rules}\n\n"
        "## Performance summary (last 7 days)\n{stats_summary}\n\n"
        "## Prediction details\n{prediction_outcomes}\n\n"
        "Output rules in <rules> tags."
    )
    (tmp_path / "reflect.txt").write_text(prompt, encoding="utf-8")


def _write_seed_rules(tmp_path: Path) -> None:
    """Write a seed v001.md to tmp_path."""
    (tmp_path / "v001.md").write_text("# Seed rules\n- Rule one.\n", encoding="utf-8")


def _write_current_rules(tmp_path: Path) -> None:
    """Write a current.md to tmp_path."""
    (tmp_path / "current.md").write_text("# Current rules\n- Be calibrated.\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# _extract_rules_text tests
# ---------------------------------------------------------------------------


def test_extract_rules_text_with_tags() -> None:
    """Content between <rules> tags is extracted."""
    raw = "Some preamble\n<rules>\n# New rules\n- Rule A\n</rules>\nEpilogue"
    assert _extract_rules_text(raw) == "# New rules\n- Rule A"


def test_extract_rules_text_without_tags() -> None:
    """Without tags, full stripped response is returned."""
    raw = "  # Just rules\n- Rule B  "
    assert _extract_rules_text(raw) == "# Just rules\n- Rule B"


def test_extract_rules_text_empty() -> None:
    """Empty string input returns empty string."""
    assert _extract_rules_text("") == ""


# ---------------------------------------------------------------------------
# _format_prediction_outcomes tests
# ---------------------------------------------------------------------------


def test_format_prediction_outcomes_populated() -> None:
    """Formatted output contains ticker, direction, return, hit markers."""
    rows: list[dict[str, str | float | int | None]] = [
        {
            "id": 1,
            "ticker": "AAPL",
            "direction": "up",
            "prob_up": 0.72,
            "confidence": 0.65,
            "rationale": "Earnings beat.",
            "key_factors_json": '["earnings", "guidance"]',
            "created_at": "2026-04-10T12:00:00+00:00",
            "actual_return": 0.013,
            "direction_hit": 1,
            "brier": 0.08,
        },
    ]
    result = _format_prediction_outcomes(rows)
    assert "AAPL" in result
    assert "up" in result
    assert "+1.3%" in result
    assert "YES" in result
    assert "earnings, guidance" in result


def test_format_prediction_outcomes_empty() -> None:
    """Empty list returns the no-scored-predictions message."""
    result = _format_prediction_outcomes([])
    assert result == "No scored predictions in the review period."


# ---------------------------------------------------------------------------
# _format_stats_summary tests
# ---------------------------------------------------------------------------


def test_format_stats_summary_populated() -> None:
    """Stats summary includes scored count and hit rate."""
    rows: list[dict[str, str | float | int | None]] = [
        {"direction_hit": 1, "brier": 0.08, "actual_return": 0.013},
        {"direction_hit": 0, "brier": 0.40, "actual_return": -0.005},
    ]
    result = _format_stats_summary(rows)
    assert "Predictions scored: 2" in result
    assert "Hit rate: 50.0%" in result


def test_format_stats_summary_empty() -> None:
    """Empty rows returns no-scored-predictions message."""
    result = _format_stats_summary([])
    assert "No scored predictions" in result


# ---------------------------------------------------------------------------
# _ensure_seed_rules tests
# ---------------------------------------------------------------------------


def test_ensure_seed_rules_inserts(
    mem_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty rules table + seed file exists inserts version 1."""
    monkeypatch.setattr("stock.learn.RULES_DIR", str(tmp_path))
    _write_seed_rules(tmp_path)

    _ensure_seed_rules(mem_db)

    row = mem_db.execute("SELECT version, text FROM rules WHERE version = 1").fetchone()
    assert row is not None
    assert "Seed rules" in row[1]


def test_ensure_seed_rules_skips_if_exists(
    mem_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-existing rules row means no additional insert."""
    monkeypatch.setattr("stock.learn.RULES_DIR", str(tmp_path))
    _write_seed_rules(tmp_path)

    # Pre-insert a rules row
    mem_db.execute(
        "INSERT INTO rules (version, text, created_at) VALUES (?, ?, ?)",
        (1, "existing", datetime.now(timezone.utc).isoformat()),
    )
    mem_db.commit()

    _ensure_seed_rules(mem_db)

    count = mem_db.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# _get_next_version tests
# ---------------------------------------------------------------------------


def test_get_next_version_empty_table(mem_db: sqlite3.Connection) -> None:
    """Empty rules table returns 1."""
    assert _get_next_version(mem_db) == 1


def test_get_next_version_existing(mem_db: sqlite3.Connection) -> None:
    """Rules table with versions 1-3 returns 4."""
    now = datetime.now(timezone.utc).isoformat()
    for v in (1, 2, 3):
        mem_db.execute(
            "INSERT INTO rules (version, text, created_at) VALUES (?, ?, ?)",
            (v, f"rules v{v}", now),
        )
    mem_db.commit()

    assert _get_next_version(mem_db) == 4


# ---------------------------------------------------------------------------
# _choose_reflect_provider tests
# ---------------------------------------------------------------------------


def test_choose_reflect_provider_claude(
    mem_db: sqlite3.Connection, env_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With Anthropic key and sufficient budget, returns claude."""
    monkeypatch.setattr(env_settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(env_settings, "daily_cost_ceiling_usd", 5.0)
    monkeypatch.setattr("stock.learn.get_settings", lambda: env_settings)

    provider, model = _choose_reflect_provider(mem_db)
    assert provider == "claude"
    assert model == "claude-opus-4-6"


def test_choose_reflect_provider_minimax_no_key(
    mem_db: sqlite3.Connection, env_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty Anthropic key falls back to minimax."""
    monkeypatch.setattr(env_settings, "anthropic_api_key", "")
    monkeypatch.setattr("stock.learn.get_settings", lambda: env_settings)

    provider, model = _choose_reflect_provider(mem_db)
    assert provider == "minimax"
    assert model == "MiniMax-M1-80k"


def test_choose_reflect_provider_minimax_low_budget(
    mem_db: sqlite3.Connection, env_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remaining budget below threshold falls back to minimax."""
    monkeypatch.setattr(env_settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(env_settings, "daily_cost_ceiling_usd", 1.00)
    monkeypatch.setattr("stock.learn.get_settings", lambda: env_settings)

    # Insert enough spend to leave remaining < $1
    mem_db.execute(
        "INSERT INTO llm_calls (model, provider, input_tokens, output_tokens,"
        " cost_usd, duration_ms, caller, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("test", "test", 100, 100, 0.50, 100, "test",
         datetime.now(timezone.utc).isoformat()),
    )
    mem_db.commit()

    provider, model = _choose_reflect_provider(mem_db)
    assert provider == "minimax"
    assert model == "MiniMax-M1-80k"


# ---------------------------------------------------------------------------
# reflect_weekly tests
# ---------------------------------------------------------------------------


@patch("stock.learn.get_client")
@patch("stock.learn.check_cost_ceiling")
@patch("stock.learn.get_settings")
def test_reflect_weekly_writes_version(
    mock_settings: MagicMock,
    mock_ceiling: MagicMock,
    mock_get_client: MagicMock,
    mem_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reflection writes versioned file, current.md, and DB row."""
    monkeypatch.setattr("stock.learn.RULES_DIR", str(tmp_path))
    monkeypatch.setattr("stock.learn.REFLECT_PROMPT_PATH", str(tmp_path / "reflect.txt"))
    _write_prompt(tmp_path)
    _write_seed_rules(tmp_path)
    _write_current_rules(tmp_path)

    # Clear the prompt cache so it reads from tmp_path
    from stock.learn import _load_reflect_prompt
    _load_reflect_prompt.cache_clear()

    # Configure mocks
    settings = Settings(
        anthropic_api_key="sk-test", minimax_api_key="test",
        stock_api_token="test", daily_cost_ceiling_usd=5.0, db_path=":memory:",
    )
    mock_settings.return_value = settings
    mock_ceiling.return_value = 0.0

    mock_client = MagicMock()
    mock_client.chat.return_value = _make_chat_response(
        "<rules>\n# Updated rules\n- New rule A.\n</rules>"
    )
    mock_get_client.return_value = mock_client

    result = reflect_weekly(mem_db)

    # Verify result (version 2 because seed occupies version 1)
    assert result.dry_run is False
    assert result.version == 2
    assert "New rule A" in result.rules_text

    # Verify versioned file written
    assert (tmp_path / "v002.md").exists()
    assert "New rule A" in (tmp_path / "v002.md").read_text(encoding="utf-8")

    # Verify current.md overwritten
    assert "New rule A" in (tmp_path / "current.md").read_text(encoding="utf-8")

    # Verify DB row
    row = mem_db.execute("SELECT version, text FROM rules ORDER BY version DESC LIMIT 1").fetchone()
    assert row[0] == 2
    assert "New rule A" in row[1]

    _load_reflect_prompt.cache_clear()


@patch("stock.learn.get_client")
@patch("stock.learn.check_cost_ceiling")
@patch("stock.learn.get_settings")
def test_reflect_weekly_dry_run(
    mock_settings: MagicMock,
    mock_ceiling: MagicMock,
    mock_get_client: MagicMock,
    mem_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dry run returns text without writing files or DB rows."""
    monkeypatch.setattr("stock.learn.RULES_DIR", str(tmp_path))
    monkeypatch.setattr("stock.learn.REFLECT_PROMPT_PATH", str(tmp_path / "reflect.txt"))
    _write_prompt(tmp_path)
    _write_seed_rules(tmp_path)

    from stock.learn import _load_reflect_prompt
    _load_reflect_prompt.cache_clear()

    settings = Settings(
        anthropic_api_key="sk-test", minimax_api_key="test",
        stock_api_token="test", daily_cost_ceiling_usd=5.0, db_path=":memory:",
    )
    mock_settings.return_value = settings
    mock_ceiling.return_value = 0.0

    mock_client = MagicMock()
    mock_client.chat.return_value = _make_chat_response(
        "<rules>\n# Dry run rules\n- Rule X.\n</rules>"
    )
    mock_get_client.return_value = mock_client

    result = reflect_weekly(mem_db, dry_run=True)

    assert result.dry_run is True
    assert "Dry run rules" in result.rules_text

    # No versioned file should exist
    assert not (tmp_path / "v002.md").exists()

    # No new DB row beyond the seed
    count = mem_db.execute(
        "SELECT COUNT(*) FROM rules WHERE version > 1"
    ).fetchone()[0]
    assert count == 0

    _load_reflect_prompt.cache_clear()


@patch("stock.learn.get_client")
@patch("stock.learn.check_cost_ceiling")
@patch("stock.learn.get_settings")
def test_reflect_weekly_version_increment(
    mock_settings: MagicMock,
    mock_ceiling: MagicMock,
    mock_get_client: MagicMock,
    mem_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-existing version 3 results in new version 4."""
    monkeypatch.setattr("stock.learn.RULES_DIR", str(tmp_path))
    monkeypatch.setattr("stock.learn.REFLECT_PROMPT_PATH", str(tmp_path / "reflect.txt"))
    _write_prompt(tmp_path)
    _write_current_rules(tmp_path)

    from stock.learn import _load_reflect_prompt
    _load_reflect_prompt.cache_clear()

    # Pre-insert rules version 3
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO rules (version, text, created_at) VALUES (?, ?, ?)",
        (3, "old rules v3", now),
    )
    mem_db.commit()

    settings = Settings(
        anthropic_api_key="sk-test", minimax_api_key="test",
        stock_api_token="test", daily_cost_ceiling_usd=5.0, db_path=":memory:",
    )
    mock_settings.return_value = settings
    mock_ceiling.return_value = 0.0

    mock_client = MagicMock()
    mock_client.chat.return_value = _make_chat_response(
        "<rules>\n# V4 rules\n- Rule V4.\n</rules>"
    )
    mock_get_client.return_value = mock_client

    result = reflect_weekly(mem_db)

    assert result.version == 4
    assert (tmp_path / "v004.md").exists()

    _load_reflect_prompt.cache_clear()


@patch("stock.learn.get_client")
@patch("stock.learn.check_cost_ceiling")
@patch("stock.learn.get_settings")
def test_reflect_weekly_no_outcomes(
    mock_settings: MagicMock,
    mock_ceiling: MagicMock,
    mock_get_client: MagicMock,
    mem_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reflection still runs with no predictions/outcomes."""
    monkeypatch.setattr("stock.learn.RULES_DIR", str(tmp_path))
    monkeypatch.setattr("stock.learn.REFLECT_PROMPT_PATH", str(tmp_path / "reflect.txt"))
    _write_prompt(tmp_path)
    _write_seed_rules(tmp_path)

    from stock.learn import _load_reflect_prompt
    _load_reflect_prompt.cache_clear()

    settings = Settings(
        anthropic_api_key="sk-test", minimax_api_key="test",
        stock_api_token="test", daily_cost_ceiling_usd=5.0, db_path=":memory:",
    )
    mock_settings.return_value = settings
    mock_ceiling.return_value = 0.0

    mock_client = MagicMock()
    mock_client.chat.return_value = _make_chat_response(
        "<rules>\n# Rules from empty.\n</rules>"
    )
    mock_get_client.return_value = mock_client

    result = reflect_weekly(mem_db)

    assert result.prediction_count == 0
    assert "Rules from empty" in result.rules_text

    # Verify the prompt included the no-scored message
    call_args = mock_client.chat.call_args
    user_msg = call_args.kwargs["messages"][0]["content"]
    assert "No scored predictions" in user_msg

    _load_reflect_prompt.cache_clear()


@patch("stock.learn.get_client")
@patch("stock.learn.check_cost_ceiling")
@patch("stock.learn.get_settings")
def test_reflect_weekly_cost_ceiling(
    mock_settings: MagicMock,
    mock_ceiling: MagicMock,
    mock_get_client: MagicMock,
    mem_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CostCeilingError propagates from check_cost_ceiling."""
    monkeypatch.setattr("stock.learn.RULES_DIR", str(tmp_path))
    monkeypatch.setattr("stock.learn.REFLECT_PROMPT_PATH", str(tmp_path / "reflect.txt"))
    _write_prompt(tmp_path)
    _write_seed_rules(tmp_path)

    from stock.learn import _load_reflect_prompt
    _load_reflect_prompt.cache_clear()

    settings = Settings(
        anthropic_api_key="sk-test", minimax_api_key="test",
        stock_api_token="test", daily_cost_ceiling_usd=5.0, db_path=":memory:",
    )
    mock_settings.return_value = settings
    mock_ceiling.side_effect = CostCeilingError("ceiling reached")

    with pytest.raises(CostCeilingError, match="ceiling reached"):
        reflect_weekly(mem_db)

    _load_reflect_prompt.cache_clear()


@patch("stock.learn.get_client")
@patch("stock.learn.check_cost_ceiling")
@patch("stock.learn.get_settings")
def test_reflect_weekly_empty_response(
    mock_settings: MagicMock,
    mock_ceiling: MagicMock,
    mock_get_client: MagicMock,
    mem_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty LLM response raises RuntimeError."""
    monkeypatch.setattr("stock.learn.RULES_DIR", str(tmp_path))
    monkeypatch.setattr("stock.learn.REFLECT_PROMPT_PATH", str(tmp_path / "reflect.txt"))
    _write_prompt(tmp_path)
    _write_seed_rules(tmp_path)

    from stock.learn import _load_reflect_prompt
    _load_reflect_prompt.cache_clear()

    settings = Settings(
        anthropic_api_key="sk-test", minimax_api_key="test",
        stock_api_token="test", daily_cost_ceiling_usd=5.0, db_path=":memory:",
    )
    mock_settings.return_value = settings
    mock_ceiling.return_value = 0.0

    mock_client = MagicMock()
    mock_client.chat.return_value = _make_chat_response("")
    mock_get_client.return_value = mock_client

    with pytest.raises(RuntimeError, match="empty rules"):
        reflect_weekly(mem_db)

    _load_reflect_prompt.cache_clear()
