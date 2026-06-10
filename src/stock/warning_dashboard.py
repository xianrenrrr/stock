"""Build the boss-facing warning dashboard from local risk signals."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from stock import holdings

AI_PRODUCTION_BREADTH_TICKERS = (
    "NVDA", "AMD", "AVGO", "MRVL", "TSM", "ASML", "MU", "WDC", "STX",
    "ANET", "CRDO", "COHR", "LITE", "AAOI", "DELL", "SMCI", "VRT",
    "ETN", "GEV", "CEG", "JBL", "NVT", "CAMT", "ONTO", "AMKR",
)


class WarningItem(BaseModel):
    """One warning row shown in the boss dashboard."""

    severity: str
    category: str
    ticker: str | None = None
    title: str
    detail: str
    created_at: str | None = None
    source: str


class WarningDashboard(BaseModel):
    """GET /channel/api/warnings wire shape."""

    generated_at: str
    items: list[WarningItem]


class WarningPublishResult(BaseModel):
    """Result of publishing warning dashboard into research_reports."""

    research_id: int | None
    high_count: int
    medium_count: int
    changed: bool
    body: str


def _latest_close(conn: sqlite3.Connection, ticker: str) -> float | None:
    row = conn.execute(
        "SELECT c FROM prices WHERE ticker = ? ORDER BY ts DESC LIMIT 1",
        (ticker.upper(),),
    ).fetchone()
    return float(row[0]) if row else None


def _severity_rank(severity: str) -> int:
    return {"high": 0, "medium": 1, "low": 2, "info": 3}.get(severity, 4)


def _created_rank(created_at: str | None) -> float:
    if not created_at:
        return 0.0
    try:
        return datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _holding_risk_items(conn: sqlite3.Connection) -> list[WarningItem]:
    from stock.stops import compute_stop_loss

    items: list[WarningItem] = []
    for h in holdings.list_holdings(conn, active_only=True):
        close = _latest_close(conn, h.ticker)
        stop = compute_stop_loss(h.ticker, conn)
        if close is None:
            items.append(WarningItem(
                severity="low",
                category="data",
                ticker=h.ticker,
                title=f"{h.ticker}: no fresh price in local DB",
                detail="Holding is active but stop/P&L dashboard cannot compute until prices refresh.",
                source="holdings",
            ))
            continue

        if h.cost_basis > 0:
            pnl_pct = (close - h.cost_basis) / h.cost_basis * 100
            if pnl_pct <= -10:
                items.append(WarningItem(
                    severity="high",
                    category="pnl",
                    ticker=h.ticker,
                    title=f"{h.ticker}: holding down {pnl_pct:.1f}%",
                    detail=f"Last ${close:.2f} vs cost ${h.cost_basis:.2f}. Review thesis and stop plan.",
                    source="holdings",
                ))
            elif pnl_pct <= -5:
                items.append(WarningItem(
                    severity="medium",
                    category="pnl",
                    ticker=h.ticker,
                    title=f"{h.ticker}: holding down {pnl_pct:.1f}%",
                    detail=f"Last ${close:.2f} vs cost ${h.cost_basis:.2f}. Watch for follow-through.",
                    source="holdings",
                ))

        if stop.recommended is not None:
            stop_dist_pct = (close - stop.recommended) / close * 100
            if stop_dist_pct <= 0:
                items.append(WarningItem(
                    severity="high",
                    category="stop",
                    ticker=h.ticker,
                    title=f"{h.ticker}: below recommended stop",
                    detail=f"Last ${close:.2f}; stop ${stop.recommended:.2f}. Real broker orders still require explicit confirmation.",
                    source="F24_stop",
                ))
            elif stop_dist_pct <= 5:
                items.append(WarningItem(
                    severity="medium",
                    category="stop",
                    ticker=h.ticker,
                    title=f"{h.ticker}: within {stop_dist_pct:.1f}% of stop",
                    detail=f"Last ${close:.2f}; stop ${stop.recommended:.2f}.",
                    source="F24_stop",
                ))

    return items


def _alert_note_items(conn: sqlite3.Connection, *, days: int) -> list[WarningItem]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT topic, body, created_at FROM research_reports"
        " WHERE kind = 'alert' AND created_at >= ?"
        " ORDER BY created_at DESC LIMIT 20",
        (cutoff,),
    ).fetchall()
    items: list[WarningItem] = []
    for topic, body, created_at in rows:
        title = str(topic or "Holding alert")
        lower = title.lower()
        severity = "high" if (
            "stop-breach" in lower
            or "drop" in lower
            or "crash" in lower
            or "intraday" in lower
        ) else "medium"
        items.append(WarningItem(
            severity=severity,
            category="alert",
            ticker=_leading_ticker(title),
            title=title,
            detail=str(body or "").strip().replace("\n", " ")[:240],
            created_at=str(created_at),
            source="research_reports.alert",
        ))
    return items


_TICKER_RE = re.compile(r"\b([A-Z]{1,5}|[0-9]{4,6}\.[A-Z]{2})\b")


def _leading_ticker(title: str) -> str | None:
    """Pull the ticker an alert is about (alert topics lead with the symbol,
    e.g. 'GOOGL sell-trigger: ...', 'ACMR intraday SPIKE: ...')."""
    m = _TICKER_RE.search(title or "")
    return m.group(1) if m else None


def _anomaly_items(conn: sqlite3.Connection, *, days: int) -> list[WarningItem]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    active = {h.ticker.upper() for h in holdings.list_holdings(conn, active_only=True)}
    rows = conn.execute(
        "SELECT ticker, ts, pct_change, volume_ratio, flag_reason, created_at"
        " FROM price_anomalies WHERE ts >= ? ORDER BY ts DESC LIMIT 40",
        (cutoff,),
    ).fetchall()
    items: list[WarningItem] = []
    for ticker, ts, pct_change, volume_ratio, flag_reason, created_at in rows:
        ticker_s = str(ticker).upper()
        if active and ticker_s not in active:
            continue
        pct = float(pct_change) * 100
        vol = float(volume_ratio)
        severity = "high" if abs(pct) >= 12 or vol >= 3 else "medium"
        items.append(WarningItem(
            severity=severity,
            category="anomaly",
            ticker=ticker_s,
            title=f"{ticker_s}: {pct:+.1f}% / {vol:.1f}x volume anomaly",
            detail=f"{ts}: {flag_reason}",
            created_at=str(created_at),
            source="price_anomalies",
        ))
    return items


def _ai_loop_crash_items(conn: sqlite3.Connection, *, days: int) -> list[WarningItem]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(days, 90))).isoformat()
    rows = conn.execute(
        "SELECT ticker, measured_at, revenue_decel, margin_compression, risk_flag"
        " FROM ai_loop_health"
        " WHERE measured_at IN ("
        "   SELECT MAX(measured_at) FROM ai_loop_health"
        "   WHERE measured_at >= ? GROUP BY ticker"
        " )",
        (cutoff,),
    ).fetchall()
    severe = [r for r in rows if str(r[4]) == "severe"]
    mild = [r for r in rows if str(r[4]) == "mild"]
    if len(severe) >= 5:
        return [WarningItem(
            severity="high",
            category="cycle_crash",
            title="AI loop crash risk: severe",
            detail=(
                f"{len(severe)} panel companies are severe on revenue deceleration "
                "or gross-margin compression. This is the system's main general AI-cycle crash warning."
            ),
            created_at=max(str(r[1]) for r in severe),
            source="ai_loop_health",
        )]
    if len(severe) + len(mild) >= 3:
        names = ", ".join(str(r[0]) for r in severe + mild[:5])
        return [WarningItem(
            severity="medium",
            category="cycle_crash",
            title="AI loop crash risk: elevated",
            detail=f"{len(severe)} severe + {len(mild)} mild AI-demand loop warnings. Watch: {names}.",
            created_at=max(str(r[1]) for r in severe + mild),
            source="ai_loop_health",
        )]
    return []


def _options_crash_items(conn: sqlite3.Connection, *, days: int) -> list[WarningItem]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT ticker, put_volume, call_volume, put_call_volume_ratio, detected_at"
        " FROM option_ratio_snapshots"
        " WHERE detected_at >= ? AND put_call_volume_ratio IS NOT NULL"
        " ORDER BY detected_at DESC LIMIT 80",
        (cutoff,),
    ).fetchall()
    items: list[WarningItem] = []
    for ticker, put_volume, call_volume, ratio, detected_at in rows:
        ratio_f = float(ratio)
        if ratio_f < 2.0 or int(put_volume) < 1000:
            continue
        severity = "high" if ratio_f >= 3.0 and int(put_volume) >= 5000 else "medium"
        items.append(WarningItem(
            severity=severity,
            category="options_crash",
            ticker=str(ticker).upper(),
            title=f"{str(ticker).upper()}: put/call volume ratio {ratio_f:.1f}x",
            detail=f"Put volume {int(put_volume):,} vs call volume {int(call_volume):,}. Treat as hedge/crash-risk signal, not a standalone sell order.",
            created_at=str(detected_at),
            source="option_ratio_snapshots",
        ))
    return items[:8]


def _put_uoa_items(conn: sqlite3.Connection, *, days: int) -> list[WarningItem]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT ticker, contract_symbol, strike, expiry, volume, vol_oi_ratio,"
        " score, flag_reason, detected_at"
        " FROM option_anomalies"
        " WHERE detected_at >= ? AND option_type = 'put'"
        " ORDER BY score DESC, detected_at DESC LIMIT 10",
        (cutoff,),
    ).fetchall()
    items: list[WarningItem] = []
    for ticker, contract, strike, expiry, volume, vol_oi_ratio, score, flag_reason, detected_at in rows:
        if float(score) < 20:
            continue
        items.append(WarningItem(
            severity="high" if float(vol_oi_ratio) >= 20 else "medium",
            category="options_crash",
            ticker=str(ticker).upper(),
            title=f"{str(ticker).upper()}: unusual put activity",
            detail=(
                f"{contract} strike ${float(strike):.2f} exp {expiry}; "
                f"volume {int(volume):,}, vol/OI {float(vol_oi_ratio):.1f}x. {flag_reason}"
            ),
            created_at=str(detected_at),
            source="option_anomalies",
        ))
    return items


# Broker-sync staleness: the auto-pull skips (writes nothing) when the RH MCP
# is unavailable in headless codex, so holdings can silently freeze. Weekday
# threshold is ~1.5 trading days; Monday allows for the weekend pause.
BROKER_STALE_HOURS_WEEKDAY: float = 36.0
BROKER_STALE_HOURS_MONDAY: float = 84.0


def _broker_sync_staleness_items(
    conn: sqlite3.Connection, *, now: datetime | None = None
) -> list[WarningItem]:
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:  # pull job is Mon-Fri; weekend staleness is expected
        return []
    row = conn.execute(
        "SELECT MAX(updated_at) FROM holdings"
        " WHERE active = 1 AND notes LIKE '[broker:robinhood%'",
    ).fetchone()
    if not row or not row[0]:
        return []
    try:
        last_sync = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
    except ValueError:
        return []
    if last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=timezone.utc)
    age_hours = (now - last_sync).total_seconds() / 3600
    threshold = (
        BROKER_STALE_HOURS_MONDAY if now.weekday() == 0 else BROKER_STALE_HOURS_WEEKDAY
    )
    if age_hours <= threshold:
        return []

    from stock import job_runs

    detail = (
        f"Active holdings were last synced from Robinhood {age_hours:.0f}h ago"
        f" ({str(row[0])[:16]}). P&L, stops, and alerts run on stale positions."
    )
    err = job_runs.last_error(conn, "broker_positions_pull")
    if err:
        detail += f" Last pull error ({err[1][:16]}): {err[0][:200]}"
    else:
        detail += (
            " No recorded pull errors -- check the orchestrator is running and"
            " `codex` can reach the robinhood-trading MCP, or run `stock broker pull`."
        )
    return [WarningItem(
        severity="high",
        category="data",
        title="Robinhood holdings sync is stale",
        detail=detail,
        created_at=now.isoformat(),
        source="broker_sync",
    )]


def _ai_breadth_crash_items(conn: sqlite3.Connection) -> list[WarningItem]:
    drops: list[tuple[str, float, str]] = []
    seen = 0
    for ticker in AI_PRODUCTION_BREADTH_TICKERS:
        rows = conn.execute(
            "SELECT ts, c FROM prices WHERE ticker = ? ORDER BY ts DESC LIMIT 6",
            (ticker,),
        ).fetchall()
        if len(rows) < 6:
            continue
        latest_ts, latest_close = rows[0]
        prior_close = rows[-1][1]
        if float(prior_close) <= 0:
            continue
        seen += 1
        ret = (float(latest_close) - float(prior_close)) / float(prior_close) * 100
        if ret <= -8:
            drops.append((ticker, ret, str(latest_ts)))

    if seen < 8:
        return []
    share = len(drops) / seen
    if share >= 0.45:
        worst = ", ".join(f"{t} {r:.1f}%" for t, r, _ts in sorted(drops, key=lambda x: x[1])[:6])
        severity = "high" if share >= 0.60 else "medium"
        return [WarningItem(
            severity=severity,
            category="market_breadth",
            title="AI production chain breadth breakdown",
            detail=f"{len(drops)}/{seen} tracked AI-production names are down at least 8% over roughly one week. Worst: {worst}.",
            created_at=max(ts for _t, _r, ts in drops),
            source="prices",
        )]
    return []


def build_warning_dashboard(
    conn: sqlite3.Connection,
    *,
    days: int = 7,
    limit: int = 25,
) -> WarningDashboard:
    """Return warnings ordered by severity, then newest evidence first."""
    generated_at = datetime.now(timezone.utc).isoformat()
    items = (
        _holding_risk_items(conn)
        + _broker_sync_staleness_items(conn)
        + _alert_note_items(conn, days=days)
        + _anomaly_items(conn, days=days)
        + _ai_loop_crash_items(conn, days=days)
        + _options_crash_items(conn, days=days)
        + _put_uoa_items(conn, days=days)
        + _ai_breadth_crash_items(conn)
    )
    items.sort(key=lambda i: (_severity_rank(i.severity), -_created_rank(i.created_at)))

    # Collapse to ONE warning per ticker: after the sort the most severe / newest
    # item for each ticker is first, so keep that and fold the rest into a
    # "+N more signals" note. Market-wide (ticker-less) warnings are all kept.
    extra: dict[str, int] = {}
    deduped: list[WarningItem] = []
    seen: set[str] = set()
    for it in items:
        if it.ticker:
            if it.ticker in seen:
                extra[it.ticker] = extra.get(it.ticker, 0) + 1
                continue
            seen.add(it.ticker)
        deduped.append(it)
    for it in deduped:
        if it.ticker and extra.get(it.ticker):
            it.detail = f"{it.detail} (+{extra[it.ticker]} more signals on {it.ticker})"

    return WarningDashboard(generated_at=generated_at, items=deduped[:limit])


def format_warning_dashboard(dashboard: WarningDashboard) -> str:
    """Render warning dashboard as a compact boss-app/email report."""
    high = [i for i in dashboard.items if i.severity == "high"]
    medium = [i for i in dashboard.items if i.severity == "medium"]
    low = [i for i in dashboard.items if i.severity not in {"high", "medium"}]
    lines = [
        f"# Warning Dashboard / 风险预警 -- {dashboard.generated_at[:16]} UTC",
        "",
        f"Summary: {len(high)} high, {len(medium)} medium, {len(low)} low/info.",
        "",
    ]
    if not dashboard.items:
        lines.append("No active warnings in the current lookback window.")
    for heading, group in (("High", high), ("Medium", medium), ("Low / Info", low)):
        if not group:
            continue
        lines.append(f"## {heading}")
        for item in group[:12]:
            ticker = f" [{item.ticker}]" if item.ticker else ""
            created = f" ({item.created_at[:16]})" if item.created_at else ""
            lines.append(f"- **{item.category}{ticker}** {item.title}{created}")
            lines.append(f"  - {item.detail}")
        lines.append("")
    lines.append(
        "Broker stop-loss orders are not created or edited automatically; this is a warning and review surface."
    )
    return "\n".join(lines).strip()


def _dashboard_digest(dashboard: WarningDashboard) -> str:
    payload = [
        item.model_dump(exclude={"created_at"}, exclude_none=True)
        for item in dashboard.items
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def publish_warning_dashboard(
    conn: sqlite3.Connection,
    *,
    days: int = 7,
    limit: int = 25,
) -> WarningPublishResult:
    """Persist warning dashboard as research_reports when warning content changes."""
    dashboard = build_warning_dashboard(conn, days=days, limit=limit)
    body = format_warning_dashboard(dashboard)
    digest = _dashboard_digest(dashboard)
    key = "warning_dashboard_last_digest"
    row = conn.execute(
        "SELECT value FROM cloud_sync_state WHERE key = ?",
        (key,),
    ).fetchone()
    high_count = sum(1 for i in dashboard.items if i.severity == "high")
    medium_count = sum(1 for i in dashboard.items if i.severity == "medium")
    if row and str(row[0]) == digest:
        return WarningPublishResult(
            research_id=None,
            high_count=high_count,
            medium_count=medium_count,
            changed=False,
            body=body,
        )

    now = datetime.now(timezone.utc).isoformat()
    # Update the single existing warning_dashboard row in place instead of
    # inserting a new one every time the warning set changes -- otherwise the
    # table (and the synced feed) accumulates dozens of near-duplicate rows.
    existing = conn.execute(
        "SELECT id FROM research_reports WHERE kind = 'warning_dashboard'"
        " ORDER BY id DESC LIMIT 1",
    ).fetchone()
    if existing:
        research_id = int(existing[0])
        conn.execute(
            "UPDATE research_reports SET body = ?, created_at = ? WHERE id = ?",
            (body, now, research_id),
        )
    else:
        cursor = conn.execute(
            "INSERT INTO research_reports"
            " (kind, topic, layer_focus, body, cost_usd, created_at)"
            " VALUES ('warning_dashboard', 'Warning dashboard', 'risk', ?, 0, ?)",
            (body, now),
        )
        research_id = int(cursor.lastrowid or 0)
    conn.execute(
        "INSERT INTO cloud_sync_state (key, value, updated_at)"
        " VALUES (?, ?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
        " updated_at=excluded.updated_at",
        (key, digest, now),
    )
    conn.commit()
    return WarningPublishResult(
        research_id=research_id,
        high_count=high_count,
        medium_count=medium_count,
        changed=True,
        body=body,
    )
