"""scripts/post_close_snapshot.py -- post-close (4:05 PM ET) volume + price refresh.

Boss directive 2026-05-08 EOD: 'when checking volume make sure you are checking
real time data, comparing to previous days same time. Or whenever we need
volume we check at 4:01 PM Eastern Time.'

This script:
1. Re-fetches today's daily bar from yfinance (final close + final volume)
2. Compares today's volume vs trailing 20-day average per conviction ticker
3. Flags anomalies: vol > 2x avg = unusual spike; vol < 0.5x avg = unusual quiet
4. Persists a research_reports kind='post_close_snapshot' row for APK delivery

Run via:
  python scripts/post_close_snapshot.py
Or scheduled via orchestrator F46 cron at 20:05 UTC (4:05 PM ET, 5 min after
close so yfinance has the final settled bar).
"""
from __future__ import annotations

import io
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stock.db import get_conn
from stock.ingest import fetch_prices
from stock.tech_trends import load_conviction


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def main() -> int:
    conn = get_conn()
    # Pull every conviction-watchlist ticker (US-only since A-shares need different logic)
    conviction = load_conviction(enabled_only=True)
    us_tickers = [n.ticker for n in conviction if "." not in n.ticker]
    a_share = [n.ticker for n in conviction if ".SS" in n.ticker or ".SZ" in n.ticker or ".SH" in n.ticker]
    print(f"Refreshing {len(us_tickers)} US tickers + {len(a_share)} A-share tickers...")

    inserted = 0
    fetch_errs = []
    for t in us_tickers + a_share:
        try:
            r = fetch_prices(t, conn, days=2)
            inserted += r.inserted
        except Exception as e:  # noqa: BLE001
            fetch_errs.append((t, type(e).__name__))

    print(f"New rows inserted: {inserted}; errors: {len(fetch_errs)}")
    if fetch_errs:
        for t, err in fetch_errs[:5]:
            print(f"  {t}: {err}")

    # Volume comparison report
    spikes = []
    quiets = []
    rows_to_render = []
    for t in sorted(us_tickers + a_share):
        rows = conn.execute(
            "SELECT ts, c, v FROM prices WHERE ticker = ?"
            " ORDER BY ts DESC LIMIT 21",
            (t,),
        ).fetchall()
        if len(rows) < 5:
            continue
        today_ts, today_c, today_v = rows[0]
        prior = [r[2] for r in rows[1:21]]
        avg_v = sum(prior) / len(prior) if prior else 0
        ratio = today_v / avg_v if avg_v else 0
        yest_c = rows[1][1] if len(rows) > 1 else today_c
        pct = (today_c / yest_c - 1) * 100 if yest_c else 0

        rows_to_render.append((t, today_ts, today_c, today_v, avg_v, ratio, pct))
        if ratio >= 2.0:
            spikes.append((t, today_ts, today_v, avg_v, ratio, pct))
        elif ratio <= 0.5:
            quiets.append((t, today_ts, today_v, avg_v, ratio, pct))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_lines = [
        f"# 收盘成交量快照 / Post-close volume snapshot -- {today}",
        "",
        f"_Snapshot taken at {datetime.now(timezone.utc).isoformat(timespec='minutes')} "
        f"UTC (post 4 PM ET close). Compared today's final volume vs trailing 20-day "
        f"average for {len(rows_to_render)} conviction tickers._",
        "",
        "---",
        "",
    ]

    if spikes:
        out_lines.append(f"## 🚨 成交量异常放大 / Volume spikes (>=2x avg) -- {len(spikes)} names")
        out_lines.append("")
        out_lines.append("| Ticker | Date | Today vol | 20d avg | Ratio | Px chg |")
        out_lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
        for t, ts, v, avg, ratio, pct in sorted(spikes, key=lambda x: -x[4]):
            out_lines.append(
                f"| **{t}** | {ts[:10]} | {_fmt_int(int(v))} | "
                f"{_fmt_int(int(avg))} | **{ratio:.2f}x** | {pct:+.2f}% |"
            )
        out_lines.append("")

    if quiets:
        out_lines.append(f"## 💤 成交量异常清淡 / Volume quiet (<=0.5x avg) -- {len(quiets)} names")
        out_lines.append("")
        out_lines.append("| Ticker | Date | Today vol | 20d avg | Ratio | Px chg |")
        out_lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
        for t, ts, v, avg, ratio, pct in sorted(quiets, key=lambda x: x[4]):
            out_lines.append(
                f"| {t} | {ts[:10]} | {_fmt_int(int(v))} | "
                f"{_fmt_int(int(avg))} | **{ratio:.2f}x** | {pct:+.2f}% |"
            )
        out_lines.append("")

    # Full table for completeness
    out_lines.append("## 全表 / Full conviction-list snapshot")
    out_lines.append("")
    out_lines.append("| Ticker | Date | Close | Vol | 20d avg | Ratio | Px chg |")
    out_lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for t, ts, c, v, avg, ratio, pct in sorted(rows_to_render):
        marker = "🚨" if ratio >= 2.0 else ("💤" if ratio <= 0.5 else "")
        out_lines.append(
            f"| {marker} {t} | {ts[:10]} | ${c:.2f} | "
            f"{_fmt_int(int(v))} | {_fmt_int(int(avg))} | "
            f"{ratio:.2f}x | {pct:+.2f}% |"
        )
    out_lines.append("")
    out_lines.append("---")
    out_lines.append("")
    out_lines.append(
        "_**How to read**: Volume ratio >= 2x = institutional accumulation OR "
        "distribution depending on price action. Combined with positive % change "
        "= bullish accumulation. Combined with negative % change = bearish "
        "distribution. Volume ratio < 0.5x with up-price = low conviction "
        "rally (rarely sustains). Cross-reference with F36 UOA scan for "
        "options confirmation._"
    )
    out_lines.append("")
    out_lines.append("_Not financial advice._")
    body = "\n".join(out_lines)

    # Persist
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO research_reports (kind, topic, body, created_at)"
        " VALUES ('post_close_snapshot', ?, ?, ?)",
        (f"收盘成交量快照 {today}", body, now),
    )
    conn.commit()
    rid = int(cur.lastrowid)
    print(f"\nPersisted research_id={rid}")
    print(f"  Spikes: {len(spikes)}, Quiets: {len(quiets)}")
    print(f"  Total scanned: {len(rows_to_render)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
