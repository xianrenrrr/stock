"""tests.test_grading -- daily grade-and-reply: refresh prices, score, summarize, queue."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock.grading import (
    OutcomeRow,
    PriceRefreshResult,
    _append_model_improvements_to_rules,
    _extract_model_improvement_section,
    compute_stats,
    generate_grading_note,
    recent_outcomes,
    refresh_prices_for_all,
)
from stock.ingest import IngestResult
from stock.prompt_rewriter import RewriteProposal


def _insert_prediction(
    conn: sqlite3.Connection,
    *,
    ticker: str = "NVDA",
    direction: str = "up",
    prob_up: float = 0.8,
    prob_up_calibrated: float | None = 0.75,
    confidence: float = 0.7,
    rationale: str = "Earnings beat + guidance raise",
    model_used: str = "MiniMax-M2.5-highspeed",
    strategy_arm: str | None = "minimax/MiniMax-M2.5-highspeed/standard",
    created_at: str = "2026-04-29T14:00:00+00:00",
    due_at: str = "2026-04-30T21:00:00+00:00",
) -> int:
    """Insert a prediction row with sensible defaults; return its id."""
    cursor = conn.execute(
        "INSERT INTO predictions ("
        "  ticker, horizon_minutes, direction, prob_up, prob_up_calibrated,"
        "  confidence, rationale, key_factors_json, model_used, strategy_arm,"
        "  created_at, due_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticker, 390, direction, prob_up, prob_up_calibrated,
         confidence, rationale, "[]", model_used, strategy_arm,
         created_at, due_at),
    )
    conn.commit()
    return cursor.lastrowid or 0


def _insert_outcome(
    conn: sqlite3.Connection,
    *,
    prediction_id: int,
    actual_return: float,
    direction_hit: int,
    brier: float,
    scored_at: str | None = None,
) -> None:
    """Insert an outcome row tied to a prediction."""
    if scored_at is None:
        scored_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (prediction_id, actual_return, direction_hit, brier, scored_at),
    )
    conn.commit()


# -- recent_outcomes --


def test_recent_outcomes_filters_by_window(mem_db: sqlite3.Connection) -> None:
    """Only outcomes scored within the lookback window come back."""
    now = datetime.now(timezone.utc)
    fresh = now.isoformat()
    stale = (now - timedelta(hours=72)).isoformat()

    pid_fresh = _insert_prediction(mem_db, ticker="NVDA")
    _insert_outcome(mem_db, prediction_id=pid_fresh, actual_return=0.04,
                    direction_hit=1, brier=0.04, scored_at=fresh)

    pid_stale = _insert_prediction(mem_db, ticker="MSFT")
    _insert_outcome(mem_db, prediction_id=pid_stale, actual_return=-0.02,
                    direction_hit=0, brier=0.81, scored_at=stale)

    rows = recent_outcomes(mem_db, hours=36)
    assert len(rows) == 1
    assert rows[0].ticker == "NVDA"


def test_recent_outcomes_empty(mem_db: sqlite3.Connection) -> None:
    """No outcomes -> empty list."""
    assert recent_outcomes(mem_db, hours=36) == []


# -- compute_stats --


def _row(
    *, ticker: str, direction: str, prob_up: float, actual_return: float,
    direction_hit: int, prob_cal: float | None = None,
) -> OutcomeRow:
    """Build an OutcomeRow with reasonable defaults for stats tests."""
    went_up = actual_return > 0.0
    brier = (max(0.0, min(1.0, prob_up)) - (1.0 if went_up else 0.0)) ** 2
    return OutcomeRow(
        prediction_id=1, ticker=ticker, direction=direction,
        prob_up=prob_up, prob_up_calibrated=prob_cal,
        confidence=0.7, rationale="r", model_used="m", strategy_arm="a",
        actual_return=actual_return, direction_hit=direction_hit, brier=brier,
        created_at="2026-04-29T14:00:00+00:00",
        due_at="2026-04-30T21:00:00+00:00",
        scored_at="2026-04-30T21:30:00+00:00",
    )


def test_compute_stats_empty() -> None:
    """No rows -> zero stats, no biggest win/loss."""
    stats = compute_stats([])
    assert stats.total == 0
    assert stats.hit_rate == 0.0
    assert stats.biggest_win is None
    assert stats.biggest_loss is None
    assert stats.confident_misses == 0


def test_compute_stats_picks_biggest() -> None:
    """Biggest win = max actual_return among hits; biggest loss = max |return| among misses."""
    rows = [
        _row(ticker="NVDA", direction="up", prob_up=0.8, actual_return=0.05, direction_hit=1),
        _row(ticker="AMD", direction="up", prob_up=0.7, actual_return=0.02, direction_hit=1),
        _row(ticker="TSLA", direction="up", prob_up=0.85, actual_return=-0.06, direction_hit=0),
        _row(ticker="MSFT", direction="up", prob_up=0.6, actual_return=-0.01, direction_hit=0),
    ]
    stats = compute_stats(rows)
    assert stats.total == 4
    assert stats.hits == 2
    assert stats.hit_rate == 0.5
    assert stats.biggest_win is not None and stats.biggest_win.ticker == "NVDA"
    assert stats.biggest_loss is not None and stats.biggest_loss.ticker == "TSLA"
    # TSLA missed at prob 0.85 which is >= 0.7 -> confident miss; MSFT at 0.6 is not
    assert stats.confident_misses == 1


def test_compute_stats_calibrated_brier_skips_none() -> None:
    """Mean calibrated Brier is None when no row has a calibrated prob; else averaged."""
    rows = [
        _row(ticker="NVDA", direction="up", prob_up=0.8, actual_return=0.05,
             direction_hit=1, prob_cal=None),
    ]
    stats = compute_stats(rows)
    assert stats.mean_calibrated_brier is None

    rows2 = [
        _row(ticker="NVDA", direction="up", prob_up=0.8, actual_return=0.05,
             direction_hit=1, prob_cal=0.7),
        _row(ticker="AMD", direction="up", prob_up=0.6, actual_return=-0.02,
             direction_hit=0, prob_cal=0.55),
    ]
    stats2 = compute_stats(rows2)
    expected = ((0.7 - 1.0) ** 2 + (0.55 - 0.0) ** 2) / 2
    assert stats2.mean_calibrated_brier == pytest.approx(expected, abs=1e-6)


# -- refresh_prices_for_all --


def test_refresh_prices_combines_watchlist_and_holdings(
    mem_db: sqlite3.Connection,
) -> None:
    """Active watchlist + active holdings are unioned, deduped, sorted."""
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES ('NVDA', ?, 1)",
        (now,),
    )
    mem_db.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES ('AMD', ?, 1)",
        (now,),
    )
    mem_db.execute(
        "INSERT INTO holdings (ticker, qty, cost_basis, opened_at, notes,"
        " active, updated_at) VALUES ('TSLA', 10, 200, ?, '', 1, ?)",
        (now, now),
    )
    # Duplicate to confirm dedup
    mem_db.execute(
        "INSERT INTO holdings (ticker, qty, cost_basis, opened_at, notes,"
        " active, updated_at) VALUES ('NVDA', 5, 700, ?, '', 1, ?)",
        (now, now),
    )
    mem_db.commit()

    with patch("stock.grading.fetch_prices") as mock_fetch:
        mock_fetch.return_value = IngestResult(
            ticker="x", source="prices", fetched=3, inserted=2, skipped=1,
        )
        result = refresh_prices_for_all(mem_db)

    called_tickers = sorted(c.args[0] for c in mock_fetch.call_args_list)
    assert called_tickers == ["AMD", "NVDA", "TSLA"]
    assert result.tickers == ["AMD", "NVDA", "TSLA"]
    assert result.inserted_total == 2 * 3
    assert result.failed == []


def test_refresh_prices_records_failures(mem_db: sqlite3.Connection) -> None:
    """A per-ticker exception is logged into PriceRefreshResult.failed; loop continues."""
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES ('NVDA', ?, 1)",
        (now,),
    )
    mem_db.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES ('AMD', ?, 1)",
        (now,),
    )
    mem_db.commit()

    def _side_effect(ticker: str, conn: sqlite3.Connection, **kw: object) -> IngestResult:
        if ticker == "AMD":
            raise RuntimeError("yfinance 429")
        return IngestResult(ticker=ticker, source="prices", fetched=1, inserted=1, skipped=0)

    with patch("stock.grading.fetch_prices", side_effect=_side_effect):
        result = refresh_prices_for_all(mem_db)

    assert "AMD" in result.failed
    assert result.inserted_total == 1


# -- generate_grading_note --


def test_generate_grading_note_empty_window_no_llm(mem_db: sqlite3.Connection) -> None:
    """No outcomes in window -> persists short note, never calls the LLM."""
    with (
        patch("stock.grading.refresh_prices_for_all") as mock_refresh,
        patch("stock.grading.score_due") as mock_score,
        patch("stock.grading.get_core_client") as mock_client,
    ):
        mock_refresh.return_value = PriceRefreshResult(
            tickers=["NVDA"], inserted_total=1, failed=[],
        )
        mock_score.return_value = MagicMock(scored=0, skipped=0, already_scored=0)

        note = generate_grading_note(mem_db, lookback_hours=36)

    mock_client.assert_not_called()
    assert note.cost_usd == 0.0
    assert note.stats.total == 0
    assert note.follow_ups_queued == 0
    row = mem_db.execute(
        "SELECT kind, body FROM research_reports WHERE id = ?",
        (note.research_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "grading"
    assert "Not financial advice" in row[1]


def test_generate_grading_note_with_outcomes_persists_and_queues(
    mem_db: sqlite3.Connection,
) -> None:
    """With outcomes, calls LLM, persists kind='grading' row, enqueues follow-ups."""
    now = datetime.now(timezone.utc).isoformat()
    pid = _insert_prediction(mem_db, ticker="NVDA")
    _insert_outcome(mem_db, prediction_id=pid, actual_return=0.04,
                    direction_hit=1, brier=0.04, scored_at=now)

    fake_body = (
        "1. Yesterday hit 1/1.\n"
        "2. AI 自动跟进 / Auto-queued follow-ups\n"
        "- review last 5 NVDA predictions for guidance-vs-beat patterns\n"
        "- audit calibration curve for prob_up >= 0.8 cohort\n"
        "\nNot financial advice."
    )
    fake_response = MagicMock(content=fake_body, cost_usd=0.0012)

    with (
        patch("stock.grading.refresh_prices_for_all") as mock_refresh,
        patch("stock.grading.score_due") as mock_score,
        patch("stock.grading.check_cost_ceiling"),
        patch("stock.grading.get_core_client") as mock_core_factory,
        patch("stock.grading.get_core_model", return_value="MiniMax-M2.5-highspeed"),
    ):
        mock_refresh.return_value = PriceRefreshResult(
            tickers=["NVDA"], inserted_total=1, failed=[],
        )
        mock_score.return_value = MagicMock(scored=0, skipped=0, already_scored=1)
        mock_core_client = MagicMock()
        mock_core_client.chat.return_value = fake_response
        mock_core_factory.return_value = mock_core_client

        note = generate_grading_note(mem_db, lookback_hours=36)

    assert note.stats.total == 1
    assert note.stats.hits == 1
    assert note.cost_usd == pytest.approx(0.0012)
    # Both follow-up bullets queued
    assert note.follow_ups_queued == 2
    assert note.rewrites_applied == 0
    assert note.rewrites_staged == 0

    # Persisted row
    row = mem_db.execute(
        "SELECT kind, cost_usd FROM research_reports WHERE id = ?",
        (note.research_id,),
    ).fetchone()
    assert row[0] == "grading"
    assert row[1] == pytest.approx(0.0012)

    # action_queue rows present
    queued = mem_db.execute(
        "SELECT COUNT(*) FROM action_queue WHERE source_research_id = ?",
        (note.research_id,),
    ).fetchone()[0]
    assert queued == 2


def test_generate_grading_note_auto_applies_model_improvement_rewrites(
    mem_db: sqlite3.Connection,
) -> None:
    """Model Improvement Directions are sent through the prompt/rules rewriter."""
    now = datetime.now(timezone.utc).isoformat()
    pid = _insert_prediction(mem_db, ticker="NVDA")
    _insert_outcome(
        mem_db, prediction_id=pid, actual_return=-0.02,
        direction_hit=0, brier=0.36, scored_at=now,
    )

    fake_body = (
        "# Daily grading\n\n"
        "## 模型改进方向 / Model Improvement Directions\n"
        "- Add an explicit rule: stale AI-demand headlines with weak tape should "
        "be capped near neutral.\n\n"
        "## AI 自动跟进 / Auto-queued follow-ups\n"
        "- audit stale AI headline misses\n\n"
        "Not financial advice."
    )
    fake_response = MagicMock(content=fake_body, cost_usd=0.0012)
    proposal = RewriteProposal(
        target_path="data/rules/current.md",
        before_text="# Prediction Rules",
        after_text="# Prediction Rules\n\n- Test rule",
        rationale="grading evidence",
    )

    with (
        patch("stock.grading.refresh_prices_for_all") as mock_refresh,
        patch("stock.grading.score_due") as mock_score,
        patch("stock.grading.check_cost_ceiling"),
        patch("stock.grading.get_core_client") as mock_core_factory,
        patch("stock.grading.get_core_model", return_value="MiniMax-M2.5-highspeed"),
        patch(
            "stock.grading.prompt_rewriter.propose_rewrite_from_text",
            return_value=[proposal],
        ) as mock_propose,
        patch(
            "stock.grading.prompt_rewriter.apply_rewrite",
            return_value=123,
        ) as mock_apply,
    ):
        mock_refresh.return_value = PriceRefreshResult(
            tickers=["NVDA"], inserted_total=1, failed=[],
        )
        mock_score.return_value = MagicMock(scored=0, skipped=0, already_scored=1)
        mock_core_client = MagicMock()
        mock_core_client.chat.return_value = fake_response
        mock_core_factory.return_value = mock_core_client
        mem_db.execute(
            "INSERT INTO prompt_rewrites"
            " (id, target_path, before_text, after_text, rationale, cost_usd,"
            " applied, applied_at, created_at)"
            " VALUES (123, 'data/rules/current.md', 'a', 'b', 'r', 0, 1, ?, ?)",
            (now, now),
        )
        mem_db.commit()

        note = generate_grading_note(mem_db, lookback_hours=36)

    assert note.rewrites_applied == 1
    assert note.rewrites_staged == 0
    mock_propose.assert_called_once()
    mock_apply.assert_called_once_with(proposal, mem_db, force=True)


def test_extract_model_improvement_section() -> None:
    body = (
        "## Score\nx\n\n"
        "## 模型改进方向 / Model Improvement Directions\n"
        "- tighten confidence caps\n\n"
        "## AI 自动跟进 / Auto-queued follow-ups\n"
        "- audit next cohort\n"
    )
    section = _extract_model_improvement_section(body)
    assert "tighten confidence caps" in section
    assert "Auto-queued" not in section


def test_append_model_improvements_to_rules_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules_path = tmp_path / "current.md"
    rules_path.write_text("# Prediction Rules\n", encoding="utf-8")
    monkeypatch.setattr("stock.grading.AUTO_IMPROVE_RULES_PATH", str(rules_path))

    _append_model_improvements_to_rules(
        section="## Model Improvement Directions\n- Cap stale AI headline calls.",
        research_id=42,
    )

    text = rules_path.read_text(encoding="utf-8")
    assert "Auto-Appended Model Improvement" in text
    assert "grading #42" in text
    assert "Cap stale AI headline calls" in text


def test_generate_grading_note_appends_disclaimer(mem_db: sqlite3.Connection) -> None:
    """Disclaimer is appended when the LLM omits it."""
    now = datetime.now(timezone.utc).isoformat()
    pid = _insert_prediction(mem_db, ticker="NVDA")
    _insert_outcome(mem_db, prediction_id=pid, actual_return=0.01,
                    direction_hit=1, brier=0.04, scored_at=now)

    fake_response = MagicMock(content="A note without a disclaimer.", cost_usd=0.0001)

    with (
        patch("stock.grading.refresh_prices_for_all") as mock_refresh,
        patch("stock.grading.score_due"),
        patch("stock.grading.check_cost_ceiling"),
        patch("stock.grading.get_core_client") as mock_core_factory,
        patch("stock.grading.get_core_model", return_value="MiniMax-M2.5-highspeed"),
    ):
        mock_refresh.return_value = PriceRefreshResult(
            tickers=[], inserted_total=0, failed=[],
        )
        mock_core_client = MagicMock()
        mock_core_client.chat.return_value = fake_response
        mock_core_factory.return_value = mock_core_client

        note = generate_grading_note(mem_db, lookback_hours=36, refresh_prices=False)

    assert note.body.endswith("Not financial advice.")


def test_generate_grading_note_score_failure_is_non_fatal(
    mem_db: sqlite3.Connection,
) -> None:
    """If score_due raises, generate_grading_note still continues with whatever's already scored."""
    now = datetime.now(timezone.utc).isoformat()
    pid = _insert_prediction(mem_db, ticker="NVDA")
    _insert_outcome(mem_db, prediction_id=pid, actual_return=0.01,
                    direction_hit=1, brier=0.04, scored_at=now)

    with (
        patch("stock.grading.refresh_prices_for_all") as mock_refresh,
        patch("stock.grading.score_due", side_effect=RuntimeError("boom")),
        patch("stock.grading.check_cost_ceiling"),
        patch("stock.grading.get_core_client") as mock_core_factory,
        patch("stock.grading.get_core_model", return_value="MiniMax-M2.5-highspeed"),
    ):
        mock_refresh.return_value = PriceRefreshResult(
            tickers=[], inserted_total=0, failed=[],
        )
        mock_core_client = MagicMock()
        mock_core_client.chat.return_value = MagicMock(
            content="Body.\nNot financial advice.", cost_usd=0.0001,
        )
        mock_core_factory.return_value = mock_core_client

        note = generate_grading_note(mem_db, lookback_hours=36, refresh_prices=False)

    assert note.stats.total == 1


def test_generate_grading_note_skips_refresh_and_score_when_disabled(
    mem_db: sqlite3.Connection,
) -> None:
    """refresh_prices=False and score_first=False short-circuit those steps."""
    with (
        patch("stock.grading.refresh_prices_for_all") as mock_refresh,
        patch("stock.grading.score_due") as mock_score,
        patch("stock.grading.get_core_client") as mock_client,
    ):
        note = generate_grading_note(
            mem_db, lookback_hours=36, refresh_prices=False, score_first=False,
        )

    mock_refresh.assert_not_called()
    mock_score.assert_not_called()
    mock_client.assert_not_called()
    assert note.stats.total == 0
