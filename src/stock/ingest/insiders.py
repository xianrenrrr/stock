"""stock.ingest.insiders -- pull SEC EDGAR Form 4 insider filings (free, no key)."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from stock.config import get_settings

logger = logging.getLogger(__name__)

CIK_DB_URL: str = "https://www.sec.gov/files/company_tickers.json"
EDGAR_FORM4_URL: str = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count={count}&output=atom"
)
CIK_CACHE_PATH: str = "data/.cache/cik_lookup.json"
CIK_CACHE_TTL_SECS: int = 7 * 86400
SEC_REQUEST_DELAY_SECS: float = 0.1
DEFAULT_LIMIT: int = 10
HTTP_TIMEOUT_SECS: float = 15.0


class InsiderTransaction(BaseModel):
    """One Form 4 transaction extracted from EDGAR."""

    ticker: str
    filer_name: str = ""
    filer_role: str | None = None
    form_type: str
    filed_at: str
    transaction_type: str | None = None
    shares: float | None = None
    price: float | None = None
    accession_number: str
    raw_url: str


def _user_agent() -> str:
    """Return the configured SEC User-Agent string (with default fallback)."""
    settings = get_settings()
    ua = (settings.edgar_user_agent or "").strip() or "stock-research 0.1 ops@example.com"
    if "example.com" in ua:
        logger.warning(
            "EDGAR_USER_AGENT still uses example.com -- set a real contact in .env"
        )
    return ua


def _http_get(url: str) -> httpx.Response:
    """GET with the EDGAR-required User-Agent header."""
    headers = {
        "User-Agent": _user_agent(),
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }
    with httpx.Client(timeout=HTTP_TIMEOUT_SECS, headers=headers) as client:
        return client.get(url)


def _load_cik_cache() -> dict[str, str]:
    """Load the cached ticker -> CIK map (returns {} if cache is missing/stale)."""
    path = Path(CIK_CACHE_PATH)
    if not path.exists():
        return {}
    try:
        age = time.time() - path.stat().st_mtime
        if age > CIK_CACHE_TTL_SECS:
            return {}
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cik_cache(mapping: dict[str, str]) -> None:
    """Write the ticker -> CIK map to disk for the next run."""
    path = Path(CIK_CACHE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping), encoding="utf-8")


def _refresh_cik_cache() -> dict[str, str]:
    """Pull the master ticker -> CIK file from EDGAR and cache it."""
    response = _http_get(CIK_DB_URL)
    response.raise_for_status()
    data: dict[str, Any] = response.json()

    mapping: dict[str, str] = {}
    for row in data.values():
        if isinstance(row, dict):
            ticker = str(row.get("ticker", "")).upper()
            cik = row.get("cik_str")
            if ticker and cik is not None:
                mapping[ticker] = str(int(cik)).zfill(10)
    _save_cik_cache(mapping)
    return mapping


def lookup_cik(ticker: str) -> str | None:
    """Return zero-padded 10-digit CIK for the ticker, or None if unknown."""
    cache = _load_cik_cache()
    if not cache:
        try:
            cache = _refresh_cik_cache()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("CIK cache refresh failed: %s", exc)
            return None
    return cache.get(ticker.upper())


_ENTRY_RE = re.compile(r"<entry>(.*?)</entry>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<{tag}[^>]*>(.*?)</{tag}>", re.DOTALL | re.IGNORECASE)


def _tag_value(block: str, tag: str) -> str:
    """Extract the inner text of the first <tag>...</tag> in block."""
    pattern = re.compile(
        rf"<{tag}[^>]*>(.*?)</{tag}>", re.DOTALL | re.IGNORECASE
    )
    match = pattern.search(block)
    return match.group(1).strip() if match else ""


def _accession_from_link(href: str) -> str:
    """Extract the accession number from an EDGAR Atom <link> href."""
    match = re.search(r"(\d{10}-\d{2}-\d{6})", href)
    return match.group(1) if match else ""


def parse_atom_feed(text: str, *, ticker: str) -> list[InsiderTransaction]:
    """Parse an EDGAR ATOM feed into InsiderTransaction rows."""
    out: list[InsiderTransaction] = []
    for entry_block in _ENTRY_RE.findall(text):
        title = _tag_value(entry_block, "title")
        link_match = re.search(r'<link[^>]*href="([^"]+)"', entry_block, re.IGNORECASE)
        href = link_match.group(1) if link_match else ""
        accession = _accession_from_link(href)
        if not accession:
            continue
        updated = _tag_value(entry_block, "updated") or _tag_value(entry_block, "filing-date")
        # Title looks like: "4 - Insider Name (CIK)" or "4/A - ..."
        form_match = re.match(r"^\s*(4(?:/A)?)\b", title)
        form_type = form_match.group(1) if form_match else "4"
        # Filer name: substring between "- " and " ("
        filer_match = re.search(r"-\s*(.+?)\s*\(", title)
        filer_name = filer_match.group(1).strip() if filer_match else title.strip()

        out.append(
            InsiderTransaction(
                ticker=ticker.upper(),
                filer_name=filer_name,
                filer_role=None,
                form_type=form_type,
                filed_at=updated,
                transaction_type=None,
                shares=None,
                price=None,
                accession_number=accession,
                raw_url=href,
            )
        )
    return out


def fetch_form4(
    ticker: str, *, limit: int = DEFAULT_LIMIT
) -> list[InsiderTransaction]:
    """Pull the most recent Form 4 entries for a ticker via EDGAR ATOM feed."""
    cik = lookup_cik(ticker)
    if not cik:
        logger.info("No CIK for ticker %s; skipping insider fetch", ticker)
        return []

    url = EDGAR_FORM4_URL.format(cik=cik, count=limit)
    try:
        time.sleep(SEC_REQUEST_DELAY_SECS)
        response = _http_get(url)
    except httpx.HTTPError as exc:
        logger.warning("EDGAR fetch failed for %s: %s", ticker, exc)
        return []

    if response.status_code != 200:
        logger.warning(
            "EDGAR returned %s for %s (%s)", response.status_code, ticker, url
        )
        return []

    return parse_atom_feed(response.text, ticker=ticker)


def persist_insiders(
    conn: sqlite3.Connection, ticker: str, *, limit: int = DEFAULT_LIMIT
) -> int:
    """Fetch + UPSERT Form 4 rows for a ticker. Returns inserted count."""
    rows = fetch_form4(ticker, limit=limit)
    if not rows:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for row in rows:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO insider_filings"
            " (ticker, filer_name, filer_role, form_type, filed_at,"
            " transaction_type, shares, price, accession_number, raw_url, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.ticker, row.filer_name, row.filer_role, row.form_type,
                row.filed_at, row.transaction_type, row.shares, row.price,
                row.accession_number, row.raw_url, now,
            ),
        )
        if cursor.rowcount:
            inserted += 1
    conn.commit()
    return inserted


def recent_for_ticker(
    conn: sqlite3.Connection, ticker: str, *, days: int = 90
) -> list[InsiderTransaction]:
    """Return Form 4 rows filed in the last N days for a ticker."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT ticker, filer_name, filer_role, form_type, filed_at,"
        " transaction_type, shares, price, accession_number, raw_url"
        " FROM insider_filings WHERE ticker = ? AND filed_at >= ?"
        " ORDER BY filed_at DESC",
        (ticker.upper(), cutoff),
    ).fetchall()
    return [
        InsiderTransaction(
            ticker=str(r[0]),
            filer_name=str(r[1]),
            filer_role=r[2],
            form_type=str(r[3]),
            filed_at=str(r[4]),
            transaction_type=r[5],
            shares=r[6],
            price=r[7],
            accession_number=str(r[8]),
            raw_url=str(r[9]),
        )
        for r in rows
    ]


def format_insider_block(rows: list[InsiderTransaction]) -> str:
    """Render Form 4 rows as a compact bullet block."""
    if not rows:
        return "(no recent insider filings)"
    lines: list[str] = []
    for row in rows:
        kind = row.transaction_type or "filing"
        sh = f" shares={row.shares:g}" if row.shares else ""
        pr = f" px={row.price:.2f}" if row.price else ""
        lines.append(
            f"- [{row.filed_at[:10]}] {row.ticker} {row.form_type} | {row.filer_name} | {kind}{sh}{pr}"
        )
    return "\n".join(lines)
