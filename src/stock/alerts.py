"""stock.alerts -- news-driven sell-trigger alerts for active holdings (F28).

Boss owns SMCI; sell-triggers in data/holdings.yaml include "margin stuck < 11%",
"auditor / 10-K compliance event", "DELL price war disclosed", etc. The news
ingest pulls headlines every 15 min during market hours; this module scans
each fresh batch for keyword patterns matching those triggers, and when one
fires for an active holding, writes a kind='alert' research_reports row that
the APK surfaces immediately.

Categories cover the sell-trigger taxonomy from holdings.yaml + generic
red flags. Each category is a list of phrase patterns (substring match,
case-insensitive, multi-language). False-positive risk is real (a headline
saying "no margin compression" still hits "margin compression"), so the
alert is INFORMATIONAL not actionable -- the operator + LLM still decide
whether to trim.

Dedup: each (ticker, news_id) pair generates at most one alert row even if
multiple categories fire. The `cloud_sync_state` table tracks the last
news ingest_at scanned per ticker so re-runs don't re-alert.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Callable

from pydantic import BaseModel

from stock import holdings

logger = logging.getLogger(__name__)

INTRADAY_HOLDING_DROP_THRESHOLD: float = -0.08
INTRADAY_HOLDING_GAIN_THRESHOLD: float = 0.12


# Sell-trigger keyword taxonomy. Phrases are matched as case-insensitive
# substrings against title + body. A single news row firing multiple
# categories produces ONE alert with all categories listed.
SELL_TRIGGER_KEYWORDS: dict[str, list[str]] = {
    "margin_compression": [
        "margin compression", "gross margin decline", "margin pressure",
        "miss on margin", "margin guidance cut", "margin warning",
        "毛利率下降", "毛利率压缩", "毛利率指引下调",
    ],
    "guidance_cut": [
        "guidance cut", "lowered guidance", "lowers guidance", "cuts forecast",
        "warns on", "profit warning", "earnings warning", "preannounce",
        "cuts outlook", "下调指引", "下调预期", "下调全年指引",
    ],
    "compliance_audit": [
        "auditor resignation", "auditor resigns", "10-K delay", "10-Q delay",
        "filing delay", "going concern", "material weakness", "restatement",
        "restate earnings", "sec investigation", "doj investigation",
        "subpoena", "delisted", "delisting risk", "noncompliance",
        "审计师辞职", "退市风险", "证监会调查",
    ],
    "fraud_legal": [
        "fraud", "fraudulent", "class action", "shareholder lawsuit",
        "criminal investigation", "indicted", "indictment", "settlement",
        "bribery", "kickback", "欺诈", "集体诉讼",
    ],
    "competition_price_war": [
        "price war", "pricing pressure", "share loss", "lost contract",
        "lost customer", "market share decline", "discounting",
        "失去客户", "价格战", "份额下降",
    ],
    "downgrade_negative": [
        "downgrade to sell", "downgrade to underperform", "downgrade to hold",
        "downgraded by", "cut to sell", "cut to underperform",
        "pt cut", "price target lowered", "target cut to",
        "下调评级", "下调目标价",
    ],
    "supply_chain_disruption": [
        "supply chain disruption", "production halt", "factory shutdown",
        "shipment delay", "yield issue", "yield problem", "recall",
        "quality issue", "stop-ship", "供应链中断", "停产", "良率问题",
    ],
    "macro_negative": [
        "recession", "stagflation", "trade war", "tariffs imposed",
        "export ban", "sanctions", "出口禁令", "制裁", "关税",
    ],
}


class HoldingAlert(BaseModel):
    """One news-driven alert row for an active holding."""

    ticker: str
    news_id: int
    news_title: str
    news_ts: str
    categories: list[str]            # which categories fired
    matched_phrases: list[str]       # the actual phrases that matched
    body_excerpt: str                # first 240 chars of news body for context


def _last_scanned_key(ticker: str) -> str:
    """cloud_sync_state key naming for per-ticker high-water-mark."""
    return f"alerts_last_scanned_{ticker.upper()}"


def _get_last_scanned_ts(conn: sqlite3.Connection, ticker: str) -> str:
    """Fetch the per-ticker last-scanned ingest_at, or epoch if first run."""
    row = conn.execute(
        "SELECT value FROM cloud_sync_state WHERE key = ?",
        (_last_scanned_key(ticker),),
    ).fetchone()
    if row:
        return str(row[0])
    return "1970-01-01T00:00:00+00:00"


def _set_last_scanned_ts(conn: sqlite3.Connection, ticker: str, ts: str) -> None:
    """Persist the new high-water-mark so next scan only sees fresher rows."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO cloud_sync_state (key, value, updated_at)"
        " VALUES (?, ?, ?) ON CONFLICT(key)"
        " DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (_last_scanned_key(ticker), ts, now),
    )
    conn.commit()


