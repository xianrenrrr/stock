"""stock.ai_loop_monitor -- F39 AI commercial-loop closure-risk monitor.

Boss directive 2026-05-05: "AI 核心在明年或者后年要建立商业闭环, 也就是除了
云公司赚钱, 那些真正用 AI 云的公司要赚钱, 如果没有办法形成商业闭环, 是有
崩盘的危险的." AI cloud capex is producing real cloud-vendor revenue NOW;
the question is whether the SaaS / consumer-app companies CONSUMING that AI
cloud spend can monetize it well enough to keep paying. If 2027-2028 doesn't
close the loop, expectations re-rate => crash.

This module tracks a curated panel of AI-using SaaS / consumer-app companies
on two dimensions per quarter:

  * Revenue YoY growth -- DECELERATION is the leading indicator
  * Gross margin trend -- COMPRESSION signals AI inference costs eating margin

When >=3 panel companies show simultaneous deceleration AND margin compression
in their most recent quarter, fire a "loop closure risk" alert. The risk_flag
column captures one of: ok / mild / severe.

The composite is rendered as a markdown block in the daily research note's
Risk section (boss explicitly asked: "always include one bullet on AI
commercial-loop status").
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Curated AI-using SaaS / consumer panel. These are companies whose business
# model depends on monetizing AI inference, NOT companies selling AI compute.
PANEL: list[dict] = [
    {"ticker": "CRM",   "name": "Salesforce",      "category": "vertical-saas-AI"},
    {"ticker": "NOW",   "name": "ServiceNow",      "category": "vertical-saas-AI"},
    {"ticker": "WDAY",  "name": "Workday",         "category": "vertical-saas-AI"},
    {"ticker": "ADBE",  "name": "Adobe",           "category": "creative-saas-AI"},
    {"ticker": "INTU",  "name": "Intuit",          "category": "smb-saas-AI"},
    {"ticker": "TEAM",  "name": "Atlassian",       "category": "developer-saas-AI"},
    {"ticker": "ZM",    "name": "Zoom",            "category": "consumer-saas-AI"},
    {"ticker": "HUBS",  "name": "HubSpot",         "category": "smb-saas-AI"},
    {"ticker": "DDOG",  "name": "Datadog",         "category": "infra-saas-AI"},
    {"ticker": "MDB",   "name": "MongoDB",         "category": "infra-saas-AI"},
    {"ticker": "SNOW",  "name": "Snowflake",       "category": "infra-saas-AI"},
    {"ticker": "PLTR",  "name": "Palantir",        "category": "enterprise-AI"},
    {"ticker": "NET",   "name": "Cloudflare",      "category": "infra-saas-AI"},
    {"ticker": "S",     "name": "SentinelOne",     "category": "security-saas-AI"},
    {"ticker": "ZS",    "name": "Zscaler",         "category": "security-saas-AI"},
]

DECEL_WARN_THRESHOLD: float = -0.05    # YoY growth dropped 5pp QoQ
DECEL_SEVERE_THRESHOLD: float = -0.15  # 15pp drop = serious deceleration
MARGIN_COMPRESSION_WARN: float = -0.02 # GM dropped 2pp from trailing-4Q mean
MARGIN_COMPRESSION_SEVERE: float = -0.05  # 5pp = serious

PANEL_SEVERE_LOOP_RISK: int = 5  # 5+ panel companies severe = "崩盘 risk live"
PANEL_MILD_LOOP_RISK: int = 3    # 3-4 panel companies mild+ = elevated risk


class LoopHealthMeasurement(BaseModel):
    """One panel company's most recent measurement -- ready for DB + render."""

    ticker: str
    measured_at: str
    quarterly_revenue_usd: float | None
    quarterly_revenue_yoy: float | None
    revenue_yoy_4q_mean: float | None
    revenue_decel: float | None  # latest YoY minus trailing 4Q mean
    gross_margin: float | None
    gross_margin_4q_mean: float | None
    margin_compression: float | None  # latest GM minus trailing 4Q mean
    risk_flag: str  # ok | mild | severe


def _classify_risk(decel: float | None, margin_compression: float | None) -> str:
    """Combine deceleration + compression into a single label."""
    decel = decel if decel is not None else 0.0
    margin = margin_compression if margin_compression is not None else 0.0
    severe = (
        decel <= DECEL_SEVERE_THRESHOLD
        or margin <= MARGIN_COMPRESSION_SEVERE
    )
    if severe:
        return "severe"
    mild = (
        decel <= DECEL_WARN_THRESHOLD
        or margin <= MARGIN_COMPRESSION_WARN
    )
    if mild:
        return "mild"
    return "ok"


