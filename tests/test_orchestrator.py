"""tests.test_orchestrator -- orchestrator scheduling and job tests."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from apscheduler.schedulers.blocking import BlockingScheduler

from stock.models import CostCeilingError
from stock.orchestrator import (
    ScheduleInfo,
    _get_active_tickers,
    _job_ingest_and_extract,
    _job_reflect_weekly,
    _job_run_predictions,
    _job_score_daily,
    create_scheduler,
    get_schedule_info,
    run_orchestrator,
)


class _ConnProxy:
    """Wrap a sqlite3.Connection so close() is a no-op (fixture cleans it up)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def close(self) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)


@pytest.fixture()
def mock_conn(mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """Patch get_conn so job functions use the test DB without closing it."""
    proxy = _ConnProxy(mem_db)
    monkeypatch.setattr("stock.orchestrator.get_conn", lambda: proxy)
    return mem_db


def _add_watchlist_ticker(conn: sqlite3.Connection, ticker: str, active: int = 1) -> None:
    """Insert a ticker into the watchlist table."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES (?, ?, ?)",
        (ticker, now, active),
    )
    conn.commit()


# -- _get_active_tickers tests -----------------------------------------------


def test_get_active_tickers_from_db(mem_db: sqlite3.Connection) -> None:
    """Returns tickers from watchlist table with active=1."""
    _add_watchlist_ticker(mem_db, "AAPL")
    _add_watchlist_ticker(mem_db, "NVDA")

    result = _get_active_tickers(mem_db)

    assert result == ["AAPL", "NVDA"]


def test_get_active_tickers_skips_inactive(mem_db: sqlite3.Connection) -> None:
    """Tickers with active=0 are excluded."""
    _add_watchlist_ticker(mem_db, "AAPL", active=1)
    _add_watchlist_ticker(mem_db, "TSLA", active=0)

    result = _get_active_tickers(mem_db)

    assert result == ["AAPL"]
    assert "TSLA" not in result


def test_get_active_tickers_yaml_fallback(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Falls back to YAML file when DB table is empty."""
    yaml_file = tmp_path / "watchlist.yaml"
    yaml_file.write_text("tickers:\n  - msft\n  - goog\n", encoding="utf-8")
    monkeypatch.setattr("stock.orchestrator.WATCHLIST_PATH", str(yaml_file))

    result = _get_active_tickers(mem_db)

    assert result == ["MSFT", "GOOG"]


def test_get_active_tickers_empty_both(
    mem_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns empty list when DB and YAML are both empty."""
    monkeypatch.setattr("stock.orchestrator.WATCHLIST_PATH", "/nonexistent/path.yaml")

    result = _get_active_tickers(mem_db)

    assert result == []


# -- _job_ingest_and_extract tests -------------------------------------------


def test_job_ingest_and_extract_processes_all(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calls fetch_news, fetch_prices, extract_features for each ticker."""
    _add_watchlist_ticker(mock_conn, "AAPL")
    _add_watchlist_ticker(mock_conn, "NVDA")

    news_calls: list[str] = []
    prices_calls: list[str] = []
    features_calls: list[str] = []
    monkeypatch.setattr(
        "stock.orchestrator.fetch_news", lambda t, c, **kw: news_calls.append(t)
    )
    monkeypatch.setattr(
        "stock.orchestrator.fetch_prices", lambda t, c, **kw: prices_calls.append(t)
    )
    monkeypatch.setattr(
        "stock.orchestrator.extract_features", lambda t, c: features_calls.append(t)
    )

    _job_ingest_and_extract()

    assert news_calls == ["AAPL", "NVDA"]
    assert prices_calls == ["AAPL", "NVDA"]
    assert features_calls == ["AAPL", "NVDA"]


def test_job_ingest_and_extract_cost_ceiling_stops(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CostCeilingError on first ticker stops processing; second not reached."""
    _add_watchlist_ticker(mock_conn, "AAPL")
    _add_watchlist_ticker(mock_conn, "NVDA")

    monkeypatch.setattr("stock.orchestrator.fetch_news", lambda t, c, **kw: None)
    monkeypatch.setattr("stock.orchestrator.fetch_prices", lambda t, c, **kw: None)

    calls: list[str] = []

    def _raise_ceiling(t: str, c: sqlite3.Connection) -> None:
        calls.append(t)
        raise CostCeilingError("ceiling hit")

    monkeypatch.setattr("stock.orchestrator.extract_features", _raise_ceiling)

    _job_ingest_and_extract()

    # Only first ticker attempted before ceiling stopped processing
    assert calls == ["AAPL"]


def test_job_ingest_and_extract_single_error_continues(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RuntimeError on first ticker does not block second ticker."""
    _add_watchlist_ticker(mock_conn, "AAPL")
    _add_watchlist_ticker(mock_conn, "NVDA")

    call_count = {"news": 0}

    def _news_stub(t: str, c: sqlite3.Connection, **kw: object) -> None:
        call_count["news"] += 1
        if t == "AAPL":
            raise RuntimeError("network error")

    monkeypatch.setattr("stock.orchestrator.fetch_news", _news_stub)
    monkeypatch.setattr("stock.orchestrator.fetch_prices", lambda t, c, **kw: None)
    monkeypatch.setattr("stock.orchestrator.extract_features", lambda t, c: None)

    _job_ingest_and_extract()

    # Both tickers attempted despite first one failing
    assert call_count["news"] == 2


def test_job_ingest_and_extract_empty_watchlist(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No pipeline calls when watchlist is empty."""
    news_mock = MagicMock()
    monkeypatch.setattr("stock.orchestrator.fetch_news", news_mock)
    monkeypatch.setattr("stock.orchestrator.WATCHLIST_PATH", "/nonexistent/path.yaml")

    _job_ingest_and_extract()

    news_mock.assert_not_called()


# -- _job_run_predictions tests ----------------------------------------------


def test_job_run_predictions_processes_all(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calls predict_ticker for each watchlist ticker."""
    _add_watchlist_ticker(mock_conn, "AAPL")
    _add_watchlist_ticker(mock_conn, "NVDA")

    calls: list[str] = []
    mock_result = MagicMock()
    mock_result.ticker = "X"
    mock_result.direction = "up"
    mock_result.prob_up = 0.6
    mock_result.prob_up_calibrated = 0.55

    def _predict_stub(t: str, c: sqlite3.Connection) -> MagicMock:
        calls.append(t)
        mock_result.ticker = t
        return mock_result

    monkeypatch.setattr("stock.orchestrator.predict_ticker", _predict_stub)

    _job_run_predictions()

    assert calls == ["AAPL", "NVDA"]


def test_job_run_predictions_cost_ceiling_stops(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CostCeilingError stops processing remaining tickers."""
    _add_watchlist_ticker(mock_conn, "AAPL")
    _add_watchlist_ticker(mock_conn, "NVDA")

    calls: list[str] = []

    def _predict_raise(t: str, c: sqlite3.Connection) -> None:
        calls.append(t)
        raise CostCeilingError("ceiling hit")

    monkeypatch.setattr("stock.orchestrator.predict_ticker", _predict_raise)

    _job_run_predictions()

    assert calls == ["AAPL"]


def test_job_run_predictions_single_error_continues(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ValueError on one ticker continues to next."""
    _add_watchlist_ticker(mock_conn, "AAPL")
    _add_watchlist_ticker(mock_conn, "NVDA")

    calls: list[str] = []
    mock_result = MagicMock()
    mock_result.ticker = "NVDA"
    mock_result.direction = "up"
    mock_result.prob_up = 0.6
    mock_result.prob_up_calibrated = 0.55

    def _predict_stub(t: str, c: sqlite3.Connection) -> MagicMock:
        calls.append(t)
        if t == "AAPL":
            raise ValueError("bad data")
        return mock_result

    monkeypatch.setattr("stock.orchestrator.predict_ticker", _predict_stub)

    _job_run_predictions()

    assert calls == ["AAPL", "NVDA"]


def test_job_run_predictions_empty_watchlist(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No calls when watchlist is empty."""
    predict_mock = MagicMock()
    monkeypatch.setattr("stock.orchestrator.predict_ticker", predict_mock)
    monkeypatch.setattr("stock.orchestrator.WATCHLIST_PATH", "/nonexistent/path.yaml")

    _job_run_predictions()

    predict_mock.assert_not_called()


# -- _job_score_daily tests --------------------------------------------------


def test_job_score_daily_calls_score_due(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """score_due is called once with the connection."""
    mock_result = MagicMock()
    mock_result.scored = 3
    mock_result.skipped = 1
    mock_result.already_scored = 0
    score_mock = MagicMock(return_value=mock_result)
    monkeypatch.setattr("stock.orchestrator.score_due", score_mock)

    _job_score_daily()

    score_mock.assert_called_once()


def test_job_score_daily_error_logged(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """score_due raising RuntimeError does not crash the job."""
    monkeypatch.setattr(
        "stock.orchestrator.score_due", MagicMock(side_effect=RuntimeError("db error"))
    )

    # Should not raise
    _job_score_daily()


# -- _job_reflect_weekly tests -----------------------------------------------


def test_job_reflect_weekly_calls_reflect(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """reflect_weekly is called once."""
    mock_result = MagicMock()
    mock_result.version = 2
    mock_result.provider = "minimax"
    mock_result.model = "M2.5-highspeed"
    mock_result.prediction_count = 10
    reflect_mock = MagicMock(return_value=mock_result)
    monkeypatch.setattr("stock.orchestrator.reflect_weekly", reflect_mock)

    _job_reflect_weekly()

    reflect_mock.assert_called_once()


def test_job_reflect_weekly_cost_ceiling(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CostCeilingError during reflection is logged as warning, not crash."""
    monkeypatch.setattr(
        "stock.orchestrator.reflect_weekly",
        MagicMock(side_effect=CostCeilingError("ceiling hit")),
    )

    # Should not raise
    _job_reflect_weekly()


# -- create_scheduler tests -------------------------------------------------


def test_create_scheduler_has_expected_jobs() -> None:
    """Scheduler registers all F00-F19 pipeline jobs."""
    scheduler = create_scheduler()
    # 19 pre-F19 + discovery_engine = 20
    assert len(scheduler.get_jobs()) == 20


def test_create_scheduler_job_ids() -> None:
    """All expected job IDs are present."""
    scheduler = create_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    expected = {
        "ingest_and_extract",
        "run_predictions",
        "score_daily",
        "reflect_weekly",
        "web_discovery_morning",
        "web_discovery_evening",
        "pull_feedback_morning",
        "pull_feedback_evening",
        "research_push_morning",
        "research_push_evening",
        "action_queue_runner",
        "anomaly_compute",
        "insiders_pull",
        "health_check_weekly",
        "learn_from_feedback",
        "sync_to_render",
        "daily_self_review",
        "grade_and_reply",
        "thesis_verify",
        "discovery_engine",
    }
    assert job_ids == expected


def test_create_scheduler_cloud_proxy_mode_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When STOCK_MODE=cloud_proxy, the scheduler registers zero jobs."""
    from stock.config import get_settings as _get_settings

    monkeypatch.setenv("STOCK_MODE", "cloud_proxy")
    _get_settings.cache_clear()
    try:
        scheduler = create_scheduler()
        assert len(scheduler.get_jobs()) == 0
    finally:
        monkeypatch.delenv("STOCK_MODE", raising=False)
        _get_settings.cache_clear()


# -- get_schedule_info tests -------------------------------------------------


def test_get_schedule_info_format() -> None:
    """Returns ScheduleInfo with correct job names and next-run strings."""
    scheduler = create_scheduler()
    info = get_schedule_info(scheduler)

    assert isinstance(info, ScheduleInfo)
    assert len(info.jobs) == 20

    # Each entry has name and next_run keys
    for entry in info.jobs:
        assert "name" in entry
        assert "next_run" in entry
        assert entry["next_run"] != ""


# -- run_orchestrator tests --------------------------------------------------


def test_job_learn_from_feedback_routes_intents(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
    env_settings: object,
) -> None:
    """_job_learn_from_feedback dispatches question->reply and instruction->queue."""
    from stock.intent import IntentResult
    from stock.wechat_inbox import FeedbackEntry

    fake_entries = [
        FeedbackEntry(
            timestamp="2026-04-28T01:00:00", recipient="boss",
            source="manual", text="What about TER?",
        ),
        FeedbackEntry(
            timestamp="2026-04-28T01:01:00", recipient="boss",
            source="manual", text="Make notes shorter",
        ),
    ]
    monkeypatch.setattr(
        "stock.orchestrator.read_feedback_entries", lambda **kw: fake_entries
    )

    # Stub embed so we don't load sentence-transformers
    monkeypatch.setattr("stock.conversation.embed", lambda text: [0.0] * 384)

    intent_results: dict[str, IntentResult] = {
        "What about TER?": IntentResult(
            intent="question", confidence=0.9, summary="ask",
        ),
        "Make notes shorter": IntentResult(
            intent="instruction", confidence=0.9,
            summary="shorter", suggested_topic="shorter notes",
        ),
    }
    monkeypatch.setattr(
        "stock.orchestrator.intent.classify",
        lambda text, recipient, conn: intent_results[text],
    )

    monkeypatch.setattr(
        "stock.orchestrator.generate_reply",
        lambda conn, recipient, boss_reply, language=None: f"reply: {boss_reply}",
    )
    monkeypatch.setattr(
        "stock.orchestrator.prompt_rewriter.propose_rewrite",
        lambda ids, conn: [],
    )

    from stock.orchestrator import _job_learn_from_feedback

    _job_learn_from_feedback()

    # Question routed to reply path -- the orchestrator now persists the reply
    # body as a research_reports row of kind='reply' (used to be a send_message
    # call). The APK polls /channel/api/notes for these rows.
    reply_rows = mock_conn.execute(
        "SELECT body FROM research_reports WHERE kind = 'reply'"
    ).fetchall()
    assert any("TER" in row[0] for row in reply_rows)

    # Instruction routed to action_queue
    rows = mock_conn.execute(
        "SELECT topic FROM action_queue WHERE topic LIKE 'shorter%'"
    ).fetchall()
    assert len(rows) == 1


def test_run_orchestrator_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Orchestrator starts and handles KeyboardInterrupt cleanly."""
    # Patch get_conn so startup DB check works
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_conn.close = MagicMock()
    monkeypatch.setattr("stock.orchestrator.get_conn", lambda: mock_conn)

    # Patch WATCHLIST_PATH to a nonexistent path
    monkeypatch.setattr("stock.orchestrator.WATCHLIST_PATH", "/nonexistent/path.yaml")

    # Patch scheduler.start to immediately raise KeyboardInterrupt
    original_create = create_scheduler

    def _patched_create() -> BlockingScheduler:
        sched = original_create()

        def _interrupt_start(**kwargs: object) -> None:
            raise KeyboardInterrupt

        sched.start = _interrupt_start  # type: ignore[assignment]
        return sched

    monkeypatch.setattr("stock.orchestrator.create_scheduler", _patched_create)

    # Should not raise -- KeyboardInterrupt is handled gracefully
    run_orchestrator()