def _match_keywords(text: str) -> tuple[list[str], list[str]]:
    """Return (categories, matched_phrases) for any sell-trigger hit.

    Substring + case-insensitive. A headline can match multiple categories;
    we de-dupe within each list.
    """
    if not text:
        return [], []
    lower = text.lower()
    cats: list[str] = []
    hits: list[str] = []
    for cat, patterns in SELL_TRIGGER_KEYWORDS.items():
        for phrase in patterns:
            if phrase.lower() in lower:
                if cat not in cats:
                    cats.append(cat)
                if phrase not in hits:
                    hits.append(phrase)
    return cats, hits


def scan_ticker_news_for_triggers(
    conn: sqlite3.Connection, ticker: str, *, max_rows: int = 50,
) -> list[HoldingAlert]:
    """Scan news for one ticker since the last high-water-mark; return alerts.

    Updates the high-water-mark on success. Idempotent on re-runs (returns
    [] if nothing newer than last scan).
    """
    since_ts = _get_last_scanned_ts(conn, ticker)
    rows = conn.execute(
        "SELECT id, title, body, ts, ingested_at FROM news"
        " WHERE ticker = ? AND ingested_at > ?"
        " ORDER BY ingested_at ASC LIMIT ?",
        (ticker.upper(), since_ts, max_rows),
    ).fetchall()
    if not rows:
        return []

    alerts: list[HoldingAlert] = []
    last_seen = since_ts
    for nid, title, body, ts, ingested_at in rows:
        last_seen = max(last_seen, str(ingested_at))
        combined = f"{title or ''}\n{body or ''}"
        cats, hits = _match_keywords(combined)
        if not cats:
            continue
        alerts.append(HoldingAlert(
            ticker=ticker.upper(),
            news_id=int(nid),
            news_title=str(title or "")[:240],
            news_ts=str(ts or ""),
            categories=cats,
            matched_phrases=hits[:8],   # cap to keep payload tight
            body_excerpt=str(body or "")[:240].replace("\n", " "),
        ))

    if last_seen != since_ts:
        _set_last_scanned_ts(conn, ticker, last_seen)
    return alerts


def _format_alert_body(ticker: str, alerts: list[HoldingAlert]) -> str:
    """Compose the markdown body for a kind='alert' research_reports row."""
    lines: list[str] = []
    lines.append(f"# ⚠️ 持仓警报 / Holding alert -- {ticker}")
    lines.append("")
    lines.append(
        f"News scan flagged {len(alerts)} headline(s) matching sell-trigger"
        f" keywords on your active holding **{ticker}**. Review and decide:"
        f" trim, exit, or override (false positive)."
    )
    lines.append("")
    for alert in alerts:
        cats_str = ", ".join(f"`{c}`" for c in alert.categories)
        phrases = ", ".join(f'"{p}"' for p in alert.matched_phrases[:5])
        lines.append(f"## [{alert.news_ts[:16]}] {alert.news_title[:200]}")
        lines.append(f"- Triggered categories: {cats_str}")
        lines.append(f"- Matched phrases: {phrases}")
        lines.append(f"- Excerpt: {alert.body_excerpt}")
        lines.append("")
    lines.append("---")
    lines.append(
        "_Sell-trigger keyword scan from F28. False positives are possible "
        "(headline negation isn't checked). Cross-reference with the next "
        "morning research note's holdings_block before acting._"
    )
    lines.append("")
    lines.append("Not financial advice.")
    return "\n".join(lines)