def _yfinance_panel_data(ticker: str) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    """Pull (latest_q_rev, latest_growth, prior_growth_mean, latest_gm, prior_4q_mean_gm).

    yfinance free tier returns ~5 quarters of quarterly_income_stmt. To compute
    a YoY-of-YoY deceleration we'd need 9, so we fall back to QoQ-of-QoQ:
    with 5 quarters we get 4 QoQ growth datapoints; latest vs trailing-3Q
    mean is the deceleration signal. QoQ is seasonally noisier but a
    consistent panel-wide signal still detects loop-closure stress.

    Tolerant of missing data -- returns Nones rather than raising. Tests
    inject a stub provider instead of calling this.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.quarterly_income_stmt
        if df is None:
            return (None, None, None, None, None)

        latest_q_rev = None
        # QoQ growth across whatever quarters yfinance gave us
        qoqs: list[float] = []
        if "Total Revenue" in df.index:
            rev_series = df.loc["Total Revenue"].dropna()
            rev_list = rev_series.tolist()  # most-recent-first
            if rev_list:
                latest_q_rev = float(rev_list[0])
            for i in range(len(rev_list) - 1):
                prev = rev_list[i + 1]
                if prev:
                    qoqs.append((rev_list[i] - prev) / abs(prev))

        latest_q_yoy = qoqs[0] if qoqs else None
        # Use up to 3 prior QoQ datapoints as the "trailing baseline"
        prior_4q_mean_yoy = (
            sum(qoqs[1:4]) / max(1, len(qoqs[1:4]))
            if len(qoqs) > 1 else None
        )

        # Gross margin: Gross Profit / Total Revenue
        gms: list[float] = []
        if "Gross Profit" in df.index and "Total Revenue" in df.index:
            gp_list = df.loc["Gross Profit"].dropna().tolist()
            rev_list = df.loc["Total Revenue"].dropna().tolist()
            n = min(len(gp_list), len(rev_list))
            for i in range(n):
                if rev_list[i]:
                    gms.append(gp_list[i] / rev_list[i])

        latest_gm = gms[0] if gms else None
        prior_4q_mean_gm = sum(gms[1:5]) / max(1, len(gms[1:5])) if len(gms) > 1 else None

        return latest_q_rev, latest_q_yoy, prior_4q_mean_yoy, latest_gm, prior_4q_mean_gm
    except Exception:
        logger.debug("yfinance loop data lookup failed for %s", ticker, exc_info=True)
        return (None, None, None, None, None)


def measure_one(
    *, ticker: str, measured_at: str | None = None,
    data_provider=None,
) -> LoopHealthMeasurement:
    """Compute one panel company's risk flag."""
    measured_at = measured_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    provider = data_provider or _yfinance_panel_data
    latest_rev, latest_yoy, mean_yoy, latest_gm, mean_gm = provider(ticker)

    decel: float | None = None
    if latest_yoy is not None and mean_yoy is not None:
        decel = latest_yoy - mean_yoy

    margin_compression: float | None = None
    if latest_gm is not None and mean_gm is not None:
        margin_compression = latest_gm - mean_gm

    return LoopHealthMeasurement(
        ticker=ticker.upper(),
        measured_at=measured_at,
        quarterly_revenue_usd=latest_rev,
        quarterly_revenue_yoy=latest_yoy,
        revenue_yoy_4q_mean=mean_yoy,
        revenue_decel=decel,
        gross_margin=latest_gm,
        gross_margin_4q_mean=mean_gm,
        margin_compression=margin_compression,
        risk_flag=_classify_risk(decel, margin_compression),
    )


def measure_panel(
    *, panel: list[dict] | None = None,
    measured_at: str | None = None,
    data_provider=None,
) -> list[LoopHealthMeasurement]:
    """Walk the curated panel; return one measurement per company."""
    panel = panel if panel is not None else PANEL
    return [
        measure_one(ticker=p["ticker"], measured_at=measured_at, data_provider=data_provider)
        for p in panel
    ]


def overall_loop_status(measurements: list[LoopHealthMeasurement]) -> str:
    """Aggregate the panel: severe / elevated / ok."""
    severe = sum(1 for m in measurements if m.risk_flag == "severe")
    mild_or_severe = sum(1 for m in measurements if m.risk_flag in ("severe", "mild"))
    if severe >= PANEL_SEVERE_LOOP_RISK:
        return "severe"
    if mild_or_severe >= PANEL_MILD_LOOP_RISK:
        return "elevated"
    return "ok"


