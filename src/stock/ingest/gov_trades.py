"""stock.ingest.gov_trades -- congressional/government trade disclosures (H3).

The boss's ask (the Trump/DELL disclosure-timing case): systematically track
politicians' STOCK Act trades instead of one-off deep dives. The free
community mirrors (senate/house-stock-watcher S3 buckets) are dead (403), so
this collector reads ANY JSON feed configured in `GOV_TRADES_URL` -- a
QuiverQuant API URL with key, a future mirror, or a self-hosted export. Both
QuiverQuant and the legacy stock-watcher field names are understood.

IMPORTANT signal caveat baked into every rendered block: STOCK Act
disclosures lag the trade by up to 45 days. This is a slow conviction /
political-risk flag, never fast alpha.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pydantic import BaseModel

from stock.config import get_settings

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECS: float = 60.0
MAX_TRANSACTION_AGE_DAYS: int = 365
DISCLOSURE_LAG_NOTE: str = (
    "(STOCK Act disclosures lag trades by up to 45 days -- treat as slow"
    " conviction / political-risk context, not fast alpha)"
)


class GovTradesPullResult(BaseModel):
    """Summary of one feed pull."""

    url: str
    fetched: int = 0
    inserted: int = 0
    skipped: int = 0


def _first(entry: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = entry.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def parse_entry(entry: dict[str, Any]) -> dict[str, str] | None:
    """Normalize one feed entry across QuiverQuant / stock-watcher shapes."""
    if not isinstance(entry, dict):
        return None
    ticker = _first(entry, "Ticker", "ticker", "symbol").upper()
    politician = _first(
        entry, "Representative", "Senator", "Politician", "Name",
        "representative", "senator", "politician", "name",
    )
    tx_date = _first(
        entry, "TransactionDate", "transaction_date", "Traded", "trade_date",
    )[:10]
    if not ticker or not politician or not tx_date or ticker in {"--", "N/A"}:
        return None
    tx_type = _first(
        entry, "Transaction", "transaction_type", "type", "Type",
    ).lower()
    if "purchase" in tx_type or "buy" in tx_type:
        tx_type = "buy"
    elif "sale" in tx_type or "sell" in tx_type or "sold" in tx_type:
        tx_type = "sell"
    elif "exchange" in tx_type:
        tx_type = "exchange"
    else:
        tx_type = tx_type or "other"
    return {
        "politician": politician,
        "chamber": _first(entry, "Chamber", "chamber", "House", "office"),
        "ticker": ticker,
        "transaction_type": tx_type,
        "amount_range": _first(entry, "Range", "amount", "Amount", "Trade_Size_USD"),
        "transaction_date": tx_date,
        "disclosed_at": _first(
            entry, "ReportDate", "disclosure_date", "Filed", "report_date",
        )[:10],
    }


def _entries_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "transactions", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [e for e in value if isinstance(e, dict)]
    return []


def pull_gov_trades(
    conn: sqlite3.Connection, *, url: str | None = None
) -> GovTradesPullResult | None:
    """Fetch the configured feed and upsert recent transactions. None = no URL."""
    url = (url or get_settings().gov_trades_url).strip()
    if not url:
        logger.info(
            "gov trades pull skipped: GOV_TRADES_URL not configured"
            " (community mirrors are dead; operator must pick a source)"
        )
        return None

    response = httpx.get(url, timeout=FETCH_TIMEOUT_SECS, follow_redirects=True)
    response.raise_for_status()
    entries = _entries_from_payload(response.json())

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=MAX_TRANSACTION_AGE_DAYS)
    ).date().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    result = GovTradesPullResult(url=url, fetched=len(entries))
    for raw in entries:
        parsed = parse_entry(raw)
        if parsed is None or parsed["transaction_date"] < cutoff:
            result.skipped += 1
            continue
        cursor = conn.execute(
            "INSERT OR IGNORE INTO gov_trades"
            " (politician, chamber, ticker, transaction_type, amount_range,"
            " transaction_date, disclosed_at, source, ingested_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (parsed["politician"], parsed["chamber"], parsed["ticker"],
             parsed["transaction_type"], parsed["amount_range"],
             parsed["transaction_date"], parsed["disclosed_at"], url[:120], now),
        )
        if cursor.rowcount > 0:
            result.inserted += 1
        else:
            result.skipped += 1
    conn.commit()
    logger.info(
        "gov trades pull: fetched=%d inserted=%d skipped=%d",
        result.fetched, result.inserted, result.skipped,
    )
    return result


def recent_for_ticker(
    conn: sqlite3.Connection, ticker: str, *, days: int = 90, limit: int = 8
) -> list[tuple[str, str, str, str, str]]:
    """(politician, type, amount, transaction_date, disclosed_at), newest first."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).date().isoformat()
    return [
        (str(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]))
        for r in conn.execute(
            "SELECT politician, transaction_type, amount_range,"
            " transaction_date, disclosed_at FROM gov_trades"
            " WHERE ticker = ? AND transaction_date >= ?"
            " ORDER BY transaction_date DESC LIMIT ?",
            (ticker.upper(), cutoff, limit),
        )
    ]


def format_gov_block(ticker: str, conn: sqlite3.Connection, *, days: int = 90) -> str:
    """Compact per-ticker block for prompts; empty string when no trades."""
    rows = recent_for_ticker(conn, ticker, days=days)
    if not rows:
        return ""
    lines = [f"Government/congressional trades in {ticker} (last {days}d) {DISCLOSURE_LAG_NOTE}:"]
    for politician, tx_type, amount, tx_date, disclosed in rows:
        disclosed_s = f", disclosed {disclosed}" if disclosed else ""
        amount_s = f" {amount}" if amount else ""
        lines.append(f"- {tx_date}: {politician} {tx_type}{amount_s}{disclosed_s}")
    return "\n".join(lines)
