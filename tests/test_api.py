"""tests.test_api -- FastAPI endpoint tests with mocked pipeline deps."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock

import pytest
import sqlite_vec
from fastapi.testclient import TestClient

from stock.config import Settings, get_settings
from stock.db import _ensure_schema
from stock.models import CostCeilingError
from stock.predict import PredictionResult


@pytest.fixture()
def mem_db(
) -> Iterator[sqlite3.Connection]:
    """Yield an in-memory SQLite connection usable across threads for FastAPI tests.

    Overrides the conftest fixture: FastAPI's TestClient dispatches handlers to a
    worker thread, so we must set check_same_thread=False.
    """
    # Build the connection directly so we control the thread flag
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")

    # Load sqlite-vec to match production schema (case_embeddings needs it)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    _ensure_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def api_client(
    mem_db: sqlite3.Connection,
    env_settings: Settings,
) -> Iterator[TestClient]:
    """Yield a TestClient with get_db_conn overridden to use the in-memory DB."""
    from stock import api as stock_api

    def override_conn() -> Iterator[sqlite3.Connection]:
        yield mem_db

    stock_api.app.dependency_overrides[stock_api.get_db_conn] = override_conn
    client = TestClient(stock_api.app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        stock_api.app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(env_settings: Settings) -> dict[str, str]:
    """Return Authorization header with the test bearer token."""
    return {"Authorization": f"Bearer {env_settings.stock_api_token}"}


def _insert_prediction(
    conn: sqlite3.Connection,
    ticker: str = "AAPL",
    direction: str = "up",
    prob_up: float = 0.7,
) -> int:
    """Insert a minimal predictions row and return the new id."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO predictions ("
        " ticker, horizon_minutes, direction, prob_up, prob_up_calibrated,"
        " expected_return_bps, confidence, rationale, key_factors_json,"
        " model_used, strategy_arm, rules_version, retrieved_case_ids,"
        " created_at, due_at, feature_context_json"
        ") VALUES (?, 390, ?, ?, ?, 50.0, 0.8, 'because', '[]',"
        " 'MiniMax-M1-80k', 'minimax_bull', NULL, NULL, ?, ?, NULL)",
        (ticker, direction, prob_up, prob_up, now, now),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)


def _insert_outcome(
    conn: sqlite3.Connection, prediction_id: int, hit: int, ret: float = 0.01
) -> None:
    """Insert a matching outcomes row for a prediction."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO outcomes (prediction_id, actual_return, direction_hit, brier, scored_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (prediction_id, ret, hit, 0.1, now),
    )
    conn.commit()


def _make_prediction_result() -> PredictionResult:
    """Return a minimal PredictionResult for on_demand mocks."""
    now = datetime.now(timezone.utc).isoformat()
    return PredictionResult(
        prediction_id=42,
        ticker="AAPL",
        direction="up",
        prob_up=0.7,
        prob_up_calibrated=0.65,
        confidence=0.8,
        rationale="because",
        created_at=now,
        due_at=now,
    )


# ---- Auth / infra ---------------------------------------------------------


def test_health_no_auth_required(api_client: TestClient) -> None:
    """GET /stock/health should succeed without any headers."""
    response = api_client.get("/stock/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["port"] == 18790


def test_missing_auth_returns_401(api_client: TestClient) -> None:
    """Protected endpoints return 401 when no Authorization header is present."""
    response = api_client.get("/stock/predict/AAPL")
    assert response.status_code == 401


def test_wrong_token_returns_401(api_client: TestClient) -> None:
    """A bearer token that does not match the configured one returns 401."""
    response = api_client.get(
        "/stock/predict/AAPL",
        headers={"Authorization": "Bearer not-the-right-token"},
    )
    assert response.status_code == 401


def test_missing_token_config_returns_503(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When STOCK_API_TOKEN is unset, protected routes return 503."""
    get_settings.cache_clear()
    monkeypatch.setenv("STOCK_API_TOKEN", "")
    response = api_client.get(
        "/stock/predict/AAPL",
        headers={"Authorization": "Bearer anything"},
    )
    assert response.status_code == 503
    get_settings.cache_clear()