def write_alert_note(
    conn: sqlite3.Connection, ticker: str, alerts: list[HoldingAlert],
) -> int | None:
    """Persist a kind='alert' research_reports row for the APK to surface.

    Returns the new row id, or None if alerts list was empty.
    """
    if not alerts:
        return None
    body = _format_alert_body(ticker, alerts)
    cats_summary = ",".join(sorted({c for a in alerts for c in a.categories}))
    topic = f"{ticker} sell-trigger: {cats_summary}"[:200]
    cursor = conn.execute(
        "INSERT INTO research_reports"
        " (kind, topic, layer_focus, body, cost_usd, created_at)"
        " VALUES ('alert', ?, NULL, ?, 0, ?)",
        (topic, body, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    rid = int(cursor.lastrowid or 0)
    logger.info(
        "alerts: wrote kind=alert id=%d for %s (%d headline matches, cats=%s)",
        rid, ticker, len(alerts), cats_summary,
    )
    return rid


def _stop_breach_key(ticker: str) -> str:
    """cloud_sync_state key naming for the stop-breach high-water-mark.
    We track the last close that triggered an alert per ticker so we don't
    re-alert on every tick after a single breach event."""
    return f"alerts_stop_breach_last_alerted_{ticker.upper()}"


def _intraday_move_key(ticker: str, date_part: str) -> str:
    """Dedup key for live holding crash/spike alerts.

    Value stores the largest severity bucket already alerted today. This allows
    one re-alert if a -9% drop worsens to -15% or -20%, but avoids every-5-min
    spam at the same severity.
    """
    return f"alerts_intraday_move_last_bucket_{ticker.upper()}_{date_part}"


def _live_pct_change_yfinance(ticker: str) -> tuple[float, float, float] | None:
    """Return (last_price, previous_close, pct_change) from yfinance.

    This intentionally uses quote-style data instead of the local `prices`
    table. The daily prices table often does not settle until after close, but
    holding crash alerts must fire intraday.
    """
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        fast = getattr(t, "fast_info", None)
        last = getattr(fast, "last_price", None) if fast is not None else None
        prev = getattr(fast, "previous_close", None) if fast is not None else None
        if last is not None and prev not in (None, 0):
            last_f = float(last)
            prev_f = float(prev)
            return last_f, prev_f, (last_f - prev_f) / prev_f

        hist = t.history(period="2d", interval="1d")
        if hist is not None and len(hist) >= 2:
            prev_f = float(hist["Close"].iloc[-2])
            last_f = float(hist["Close"].iloc[-1])
            if prev_f:
                return last_f, prev_f, (last_f - prev_f) / prev_f
    except Exception:
        logger.debug("live pct lookup failed for %s", ticker, exc_info=True)
    return None


LiveMoveProvider = Callable[[str], tuple[float, float, float] | None]


def scan_holdings_for_intraday_moves(
    conn: sqlite3.Connection,
    *,
    provider: LiveMoveProvider | None = None,
    as_of: datetime | None = None,
) -> dict[str, str]:
    """Fire an alert when an active holding makes a large live move.

    This is the guardrail that should have caught a holding like AMBA dropping
    ~20% intraday even when cost_basis is unknown and the close-based stop scan
    has not run yet.
    """
    quote_provider = provider or _live_pct_change_yfinance
    now_dt = as_of or datetime.now(timezone.utc)
    now = now_dt.isoformat()
    date_part = now_dt.strftime("%Y-%m-%d")
    out: dict[str, str] = {}

    for h in holdings.list_holdings(conn, active_only=True):
        ticker = h.ticker.upper()
        quote = quote_provider(ticker)
        if quote is None:
            continue
        last_price, previous_close, pct_change = quote

        if (
            pct_change > INTRADAY_HOLDING_DROP_THRESHOLD
            and pct_change < INTRADAY_HOLDING_GAIN_THRESHOLD
        ):
            continue

        severity_bucket = int(abs(pct_change) // 0.05) * 5
        min_bucket = 5
        if severity_bucket < min_bucket:
            severity_bucket = min_bucket
        key = _intraday_move_key(ticker, date_part)
        row = conn.execute(
            "SELECT value FROM cloud_sync_state WHERE key = ?",
            (key,),
        ).fetchone()
        last_bucket = int(float(row[0])) if row else 0
        if severity_bucket <= last_bucket:
            continue

        conn.execute(
            "INSERT INTO cloud_sync_state (key, value, updated_at)"
            " VALUES (?, ?, ?) ON CONFLICT(key)"
            " DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, str(severity_bucket), now),
        )

        direction = "DROP" if pct_change < 0 else "SPIKE"
        pct_s = f"{pct_change * 100:+.1f}%"
        body = "\n".join(
            [
                f"# 🚨 Intraday holding {direction} alert -- {ticker}",
                "",
                f"Active holding **{ticker}** moved **{pct_s} intraday**.",
                "",
                "## Live quote",
                f"- last price: ${last_price:.2f}",
                f"- previous close: ${previous_close:.2f}",
                f"- move: {pct_s}",
                f"- quantity tracked: {h.qty:g}",
                f"- cost basis: ${h.cost_basis:.2f}" if h.cost_basis > 0 else "- cost basis: unset",
                "",
                "## Why this fired",
                f"- Drop threshold: {INTRADAY_HOLDING_DROP_THRESHOLD * 100:.0f}%",
                f"- Spike threshold: +{INTRADAY_HOLDING_GAIN_THRESHOLD * 100:.0f}%",
                "- This alert uses live quote data, not only settled daily close.",
                "",
                "## Immediate operator checklist",
                "- Check whether the move is earnings/guidance/downgrade driven.",
                "- Compare with today's daily note and the current stop level.",
                "- Decide: hold, trim, exit, or wait for close confirmation.",
                "",
                "Not financial advice.",
            ]
        )
        cursor = conn.execute(
            "INSERT INTO research_reports"
            " (kind, topic, layer_focus, body, cost_usd, created_at)"
            " VALUES ('alert', ?, 'intraday_holding_move', ?, 0, ?)",
            (f"{ticker} intraday {direction}: {pct_s}", body, now),
        )
        conn.commit()
        rid = int(cursor.lastrowid or 0)
        msg = f"{direction} {pct_s} last=${last_price:.2f} prev=${previous_close:.2f} -> alert id={rid}"
        out[ticker] = msg
        logger.warning("ALERT: %s intraday holding move %s", ticker, msg)

    return out


def scan_holdings_for_stop_breach(
    conn: sqlite3.Connection,
) -> dict[str, str]:
    """F32: write a kind='alert' row when latest close breaches a holding's stop.

    Two breach checks per holding (alert fires if EITHER triggers):
      1. **Cost-anchored breach** (primary): latest close < cost_basis * 0.85.
         Fixed -15% mechanical stop from entry; doesn't drift as the F24
         stop-helper adapts to fresh lows. Skipped if cost_basis == 0
         (placeholder pending operator update).
      2. **Recommended-stop breach** (secondary): latest close < F24
         recommended stop AND that stop is below entry (so the helper
         actually has a defensible level). Catches volatility-tightened
         stops the operator can't see at-a-glance.

    Idempotent: persists the alerted close in cloud_sync_state so re-runs
    at the same or higher close don't spam alerts. New alert fires only on
    a fresh lower close.

    Returns {ticker: breach_message}.
    """
    from stock.stops import compute_stop_loss

    out: dict[str, str] = {}
    active = holdings.list_holdings(conn, active_only=True)
    for h in active:
        try:
            stop = compute_stop_loss(h.ticker, conn)
            if stop.entry_price is None:
                continue

            close = stop.entry_price
            cost_stop = (h.cost_basis * 0.85) if h.cost_basis > 0 else None
            rec_stop = stop.recommended if (
                stop.recommended is not None and stop.recommended < close
            ) else None

            # Determine the "active" stop that fires the breach
            triggered_stop: float | None = None
            triggered_label: str = ""
            if cost_stop is not None and close < cost_stop:
                triggered_stop = cost_stop
                triggered_label = f"-15% from cost ${h.cost_basis:.2f}"
            elif rec_stop is not None and close < rec_stop:
                triggered_stop = rec_stop
                triggered_label = "F24 recommended stop"

            if triggered_stop is None:
                # Above all stops -- reset the high-water-mark so a future
                # breach triggers cleanly without dedup interference.
                conn.execute(
                    "DELETE FROM cloud_sync_state WHERE key = ?",
                    (_stop_breach_key(h.ticker),),
                )
                conn.commit()
                continue

            # Dedup: only re-alert if today's close is LOWER than the last alert
            row = conn.execute(
                "SELECT value FROM cloud_sync_state WHERE key = ?",
                (_stop_breach_key(h.ticker),),
            ).fetchone()
            last_alerted_close = float(row[0]) if row else float("inf")
            if close >= last_alerted_close:
                continue

            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO cloud_sync_state (key, value, updated_at)"
                " VALUES (?, ?, ?) ON CONFLICT(key)"
                " DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (_stop_breach_key(h.ticker), str(close), now),
            )

            # Compose alert body
            cost_str = f"${h.cost_basis:.2f}" if h.cost_basis > 0 else "(unset)"
            pnl_str = "(unset)"
            if h.cost_basis > 0:
                pnl_pct = (close - h.cost_basis) / h.cost_basis * 100
                pnl_str = f"{pnl_pct:+.1f}%"
            breach_pct = (triggered_stop - close) / triggered_stop * 100
            body_lines = [
                f"# 🚨 止损触发 / Stop-loss breach -- {h.ticker}",
                "",
                f"**Latest close ${close:.2f} is BELOW the {triggered_label} of "
                f"${triggered_stop:.2f}** (gap: -{breach_pct:.2f}%).",
                "",
                "## Position",
                f"- qty: {h.qty:g}",
                f"- cost basis: {cost_str}",
                f"- P&L vs cost: {pnl_str}",
                "",
                "## Stop-loss components (F24, recomputed)",
            ]
            if stop.atr_20 is not None:
                body_lines.append(f"- ATR(20): ${stop.atr_20:.2f}")
            if stop.atr_stop is not None:
                body_lines.append(f"- ATR-stop (2x): ${stop.atr_stop:.2f}")
            if stop.swing_low_30d is not None:
                body_lines.append(f"- 30d swing-low: ${stop.swing_low_30d:.2f}")
            if stop.percent_stop is not None:
                body_lines.append(f"- -15% percent stop: ${stop.percent_stop:.2f}")
            if stop.recommended is not None:
                body_lines.append(f"- **Recommended (live): ${stop.recommended:.2f}**")
            body_lines += [
                "",
                "## What this means",
                "The mechanical stop-loss was breached at the latest daily close.",
                "Either the trade thesis is broken or this is a volatility shakeout.",
                "The system does NOT auto-sell -- you decide.",
                "",
                "_Stop-loss breach alert from F32. Cross-reference today's news + the",
                "holdings_block in the next research note before acting._",
                "",
                "Not financial advice.",
            ]
            body = "\n".join(body_lines)
            cursor = conn.execute(
                "INSERT INTO research_reports"
                " (kind, topic, layer_focus, body, cost_usd, created_at)"
                " VALUES ('alert', ?, NULL, ?, 0, ?)",
                (
                    f"{h.ticker} stop-breach: ${close:.2f} < ${triggered_stop:.2f} ({triggered_label})",
                    body, now,
                ),
            )
            conn.commit()
            rid = int(cursor.lastrowid or 0)
            msg = (
                f"close=${close:.2f} stop=${triggered_stop:.2f} ({triggered_label})"
                f" breach=-{breach_pct:.1f}% -> alert id={rid}"
            )
            out[h.ticker] = msg
            logger.warning("ALERT: %s stop-loss breach %s", h.ticker, msg)
        except Exception:
            logger.exception("alerts: stop-breach scan failed for %s", h.ticker)
    return out


def scan_all_holdings(conn: sqlite3.Connection) -> dict[str, int]:
    """Scan every active holding's news for sell-triggers; write alert notes.

    Returns {ticker: alert_count} so the orchestrator can log a one-line summary.
    Best-effort: per-ticker exceptions are logged and don't abort the loop.

    Also runs the F32 stop-breach scan in the same call so a single
    orchestrator hook covers both keyword-driven AND mechanical alerts.
    """
    counts: dict[str, int] = {}
    active = holdings.list_holdings(conn, active_only=True)
    if not active:
        return counts

    for h in active:
        try:
            alerts = scan_ticker_news_for_triggers(conn, h.ticker)
            if alerts:
                rid = write_alert_note(conn, h.ticker, alerts)
                if rid is not None:
                    counts[h.ticker] = len(alerts)
        except Exception:
            logger.exception("alerts: keyword-scan failed for %s", h.ticker)

    # F32: mechanical stop-breach scan (close <= recommended stop)
    try:
        breaches = scan_holdings_for_stop_breach(conn)
        for ticker in breaches:
            counts[ticker] = counts.get(ticker, 0) + 1
    except Exception:
        logger.exception("alerts: stop-breach scan raised at top level")

    # Live quote crash/spike scan. This catches intraday holding moves before
    # yfinance's daily bar settles and before close-only anomaly jobs run.
    try:
        moves = scan_holdings_for_intraday_moves(conn)
        for ticker in moves:
            counts[ticker] = counts.get(ticker, 0) + 1
    except Exception:
        logger.exception("alerts: intraday holding move scan raised at top level")

    return counts
