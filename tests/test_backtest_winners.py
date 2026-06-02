"""tests.test_backtest_winners -- F20 diagnostic harness."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from stock.backtest_winners import (
    KNOWN_WINNERS,
    WinnerCase,
    format_diagnostic_table,
    probe_winner_at_offset,
    run_winner_diagnostic,
    write_diagnostic_report,
)
from stock.leading import EightKNoveltySignal, InsiderSignal, QAPSignal


def _stub_signals(insider_score: float, novelty_score: float, qap: bool):
    """Return three patched signals with the desired raw values."""
    return (
        InsiderSignal(
            ticker="X", raw_score=insider_score, distinct_filers_30d=1,
            cluster_size_max=1, opportunistic_value_usd=insider_score * 100,
            routine_value_usd=0,
        ),
        EightKNoveltySignal(
            ticker="X", novelty_score=novelty_score,
            most_recent_8k_ts="2026-01-01", baseline_count=4,
        ),
        QAPSignal(
            ticker="X", qap_gate=qap, range_over_atr=1.0, volume_ratio=0.5, bars_used=240,
        ),
    )


# -- threshold logic --


def test_probe_fires_on_high_insider(mem_db: sqlite3.Connection) -> None:
    """Insider OCIS > 5 -> 'insider' probe fires."""
    insider, novelty, qap = _stub_signals(insider_score=10.0, novelty_score=0.2, qap=False)
    with (
        patch("stock.backtest_winners.compute_insider_acceleration", return_value=insider),
        patch("stock.backtest_winners.compute_8k_novelty", return_value=novelty),
        patch("stock.backtest_winners.compute_quiet_accumulation", return_value=qap),
    ):
        report = probe_winner_at_offset(KNOWN_WINNERS[0], mem_db, lookback_months=6)
    insider_probe = next(p for p in report.probes if p.signal == "insider")
    assert insider_probe.fired is True
    assert report.any_fired is True


def test_probe_does_not_fire_on_weak_signals(mem_db: sqlite3.Connection) -> None:
    """All signals below threshold -> any_fired=False."""
    insider, novelty, qap = _stub_signals(insider_score=2.0, novelty_score=0.3, qap=False)
    with (
        patch("stock.backtest_winners.compute_insider_acceleration", return_value=insider),
        patch("stock.backtest_winners.compute_8k_novelty", return_value=novelty),
        patch("stock.backtest_winners.compute_quiet_accumulation", return_value=qap),
    ):
        report = probe_winner_at_offset(KNOWN_WINNERS[0], mem_db, lookback_months=6)
    assert report.any_fired is False


def test_probe_fires_on_qap_gate(mem_db: sqlite3.Connection) -> None:
    """QAP gate True -> qap probe fires."""
    insider, novelty, qap = _stub_signals(insider_score=0.0, novelty_score=0.0, qap=True)
    with (
        patch("stock.backtest_winners.compute_insider_acceleration", return_value=insider),
        patch("stock.backtest_winners.compute_8k_novelty", return_value=novelty),
        patch("stock.backtest_winners.compute_quiet_accumulation", return_value=qap),
    ):
        report = probe_winner_at_offset(KNOWN_WINNERS[0], mem_db, lookback_months=6)
    qap_probe = next(p for p in report.probes if p.signal == "qap")
    assert qap_probe.fired is True
    assert report.any_fired is True


# -- run_winner_diagnostic produces 1 report per (case, lookback) --


def test_run_winner_diagnostic_cardinality(mem_db: sqlite3.Connection) -> None:
    """N cases * M lookbacks -> N*M reports."""
    insider, novelty, qap = _stub_signals(insider_score=0.0, novelty_score=0.0, qap=False)
    with (
        patch("stock.backtest_winners.compute_insider_acceleration", return_value=insider),
        patch("stock.backtest_winners.compute_8k_novelty", return_value=novelty),
        patch("stock.backtest_winners.compute_quiet_accumulation", return_value=qap),
    ):
        reports = run_winner_diagnostic(
            mem_db, cases=KNOWN_WINNERS, lookback_months=(3, 6, 12),
        )
    assert len(reports) == len(KNOWN_WINNERS) * 3


# -- format_diagnostic_table --


def test_format_table_includes_headers_and_summary(mem_db: sqlite3.Connection) -> None:
    """Markdown table contains the column headers + hit-rate summary line."""
    insider, novelty, qap = _stub_signals(insider_score=10.0, novelty_score=0.7, qap=True)
    with (
        patch("stock.backtest_winners.compute_insider_acceleration", return_value=insider),
        patch("stock.backtest_winners.compute_8k_novelty", return_value=novelty),
        patch("stock.backtest_winners.compute_quiet_accumulation", return_value=qap),
    ):
        reports = run_winner_diagnostic(
            mem_db, cases=KNOWN_WINNERS[:1], lookback_months=(6,),
        )
    table = format_diagnostic_table(reports)
    assert "| ticker | breakout |" in table
    assert "Hit-rate by signal" in table
    assert "DIAGNOSTIC ONLY" in table


def test_format_table_handles_empty() -> None:
    """No reports -> placeholder string."""
    assert format_diagnostic_table([]) == "(no winner reports)"


# -- write_diagnostic_report writes a file --


def test_write_diagnostic_report_creates_markdown(
    mem_db: sqlite3.Connection, tmp_path: Path,
) -> None:
    """Report file is written to the requested out_dir with all winner cases listed."""
    insider, novelty, qap = _stub_signals(insider_score=8.0, novelty_score=0.5, qap=True)
    with (
        patch("stock.backtest_winners.compute_insider_acceleration", return_value=insider),
        patch("stock.backtest_winners.compute_8k_novelty", return_value=novelty),
        patch("stock.backtest_winners.compute_quiet_accumulation", return_value=qap),
    ):
        out_path = write_diagnostic_report(
            mem_db,
            cases=(WinnerCase(ticker="TEST", breakout_date="2024-01-01",
                              multiple_realized=10, one_line_thesis="x"),),
            lookback_months=(6,),
            out_dir=str(tmp_path),
        )
    body = Path(out_path).read_text(encoding="utf-8")
    assert "TEST" in body
    assert "broke out 2024-01-01" in body
    assert "Hit-rate by signal" in body