def test_invalid_ticker_returns_400(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """A ticker with digits or too many chars returns 400."""
    response = api_client.get("/stock/predict/AAPL123", headers=auth_headers)
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_request"


# ---- /stock/predict --------------------------------------------------------


def test_predict_returns_latest(
    api_client: TestClient,
    mem_db: sqlite3.Connection,
    auth_headers: dict[str, str],
) -> None:
    """GET returns the most recently inserted prediction for the ticker."""
    _insert_prediction(mem_db, ticker="AAPL", direction="up", prob_up=0.6)
    latest_id = _insert_prediction(mem_db, ticker="AAPL", direction="down", prob_up=0.3)

    response = api_client.get("/stock/predict/AAPL", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["prediction_id"] == latest_id
    assert body["direction"] == "down"
    assert body["prob_up"] == pytest.approx(0.3)


def test_predict_404_when_none(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """GET returns 404 for a ticker with no predictions."""
    response = api_client.get("/stock/predict/AAPL", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"] == "no prediction"


def test_predict_ticker_case_normalized(
    api_client: TestClient,
    mem_db: sqlite3.Connection,
    auth_headers: dict[str, str],
) -> None:
    """Lowercase tickers are normalized to uppercase before lookup."""
    _insert_prediction(mem_db, ticker="AAPL")
    response = api_client.get("/stock/predict/aapl", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["ticker"] == "AAPL"


# ---- /stock/on_demand ------------------------------------------------------


def test_on_demand_calls_predict_ticker(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    """POST /stock/on_demand returns the PredictionResult body."""
    fake = MagicMock(return_value=_make_prediction_result())
    monkeypatch.setattr("stock.api.predict_ticker", fake)

    response = api_client.post(
        "/stock/on_demand", headers=auth_headers, json={"ticker": "AAPL"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["prediction_id"] == 42
    assert body["direction"] == "up"
    assert fake.call_count == 1


def test_on_demand_cost_ceiling_returns_503(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    """CostCeilingError becomes a 503 with Retry-After header."""
    monkeypatch.setattr(
        "stock.api.predict_ticker",
        MagicMock(side_effect=CostCeilingError("over budget")),
    )
    response = api_client.post(
        "/stock/on_demand", headers=auth_headers, json={"ticker": "AAPL"}
    )
    assert response.status_code == 503
    assert response.headers.get("retry-after") == "3600"
    assert response.json()["error"] == "cost_ceiling_reached"


def test_on_demand_value_error_returns_400(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    """ValueError from predict_ticker maps to 400 with detail."""
    monkeypatch.setattr(
        "stock.api.predict_ticker",
        MagicMock(side_effect=ValueError("no prices for AAPL")),
    )
    response = api_client.post(
        "/stock/on_demand", headers=auth_headers, json={"ticker": "AAPL"}
    )
    assert response.status_code == 400
    assert "no prices" in response.json()["detail"]


def test_on_demand_missing_ticker_returns_422(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Empty body triggers Pydantic validation error -> 422."""
    response = api_client.post("/stock/on_demand", headers=auth_headers, json={})
    assert response.status_code == 422


# ---- /stock/report ---------------------------------------------------------


def test_report_default_days(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """With no data, report returns zeros and None aggregates."""
    response = api_client.get("/stock/report", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 7
    assert body["total_predictions"] == 0
    assert body["scored"] == 0
    assert body["hit_rate"] is None


def test_report_custom_days(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    """?days=14 is passed through to build_report."""
    captured: dict[str, int] = {}

    def fake_report(conn: sqlite3.Connection, days: int = 7):  # type: ignore[no-untyped-def]
        captured["days"] = days
        from stock.score import ReportSummary

        return ReportSummary(
            days=days,
            total_predictions=0,
            scored=0,
            pending=0,
            hit_rate=None,
            mean_brier=None,
            best_call=None,
            worst_call=None,
            total_return_bps=0.0,
            spend_usd=0.0,
        )

    monkeypatch.setattr("stock.api.build_report", fake_report)

    response = api_client.get("/stock/report?days=14", headers=auth_headers)
    assert response.status_code == 200
    assert captured["days"] == 14


def test_report_days_out_of_range(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """days=0 and days=400 trigger FastAPI Query validation."""
    assert api_client.get("/stock/report?days=0", headers=auth_headers).status_code == 422
    assert api_client.get("/stock/report?days=400", headers=auth_headers).status_code == 422


# ---- /stock/rules ----------------------------------------------------------


def test_rules_reads_current_md(
    api_client: TestClient,
    mem_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    auth_headers: dict[str, str],
) -> None:
    """Body contains current.md text + latest DB row metadata."""
    rules_path = tmp_path / "current.md"
    rules_path.write_text("rule 1\nrule 2\n", encoding="utf-8")
    monkeypatch.setattr("stock.api.RULES_CURRENT_PATH", str(rules_path))

    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO rules (version, text, reflection_input_ids, created_at)"
        " VALUES (?, ?, ?, ?)",
        (3, "rule 1\nrule 2\n", None, now),
    )
    mem_db.commit()

    response = api_client.get("/stock/rules", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 3
    assert "rule 1" in body["text"]
    assert body["updated_at"] == now


def test_rules_empty_when_missing(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    auth_headers: dict[str, str],
) -> None:
    """Missing current.md and empty rules table -> empty text and version=None."""
    missing_path = tmp_path / "does-not-exist.md"
    monkeypatch.setattr("stock.api.RULES_CURRENT_PATH", str(missing_path))

    response = api_client.get("/stock/rules", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["version"] is None
    assert body["text"] == ""
    assert body["updated_at"] is None


# ---- /stock/watchlist ------------------------------------------------------


def test_watchlist_list_empty(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Empty watchlist returns an empty list."""
    response = api_client.get("/stock/watchlist", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["tickers"] == []
    assert body["action"] == "list"
    assert body["changed"] is False


def test_watchlist_add_inserts(
    api_client: TestClient,
    mem_db: sqlite3.Connection,
    auth_headers: dict[str, str],
) -> None:
    """action=add inserts a new active row."""
    response = api_client.post(
        "/stock/watchlist",
        headers=auth_headers,
        json={"action": "add", "ticker": "AAPL"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is True
    assert [t["ticker"] for t in body["tickers"]] == ["AAPL"]

    row = mem_db.execute("SELECT ticker, active FROM watchlist").fetchone()
    assert row == ("AAPL", 1)


def test_watchlist_add_idempotent(
    api_client: TestClient,
    mem_db: sqlite3.Connection,
    auth_headers: dict[str, str],
) -> None:
    """Adding an already-active ticker reports changed=False."""
    mem_db.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES (?, ?, 1)",
        ("AAPL", datetime.now(timezone.utc).isoformat()),
    )
    mem_db.commit()

    response = api_client.post(
        "/stock/watchlist",
        headers=auth_headers,
        json={"action": "add", "ticker": "AAPL"},
    )
    assert response.status_code == 200
    assert response.json()["changed"] is False


def test_watchlist_add_reactivates_inactive(
    api_client: TestClient,
    mem_db: sqlite3.Connection,
    auth_headers: dict[str, str],
) -> None:
    """Adding an inactive ticker flips active=1 and reports changed=True."""
    mem_db.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES (?, ?, 0)",
        ("AAPL", datetime.now(timezone.utc).isoformat()),
    )
    mem_db.commit()

    response = api_client.post(
        "/stock/watchlist",
        headers=auth_headers,
        json={"action": "add", "ticker": "AAPL"},
    )
    assert response.status_code == 200
    assert response.json()["changed"] is True
    active = mem_db.execute("SELECT active FROM watchlist WHERE ticker='AAPL'").fetchone()
    assert active[0] == 1


def test_watchlist_remove_sets_inactive(
    api_client: TestClient,
    mem_db: sqlite3.Connection,
    auth_headers: dict[str, str],
) -> None:
    """action=remove soft-deletes (active=0)."""
    mem_db.execute(
        "INSERT INTO watchlist (ticker, added_at, active) VALUES (?, ?, 1)",
        ("AAPL", datetime.now(timezone.utc).isoformat()),
    )
    mem_db.commit()

    response = api_client.post(
        "/stock/watchlist",
        headers=auth_headers,
        json={"action": "remove", "ticker": "AAPL"},
    )
    assert response.status_code == 200
    assert response.json()["changed"] is True
    active = mem_db.execute("SELECT active FROM watchlist WHERE ticker='AAPL'").fetchone()
    assert active[0] == 0


def test_watchlist_remove_missing_returns_404(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Removing an unknown ticker returns 404."""
    response = api_client.post(
        "/stock/watchlist",
        headers=auth_headers,
        json={"action": "remove", "ticker": "NVDA"},
    )
    assert response.status_code == 404


def test_watchlist_bad_action_returns_422(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Unknown action value rejected by Pydantic Literal."""
    response = api_client.post(
        "/stock/watchlist",
        headers=auth_headers,
        json={"action": "nuke", "ticker": "AAPL"},
    )
    assert response.status_code == 422


def test_watchlist_add_requires_ticker(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """action=add without ticker returns 400."""
    response = api_client.post(
        "/stock/watchlist",
        headers=auth_headers,
        json={"action": "add"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "ticker required"


# ---- /stock/calibration ----------------------------------------------------


def test_calibration_empty(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Fresh install with no scored predictions returns empty buckets."""
    response = api_client.get("/stock/calibration", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["n_samples"] == 0
    assert body["buckets"] == []
    assert body["version"] is None


def test_calibration_buckets_sorted(
    api_client: TestClient,
    mem_db: sqlite3.Connection,
    auth_headers: dict[str, str],
) -> None:
    """Buckets are sorted ascending by bin_lower with correct per-bin aggregates."""
    # Insert predictions spanning multiple bins with known hit patterns
    pid_low = _insert_prediction(mem_db, ticker="AAPL", direction="down", prob_up=0.15)
    _insert_outcome(mem_db, pid_low, hit=0)
    pid_mid = _insert_prediction(mem_db, ticker="AAPL", direction="up", prob_up=0.55)
    _insert_outcome(mem_db, pid_mid, hit=1)
    pid_high = _insert_prediction(mem_db, ticker="AAPL", direction="up", prob_up=0.85)
    _insert_outcome(mem_db, pid_high, hit=1)

    response = api_client.get("/stock/calibration", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["n_samples"] == 3

    # Buckets sorted ascending
    lowers = [b["bin_lower"] for b in body["buckets"]]
    assert lowers == sorted(lowers)

    # Verify a high-probability bucket shows mean_actual == 1.0
    high_bucket = next(b for b in body["buckets"] if b["bin_lower"] >= 0.8)
    assert high_bucket["mean_actual"] == pytest.approx(1.0)
    assert high_bucket["count"] == 1
