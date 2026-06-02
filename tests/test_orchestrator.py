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
    TECH_DIVE_SECTORS,
    ScheduleInfo,
    _get_active_tickers,
    _job_email_daily_action_report,
    _job_ingest_and_extract,
    _job_reflect_weekly,
    _job_run_predictions,
    _job_score_daily,
    _job_weekly_qa_dive,
    _pop_next_topic,
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
    # F29: pin the ingest universe so secular themes + holdings don't bloat
    # this unit test (which is asserting on call ordering).
    monkeypatch.setattr(
        "stock.orchestrator._get_ingest_universe", lambda c: ["AAPL", "NVDA"],
    )

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
    # F28: holding scan runs after ingest; mock it so the test stays focused
    monkeypatch.setattr(
        "stock.orchestrator.alerts.scan_all_holdings", lambda c: {},
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
    monkeypatch.setattr(
        "stock.orchestrator._get_ingest_universe", lambda c: ["AAPL", "NVDA"],
    )
    monkeypatch.setattr(
        "stock.orchestrator.alerts.scan_all_holdings", lambda c: {},
    )

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
    """No pipeline calls when ingest universe is empty."""
    news_mock = MagicMock()
    monkeypatch.setattr("stock.orchestrator.fetch_news", news_mock)
    # F29 ingest universe pulls from watchlist + holdings + secular_themes;
    # pin to empty for this no-op test.
    monkeypatch.setattr("stock.orchestrator._get_ingest_universe", lambda c: [])

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


# -- _job_weekly_qa_dive tests (F40) ----------------------------------------


def test_job_weekly_qa_dive_iterates_top5(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F40 calls qa_deepdive.run_and_persist for each top-FWP candidate."""
    from stock.discovery_engine import CandidateScore

    fake_candidates = [
        CandidateScore(
            ticker=t, fwp=0.7 - i * 0.05, fwp_pre_gate=0.7 - i * 0.05,
            qap_gate=True, components={"insider": 0.4, "novelty": 0.6},
            score_at="2026-05-05T22:00:00+00:00",
        )
        for i, t in enumerate(["ACMR", "VKTX", "BE", "AOSL", "RXRX"])
    ]
    monkeypatch.setattr(
        "stock.discovery_engine.list_candidates",
        lambda conn, **kwargs: fake_candidates,
    )

    calls: list[str] = []
    def fake_run_and_persist(*, ticker, seed_thesis, conn, rounds):
        calls.append(ticker)
        from stock.qa_deepdive import QADeepDive
        return QADeepDive(
            ticker=ticker, seed_thesis=seed_thesis, rounds=[],
            created_at="2026-05-05T22:00:00+00:00", research_id=None,
        )

    monkeypatch.setattr("stock.qa_deepdive.run_and_persist", fake_run_and_persist)

    _job_weekly_qa_dive()

    assert calls == ["ACMR", "VKTX", "BE", "AOSL", "RXRX"]


def test_job_weekly_qa_dive_skips_when_no_candidates(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F40 logs and exits when discovery_engine has no candidates -- no crash."""
    monkeypatch.setattr(
        "stock.discovery_engine.list_candidates", lambda conn, **kwargs: [],
    )
    # If this raises, test fails.
    _job_weekly_qa_dive()


def test_job_weekly_qa_dive_continues_on_per_ticker_failure(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bad qa_deepdive call doesn't stop the rest of the loop."""
    from stock.discovery_engine import CandidateScore

    monkeypatch.setattr(
        "stock.discovery_engine.list_candidates",
        lambda conn, **kwargs: [
            CandidateScore(ticker="A", fwp=0.7, fwp_pre_gate=0.7, qap_gate=True,
                           components={}, score_at=""),
            CandidateScore(ticker="B", fwp=0.6, fwp_pre_gate=0.6, qap_gate=True,
                           components={}, score_at=""),
        ],
    )
    seen: list[str] = []
    def fake_run_and_persist(*, ticker, seed_thesis, conn, rounds):
        seen.append(ticker)
        if ticker == "A":
            raise RuntimeError("boom on A")
        from stock.qa_deepdive import QADeepDive
        return QADeepDive(
            ticker=ticker, seed_thesis=seed_thesis, rounds=[],
            created_at="2026-05-05T22:00:00+00:00", research_id=None,
        )

    monkeypatch.setattr("stock.qa_deepdive.run_and_persist", fake_run_and_persist)

    _job_weekly_qa_dive()

    assert seen == ["A", "B"]  # B was attempted despite A failing


# -- create_scheduler tests -------------------------------------------------


def test_create_scheduler_has_expected_jobs() -> None:
    """Scheduler registers all F00-F46 pipeline jobs.

    19 + backup_db (F33) + uoa_scan (F36) + smallcap_scan (F38)
    + ai_loop (F39) + weekly_qa_dive (F40) + weekly_tech_dive (F43)
    + company_dd_dive (F44) + weekly_entry_scan (F45)
    + post_close_snapshot (F46) + daily_action_email
    + intraday holding move alerts + warning_dashboard_publish
    + broker_snapshot_import + stop_order_propose
    + broker_positions_pull = 34.
    """
    scheduler = create_scheduler()
    assert len(scheduler.get_jobs()) == 34


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
        "research_push_morning",
        "research_push_evening",
        "daily_action_email",
        "action_queue_runner",
        "anomaly_compute",
        "intraday_holding_move_alerts",
        "insiders_pull",
        "health_check_weekly",
        "learn_from_feedback",
        "sync_to_render",
        "warning_dashboard_publish",
        "broker_snapshot_import",
        "daily_self_review",
        "grade_and_reply",
        "thesis_verify",
        "discovery_engine",
        "verify_tracked_events",
        "backup_db",
        "uoa_scan",
        "smallcap_scan",
        "ai_loop_measure",
        "weekly_qa_dive",
        "weekly_tech_dive",
        "company_dd_dive",
        "weekly_entry_scan",
        "post_close_snapshot",
        "stop_order_propose",
        "broker_positions_pull",
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
    assert len(info.jobs) == 34

    # Each entry has name and next_run keys
    for entry in info.jobs:
        assert "name" in entry
        assert "next_run" in entry
        assert entry["next_run"] != ""


def test_job_email_daily_action_report_sends_latest_daily(
    mock_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The daily email job sends the latest daily research note."""
    sent: dict[str, str] = {}

    mock_conn.execute(
        "INSERT INTO research_reports (kind, body, cost_usd, created_at)"
        " VALUES ('daily', 'Do X today', 0, '2026-05-25T14:30:00+00:00')"
    )
    mock_conn.commit()

    def fake_send_email(*, subject: str, body: str, to_addr: str | None = None):
        sent["subject"] = subject
        sent["body"] = body
        return MagicMock(sent=True, detail="sent")

    monkeypatch.setattr("stock.orchestrator.emailer.send_email", fake_send_email)

    _job_email_daily_action_report()

    assert "STOCK daily action report" in sent["subject"]
    assert sent["body"] == "Do X today"


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


# -- tech-dive sector rotation + phase tests ---------------------------------


def test_tech_dive_sectors_include_buyer_side_and_space() -> None:
    """The weekly rotation must give airtime to ai_demand and space_tech."""
    assert "ai_demand" in TECH_DIVE_SECTORS
    assert "space_tech" in TECH_DIVE_SECTORS
    # Legacy three sectors stay covered.
    for s in ("information", "biopharma_ai", "energy"):
        assert s in TECH_DIVE_SECTORS


def test_pop_next_topic_returns_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """_pop_next_topic returns (sector, topic, phase) and defaults phase to mature."""
    import yaml

    queue = tmp_path / "topic_queue.yaml"
    queue.write_text(yaml.safe_dump({"topics": [
        {"sector": "ai_demand", "topic": "buyer side dive", "enabled": True,
         "last_run": "", "phase": "emerging"},
        {"sector": "information", "topic": "no-phase topic", "enabled": True,
         "last_run": ""},
    ]}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr("stock.orchestrator.TOPIC_QUEUE_PATH", str(queue))

    sector, topic, phase = _pop_next_topic("ai_demand")
    assert sector == "ai_demand"
    assert topic == "buyer side dive"
    assert phase == "emerging"

    # Topic without an explicit phase defaults to mature.
    _, _, default_phase = _pop_next_topic("information")
    assert default_phase == "mature"

    # last_run was written back so the next call rotates.
    data = yaml.safe_load(queue.read_text(encoding="utf-8"))
    assert data["topics"][0]["last_run"] != ""


def test_pop_next_topic_empty_sector_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import yaml

    queue = tmp_path / "topic_queue.yaml"
    queue.write_text(yaml.safe_dump({"topics": [
        {"sector": "information", "topic": "x", "enabled": True, "last_run": ""},
    ]}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr("stock.orchestrator.TOPIC_QUEUE_PATH", str(queue))

    assert _pop_next_topic("ai_demand") is None