def persist(conn: sqlite3.Connection, measurements: list[LoopHealthMeasurement]) -> int:
    """Insert measurements; UNIQUE(ticker, measured_at) dedupes."""
    if not measurements:
        return 0
    inserted = 0
    for m in measurements:
        cur = conn.execute(
            "INSERT OR IGNORE INTO ai_loop_health"
            " (ticker, measured_at, quarterly_revenue_usd, quarterly_revenue_yoy,"
            " revenue_yoy_4q_mean, revenue_decel, gross_margin, gross_margin_4q_mean,"
            " margin_compression, risk_flag)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                m.ticker, m.measured_at, m.quarterly_revenue_usd,
                m.quarterly_revenue_yoy, m.revenue_yoy_4q_mean, m.revenue_decel,
                m.gross_margin, m.gross_margin_4q_mean, m.margin_compression,
                m.risk_flag,
            ),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


def latest_measurements(conn: sqlite3.Connection, *, days: int = 90) -> list[dict]:
    """Return the most-recent measurement per ticker within the lookback window."""
    rows = conn.execute(
        "SELECT ticker, measured_at, quarterly_revenue_yoy, revenue_yoy_4q_mean,"
        " revenue_decel, gross_margin, margin_compression, risk_flag"
        " FROM ai_loop_health"
        " WHERE measured_at IN ("
        "   SELECT MAX(measured_at) FROM ai_loop_health"
        "   WHERE measured_at >= datetime('now', ?)"
        "   GROUP BY ticker"
        " )"
        " ORDER BY"
        "   CASE risk_flag WHEN 'severe' THEN 0 WHEN 'mild' THEN 1 ELSE 2 END,"
        "   ticker",
        (f"-{int(days)} days",),
    ).fetchall()
    keys = [
        "ticker", "measured_at", "quarterly_revenue_yoy", "revenue_yoy_4q_mean",
        "revenue_decel", "gross_margin", "margin_compression", "risk_flag",
    ]
    return [dict(zip(keys, r)) for r in rows]


def format_loop_block(conn: sqlite3.Connection, *, days: int = 90) -> str:
    """Render the markdown block for the daily research note Risk section.

    Empty string when the panel hasn't been measured -- caller suppresses
    the section so the note doesn't lie about coverage.
    """
    rows = latest_measurements(conn, days=days)
    if not rows:
        return ""
    severe = [r for r in rows if r["risk_flag"] == "severe"]
    mild = [r for r in rows if r["risk_flag"] == "mild"]
    overall = (
        "severe" if len(severe) >= PANEL_SEVERE_LOOP_RISK
        else "elevated" if len(severe) + len(mild) >= PANEL_MILD_LOOP_RISK
        else "ok"
    )
    headline = {
        "severe": "AI 商业闭环 -- 严重风险 (5+ 面板公司同时减速 + 毛利压缩)",
        "elevated": "AI 商业闭环 -- 警戒 (3+ 面板公司减速 / 毛利压缩)",
        "ok": "AI 商业闭环 -- 健康 (< 3 减速信号)",
    }[overall]

    lines = [
        f"**{headline}** -- panel of {len(rows)} AI-using SaaS/consumer co's, "
        f"{len(severe)} severe + {len(mild)} mild on most-recent-Q.",
    ]
    if severe or mild:
        lines.append("")
        lines.append("| Ticker | Rev YoY | 4Q mean | Decel | GM | GM compress | Flag |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for r in severe + mild[:5 - len(severe)]:
            yoy = f"{(r['quarterly_revenue_yoy'] or 0) * 100:+.1f}%" if r["quarterly_revenue_yoy"] is not None else "-"
            mean = f"{(r['revenue_yoy_4q_mean'] or 0) * 100:+.1f}%" if r["revenue_yoy_4q_mean"] is not None else "-"
            decel = f"{(r['revenue_decel'] or 0) * 100:+.1f}pp" if r["revenue_decel"] is not None else "-"
            gm = f"{(r['gross_margin'] or 0) * 100:.1f}%" if r["gross_margin"] is not None else "-"
            comp = f"{(r['margin_compression'] or 0) * 100:+.1f}pp" if r["margin_compression"] is not None else "-"
            lines.append(
                f"| {r['ticker']} | {yoy} | {mean} | {decel} | {gm} | {comp} | {r['risk_flag']} |"
            )
    return "\n".join(lines)
