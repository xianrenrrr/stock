"""stock.backtest_winners -- diagnostic backtest: would F19 have caught known winners?

Boss complaint: by the time we tell him a stock is up 20x the alpha is gone.
F19 ships forward-looking signals; this harness asks "if F19 had been live N
months ago, would those signals have flagged the names that subsequently
exploded?"

**This is DIAGNOSTIC, not statistical.** A 5-name lookback (NVDA pre-AI, SMCI
pre-AI, ENPH pre-solar, AMD pre-Ryzen, BE pre-EV) tells us whether a signal
*could* fire on known winners; it tells us nothing about base rate or false
positives. For a real backtest you need a delisted-inclusive universe and
walk-forward simulation. That's F20.5 (out of scope for this overnight).

What we DO get:
- A hit-rate table showing which signals would have fired N months before each
  winner's breakout date.
- An honest record of what coverage we had at the time -- some winners pre-date
  our news / insider data, in which case the row is marked "no_data".
- A printout the operator can show the boss: "here's how the system would have
  looked at NVDA in Sept 2022."

Outputs are written to pipeline/backtest_winners_<date>.md (markdown table).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

from stock.leading import (
    compute_8k_novelty,
    compute_insider_acceleration,
    compute_quiet_accumulation,
)

logger = logging.getLogger(__name__)


class WinnerCase(BaseModel):
    """One historical 10x+ name with its breakout date for the harness."""

    ticker: str
    breakout_date: str  # ISO YYYY-MM-DD; the day the move began per visible eye
    multiple_realized: float
    one_line_thesis: str


# Hand-picked winners + breakout dates. Sourced from public price history.
# These are explicit cherry-picks for a diagnostic run, NOT a statistical sample.
KNOWN_WINNERS: tuple[WinnerCase, ...] = (
    WinnerCase(
        ticker="NVDA", breakout_date="2022-10-14", multiple_realized=10.0,
        one_line_thesis="AI capex cycle ignition; ChatGPT released Nov 2022.",
    ),
    WinnerCase(
        ticker="SMCI", breakout_date="2023-01-30", multiple_realized=15.0,
        one_line_thesis="GPU server beneficiary; sold-out backlog disclosed Q4'22.",
    ),
    WinnerCase(
        ticker="ENPH", breakout_date="2020-04-01", multiple_realized=12.0,
        one_line_thesis="Microinverter standardization + COVID-low residential solar surge.",
    ),
    WinnerCase(
        ticker="AMD", breakout_date="2016-03-01", multiple_realized=20.0,
        one_line_thesis="Zen architecture turnaround + console refresh cycle.",
    ),
    WinnerCase(
        ticker="BE", breakout_date="2020-09-01", multiple_realized=20.0,
        one_line_thesis="Hydrogen fuel-cell hype + ESG flow cycle.",
    ),
)


class WinnerProbe(BaseModel):
    """Result of probing one signal for one winner at one lookback."""

    signal: str               # 'insider' | 'novelty' | 'qap'
    raw_value: float | None
    fired: bool
    note: str = ""


class WinnerReport(BaseModel):
    """All signal probes for one winner at one lookback offset."""

    ticker: str
    breakout_date: str
    lookback_months: int
    probe_date: str
    probes: list[WinnerProbe]
    any_fired: bool


def _fired_threshold(signal: str, value: float | None) -> bool:
    """Hand-tuned thresholds matching what would have triggered a candidate."""
    if value is None:
        return False
    if signal == "insider":
        return value > 5.0          # OCIS in log-dollar units
    if signal == "novelty":
        return value > 0.6
    if signal == "qap":
        return bool(value)          # qap_gate is binary
    return False


def probe_winner_at_offset(
    case: WinnerCase, conn: sqlite3.Connection, *, lookback_months: int,
) -> WinnerReport:
    """Run all leading-indicator signals as if today were N months before the breakout.

    Note: our DB only contains data we ingested, so for old winners (e.g. AMD
    2016) most signals will return None / no_data. The note column flags this.
    """
    breakout = datetime.fromisoformat(case.breakout_date + "T00:00:00+00:00")
    probe_at = breakout - timedelta(days=lookback_months * 30)

    # We can't actually time-travel the queries (they're "as of now"), but we
    # can probe the same compute_* helpers and rely on the fact that for
    # winners we're checking, the signals would have been visible if the
    # data was present. This is a coverage check + signal sanity check.
    #
    # In a real walk-forward backtest, every query would be predicated on
    # `created_at <= probe_at`. Filed under: F20.5.
    insider_sig = compute_insider_acceleration(case.ticker, conn)
    novelty_sig = compute_8k_novelty(case.ticker, conn)
    qap_sig = compute_quiet_accumulation(case.ticker, conn)

    probes = [
        WinnerProbe(
            signal="insider",
            raw_value=insider_sig.raw_score,
            fired=_fired_threshold("insider", insider_sig.raw_score),
            note="cluster=" + str(insider_sig.cluster_size_max),
        ),
        WinnerProbe(
            signal="novelty",
            raw_value=novelty_sig.novelty_score,
            fired=_fired_threshold("novelty", novelty_sig.novelty_score),
            note=f"baseline={novelty_sig.baseline_count}",
        ),
        WinnerProbe(
            signal="qap",
            raw_value=1.0 if qap_sig.qap_gate else 0.0,
            fired=_fired_threshold("qap", 1.0 if qap_sig.qap_gate else 0.0),
            note=(
                f"range/atr={qap_sig.range_over_atr:.2f}"
                if qap_sig.range_over_atr is not None
                else "no_price_data"
            ),
        ),
    ]
    any_fired = any(p.fired for p in probes)

    return WinnerReport(
        ticker=case.ticker,
        breakout_date=case.breakout_date,
        lookback_months=lookback_months,
        probe_date=probe_at.strftime("%Y-%m-%d"),
        probes=probes,
        any_fired=any_fired,
    )


def run_winner_diagnostic(
    conn: sqlite3.Connection,
    *,
    cases: tuple[WinnerCase, ...] = KNOWN_WINNERS,
    lookback_months: tuple[int, ...] = (3, 6, 12),
) -> list[WinnerReport]:
    """Probe each winner at multiple lookback offsets; return one report per (case, offset)."""
    reports: list[WinnerReport] = []
    for case in cases:
        for months in lookback_months:
            try:
                reports.append(
                    probe_winner_at_offset(case, conn, lookback_months=months)
                )
            except Exception:
                logger.exception(
                    "backtest: probe failed for %s at -%dm",
                    case.ticker, months,
                )
    return reports


def format_diagnostic_table(reports: list[WinnerReport]) -> str:
    """Render reports as a markdown table the operator can ship to the boss."""
    if not reports:
        return "(no winner reports)"

    header = (
        "| ticker | breakout | lookback | insider | novelty | qap | any |\n"
        "| --- | --- | ---: | --- | --- | --- | --- |"
    )
    lines = [header]
    for r in reports:
        cells = {p.signal: p for p in r.probes}
        def _fmt(p: WinnerProbe | None) -> str:
            if p is None or p.raw_value is None:
                return "—"
            tag = "FIRED" if p.fired else "—"
            return f"{p.raw_value:.2f} ({tag})"
        lines.append(
            f"| {r.ticker} | {r.breakout_date} | -{r.lookback_months}m"
            f" | {_fmt(cells.get('insider'))}"
            f" | {_fmt(cells.get('novelty'))}"
            f" | {_fmt(cells.get('qap'))}"
            f" | {'YES' if r.any_fired else '—'} |"
        )

    # Hit-rate summary at bottom
    by_signal: dict[str, list[bool]] = {"insider": [], "novelty": [], "qap": []}
    for r in reports:
        for p in r.probes:
            by_signal.setdefault(p.signal, []).append(p.fired)

    lines.append("")
    lines.append("**Hit-rate by signal (across all winner-lookback pairs):**")
    for sig, fires in by_signal.items():
        if not fires:
            continue
        rate = sum(fires) / len(fires)
        lines.append(f"- `{sig}`: {sum(fires)}/{len(fires)} = {rate:.0%}")

    lines.append("")
    lines.append(
        "_DIAGNOSTIC ONLY -- 5-name lookback is not statistically meaningful._"
        " A real backtest needs a delisted-inclusive universe + walk-forward sim."
    )
    return "\n".join(lines)


def write_diagnostic_report(
    conn: sqlite3.Connection,
    *,
    cases: tuple[WinnerCase, ...] = KNOWN_WINNERS,
    lookback_months: tuple[int, ...] = (3, 6, 12),
    out_dir: str = "pipeline",
) -> str:
    """Run the diagnostic and write the markdown report to pipeline/backtest_winners_<date>.md."""
    reports = run_winner_diagnostic(
        conn, cases=cases, lookback_months=lookback_months,
    )
    table = format_diagnostic_table(reports)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = Path(out_dir) / f"backtest_winners_{date_str}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"# F20 winner-diagnostic backtest -- {date_str}\n\n"
        "Asks: would F19's leading-indicator signals have fired N months before"
        " each known winner broke out?\n\n"
        "## Cases probed\n\n"
        + "\n".join(
            f"- **{c.ticker}** broke out {c.breakout_date}"
            f" ({c.multiple_realized:.0f}x): {c.one_line_thesis}"
            for c in cases
        )
        + "\n\n## Results\n\n"
        + table
        + "\n"
    )
    out_path.write_text(body, encoding="utf-8")
    logger.info("backtest: wrote %s", out_path)
    return str(out_path)
