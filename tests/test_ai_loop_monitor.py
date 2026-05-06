"""tests.test_ai_loop_monitor -- F39 AI commercial-loop monitor."""
from __future__ import annotations

import sqlite3

import pytest

from stock import db
from stock.ai_loop_monitor import (
    LoopHealthMeasurement,
    _classify_risk,
    format_loop_block,
    measure_one,
    measure_panel,
    overall_loop_status,
    persist,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    return db.get_conn(":memory:")


# ---- classification --------------------------------------------------------


def test_classify_risk_ok_when_no_signals() -> None:
    assert _classify_risk(decel=0.02, margin_compression=0.01) == "ok"


def test_classify_risk_mild_on_decel_only() -> None:
    assert _classify_risk(decel=-0.07, margin_compression=0.01) == "mild"


def test_classify_risk_mild_on_margin_only() -> None:
    assert _classify_risk(decel=0.0, margin_compression=-0.03) == "mild"


def test_classify_risk_severe_on_severe_decel() -> None:
    assert _classify_risk(decel=-0.20, margin_compression=0.01) == "severe"


def test_classify_risk_severe_on_severe_margin() -> None:
    assert _classify_risk(decel=0.0, margin_compression=-0.06) == "severe"


def test_classify_risk_handles_none_as_zero() -> None:
    assert _classify_risk(decel=None, margin_compression=None) == "ok"


# ---- measurement -----------------------------------------------------------


def test_measure_one_uses_provider_data() -> None:
    """Synthetic provider lets us exercise the math without yfinance."""
    def provider(_t: str):
        # latest_rev, latest_yoy, mean_yoy, latest_gm, mean_gm
        return (1.5e9, 0.10, 0.30, 0.65, 0.72)

    m = measure_one(ticker="CRM", measured_at="2026-05-05T22:00:00+00:00",
                    data_provider=provider)
    assert m.ticker == "CRM"
    assert m.quarterly_revenue_usd == 1.5e9
    assert m.quarterly_revenue_yoy == 0.10
    assert m.revenue_yoy_4q_mean == 0.30
    # Decel: 0.10 - 0.30 = -0.20 (severe)
    assert m.revenue_decel == pytest.approx(-0.20)
    # GM compression: 0.65 - 0.72 = -0.07 (severe)
    assert m.margin_compression == pytest.approx(-0.07)
    assert m.risk_flag == "severe"


def test_measure_one_handles_missing_data() -> None:
    """Provider returns Nones -> measurement still produced, flag=ok."""
    def provider(_t: str):
        return (None, None, None, None, None)

    m = measure_one(ticker="X", data_provider=provider)
    assert m.risk_flag == "ok"
    assert m.revenue_decel is None
    assert m.margin_compression is None


def test_measure_panel_iterates(conn: sqlite3.Connection) -> None:
    """Custom panel + provider produces one row per company."""
    panel = [{"ticker": "A"}, {"ticker": "B"}, {"ticker": "C"}]
    def provider(t: str):
        # B: decel -0.08 (mild), GM compression -0.01 (ok) -> mild overall
        return (1e9, 0.10, 0.18, 0.60, 0.61) if t == "B" else (1e9, 0.30, 0.30, 0.70, 0.70)

    measurements = measure_panel(panel=panel, data_provider=provider)
    assert len(measurements) == 3
    by_t = {m.ticker: m for m in measurements}
    assert by_t["A"].risk_flag == "ok"
    assert by_t["B"].risk_flag == "mild"
    assert by_t["C"].risk_flag == "ok"


# ---- aggregation -----------------------------------------------------------


def _measurement(ticker: str, flag: str) -> LoopHealthMeasurement:
    return LoopHealthMeasurement(
        ticker=ticker, measured_at="2026-05-05T22:00:00+00:00",
        quarterly_revenue_usd=None, quarterly_revenue_yoy=None,
        revenue_yoy_4q_mean=None, revenue_decel=None,
        gross_margin=None, gross_margin_4q_mean=None,
        margin_compression=None, risk_flag=flag,
    )


def test_overall_status_severe_at_5plus_severe() -> None:
    measurements = [_measurement(f"X{i}", "severe") for i in range(5)]
    assert overall_loop_status(measurements) == "severe"


def test_overall_status_elevated_at_3plus_mild_or_severe() -> None:
    measurements = [_measurement(f"X{i}", "mild") for i in range(3)]
    assert overall_loop_status(measurements) == "elevated"


def test_overall_status_ok_when_below_thresholds() -> None:
    """2 mild < the 3-panel threshold -> ok (not yet elevated)."""
    measurements = [
        _measurement("A", "mild"),
        _measurement("B", "mild"),
        _measurement("C", "ok"),
    ]
    assert overall_loop_status(measurements) == "ok"


def test_overall_status_clearly_ok() -> None:
    measurements = [_measurement(f"X{i}", "ok") for i in range(5)]
    assert overall_loop_status(measurements) == "ok"


# ---- persist + render ------------------------------------------------------


def test_persist_writes_and_dedupes(conn: sqlite3.Connection) -> None:
    measurements = [_measurement("CRM", "mild"), _measurement("NOW", "severe")]
    n1 = persist(conn, measurements)
    n2 = persist(conn, measurements)  # Same measured_at -> UNIQUE blocks
    assert n1 == 2
    assert n2 == 0
    rows = conn.execute("SELECT ticker, risk_flag FROM ai_loop_health ORDER BY ticker").fetchall()
    assert rows == [("CRM", "mild"), ("NOW", "severe")]


def test_format_loop_block_empty_when_no_data(conn: sqlite3.Connection) -> None:
    assert format_loop_block(conn) == ""


def test_format_loop_block_renders_severe_panel(conn: sqlite3.Connection) -> None:
    measurements = [
        LoopHealthMeasurement(
            ticker="CRM", measured_at="2026-05-05T22:00:00+00:00",
            quarterly_revenue_usd=8e9, quarterly_revenue_yoy=0.05,
            revenue_yoy_4q_mean=0.25, revenue_decel=-0.20,
            gross_margin=0.62, gross_margin_4q_mean=0.70,
            margin_compression=-0.08, risk_flag="severe",
        ),
        _measurement("NOW", "mild"),
        _measurement("WDAY", "mild"),
    ]
    persist(conn, measurements)
    block = format_loop_block(conn)
    assert "AI 商业闭环" in block
    assert "CRM" in block
    assert "-20.0pp" in block  # decel
    assert "-8.0pp" in block   # margin compression
    assert "severe" in block
