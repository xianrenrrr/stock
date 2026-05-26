"""stock.options -- F36 unusual options activity (UOA) detector.

Pulls each ticker's option chain via yfinance, looks for "smart-money"
fingerprints near the current price:

* volume / open_interest >= 5  (fresh position, not just rolling existing OI)
* volume >= 1000 contracts (filters retail noise; institutional sweeps clear this)
* |strike - underlying| / underlying < 12% (near-the-money is the actionable zone)
* expiry within 75 days (longer-dated whales get muddied by hedging flows)

What this catches: the EBAY pattern from the screenshots -- 20,000+ contracts
piled into a near-the-money strike on a single day, vol/OI >> 1, IV elevated.

Limitations: yfinance gives end-of-day chain snapshots, not intraday tape;
we cannot distinguish bid-side vs ask-side prints. So treat scores as
"directionally interesting" not "definitely bullish/bearish."
"""
from __future__ import annotations

import logging
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from pydantic import BaseModel

logger = logging.getLogger(__name__)

VOLUME_FLOOR: int = 1000
VOL_OI_RATIO_FLOOR: float = 5.0
DISTANCE_PCT_CEILING: float = 0.12
MAX_DAYS_TO_EXPIRY: int = 75
TOP_PER_TICKER: int = 5  # only persist the most extreme N hits per scan


class UnusualOption(BaseModel):
    """One UOA detection -- ready for DB insert + prompt rendering."""

    ticker: str
    contract_symbol: str
    option_type: str  # 'call' or 'put'
    strike: float
    expiry: str
    volume: int
    open_interest: int
    vol_oi_ratio: float
    implied_vol: float | None
    underlying_price: float | None
    distance_pct: float | None
    score: float
    flag_reason: str


class OptionRatioSnapshot(BaseModel):
    """Aggregate call/put positioning snapshot for one ticker scan."""

    ticker: str
    call_volume: int
    put_volume: int
    call_open_interest: int
    put_open_interest: int
    call_put_volume_ratio: float | None
    put_call_volume_ratio: float | None
    call_put_oi_ratio: float | None
    put_call_oi_ratio: float | None
    expiries_scanned: int
    contracts_scanned: int
    detected_at: str | None = None


@dataclass
class _ChainRow:
    """yfinance row reduced to the fields we use -- keeps this module mockable."""

    contract_symbol: str
    strike: float
    volume: float | None
    open_interest: float | None
    implied_vol: float | None


def _coerce_int(value: float | int | None) -> int:
    """yfinance gives float NaN for missing volume; clamp to 0."""
    if value is None:
        return 0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0
    if math.isnan(f):
        return 0
    return int(f)


def _score(volume: int, vol_oi_ratio: float, distance_pct: float) -> float:
    """Composite: more weight to fresh positioning + nearness to spot.

    score = log10(volume) * vol_oi_ratio * (1 - distance_pct)
    Typical real-world hits: log10(20000)=4.3, ratio=5, distance=0.05
    => ~20 (high). Floor: log10(1000)=3, ratio=5, distance=0.12 => ~13.2.
    """
    return math.log10(max(volume, 10)) * vol_oi_ratio * max(0.0, 1.0 - distance_pct)


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _classify(
    row: _ChainRow,
    *,
    option_type: str,
    expiry: str,
    underlying: float,
    today: datetime,
) -> UnusualOption | None:
    """Apply the UOA filter to one chain row; return None if it doesn't pass."""
    volume = _coerce_int(row.volume)
    open_interest = _coerce_int(row.open_interest)
    if volume < VOLUME_FLOOR:
        return None
    if open_interest <= 0:
        # Fresh series can have OI=0 -- treat as ratio = volume
        vol_oi_ratio = float(volume)
    else:
        vol_oi_ratio = volume / open_interest
    if vol_oi_ratio < VOL_OI_RATIO_FLOOR:
        return None

    distance_pct = abs(row.strike - underlying) / underlying if underlying > 0 else 1.0
    if distance_pct > DISTANCE_PCT_CEILING:
        return None

    try:
        exp_dt = datetime.fromisoformat(expiry).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    days_to_expiry = (exp_dt - today).days
    if days_to_expiry < 0 or days_to_expiry > MAX_DAYS_TO_EXPIRY:
        return None

    flag_parts: list[str] = []
    if vol_oi_ratio >= 20:
        flag_parts.append("EXTREME vol/OI")
    elif vol_oi_ratio >= 10:
        flag_parts.append("HIGH vol/OI")
    if volume >= 10000:
        flag_parts.append("size whale")
    if distance_pct < 0.03:
        flag_parts.append("at-the-money")
    if not flag_parts:
        flag_parts.append("UOA threshold")
    flag_reason = ", ".join(flag_parts)

    return UnusualOption(
        ticker="",  # caller fills
        contract_symbol=row.contract_symbol,
        option_type=option_type,
        strike=row.strike,
        expiry=expiry,
        volume=volume,
        open_interest=open_interest,
        vol_oi_ratio=vol_oi_ratio,
        implied_vol=row.implied_vol,
        underlying_price=underlying,
        distance_pct=distance_pct,
        score=_score(volume, vol_oi_ratio, distance_pct),
        flag_reason=flag_reason,
    )


def detect_unusual(
    *,
    ticker: str,
    underlying: float,
    expiries: Iterable[str],
    chain_provider,  # callable: expiry -> (calls_rows, puts_rows)
    today: datetime | None = None,
) -> list[UnusualOption]:
    """Run UOA detection on every nearby expiry; return the top hits.

    chain_provider is a callable so this is easy to mock in tests; in
    production it wraps yfinance.Ticker(ticker).option_chain(expiry).
    Returns up to TOP_PER_TICKER results sorted by score descending.
    """
    if underlying <= 0:
        return []
    today = today or datetime.now(timezone.utc)
    cutoff = today.replace(hour=0, minute=0, second=0, microsecond=0)

    hits: list[UnusualOption] = []
    for expiry in expiries:
        try:
            exp_dt = datetime.fromisoformat(expiry).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if (exp_dt - cutoff).days > MAX_DAYS_TO_EXPIRY:
            break  # expiries are sorted ascending; further ones are too far out
        try:
            calls_rows, puts_rows = chain_provider(expiry)
        except Exception:  # noqa: BLE001 -- network/yfinance, log+skip
            logger.debug("chain fetch failed for %s %s", ticker, expiry, exc_info=True)
            continue
        for row in calls_rows:
            hit = _classify(row, option_type="call", expiry=expiry,
                            underlying=underlying, today=today)
            if hit:
                hit.ticker = ticker.upper()
                hits.append(hit)
        for row in puts_rows:
            hit = _classify(row, option_type="put", expiry=expiry,
                            underlying=underlying, today=today)
            if hit:
                hit.ticker = ticker.upper()
                hits.append(hit)
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:TOP_PER_TICKER]


def compute_ratio_snapshot(
    *,
    ticker: str,
    expiries: Iterable[str],
    chain_provider,
    today: datetime | None = None,
) -> OptionRatioSnapshot:
    """Aggregate call/put volume and open interest across nearby expiries."""
    today = today or datetime.now(timezone.utc)
    cutoff = today.replace(hour=0, minute=0, second=0, microsecond=0)
    call_volume = put_volume = 0
    call_open_interest = put_open_interest = 0
    expiries_scanned = contracts_scanned = 0

    for expiry in expiries:
        try:
            exp_dt = datetime.fromisoformat(expiry).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        days_to_expiry = (exp_dt - cutoff).days
        if days_to_expiry < 0:
            continue
        if days_to_expiry > MAX_DAYS_TO_EXPIRY:
            break
        try:
            calls_rows, puts_rows = chain_provider(expiry)
        except Exception:  # noqa: BLE001 -- network/yfinance, log+skip
            logger.debug("chain fetch failed for ratio %s %s", ticker, expiry, exc_info=True)
            continue

        expiries_scanned += 1
        contracts_scanned += len(calls_rows) + len(puts_rows)
        for row in calls_rows:
            call_volume += _coerce_int(row.volume)
            call_open_interest += _coerce_int(row.open_interest)
        for row in puts_rows:
            put_volume += _coerce_int(row.volume)
            put_open_interest += _coerce_int(row.open_interest)

    return OptionRatioSnapshot(
        ticker=ticker.upper(),
        call_volume=call_volume,
        put_volume=put_volume,
        call_open_interest=call_open_interest,
        put_open_interest=put_open_interest,
        call_put_volume_ratio=_safe_ratio(call_volume, put_volume),
        put_call_volume_ratio=_safe_ratio(put_volume, call_volume),
        call_put_oi_ratio=_safe_ratio(call_open_interest, put_open_interest),
        put_call_oi_ratio=_safe_ratio(put_open_interest, call_open_interest),
        expiries_scanned=expiries_scanned,
        contracts_scanned=contracts_scanned,
    )


def _yfinance_provider(ticker: str):
    """Build a chain_provider closure backed by yfinance."""
    import yfinance  # third-party, optional

    yf_ticker = yfinance.Ticker(ticker)

    def provider(expiry: str) -> tuple[list[_ChainRow], list[_ChainRow]]:
        chain = yf_ticker.option_chain(expiry)
        calls = [
            _ChainRow(
                contract_symbol=str(r["contractSymbol"]),
                strike=float(r["strike"]),
                volume=r.get("volume"),
                open_interest=r.get("openInterest"),
                implied_vol=float(r["impliedVolatility"]) if r.get("impliedVolatility") else None,
            )
            for r in chain.calls.to_dict("records")
        ]
        puts = [
            _ChainRow(
                contract_symbol=str(r["contractSymbol"]),
                strike=float(r["strike"]),
                volume=r.get("volume"),
                open_interest=r.get("openInterest"),
                implied_vol=float(r["impliedVolatility"]) if r.get("impliedVolatility") else None,
            )
            for r in chain.puts.to_dict("records")
        ]
        return calls, puts

    return provider, yf_ticker


def scan_ticker(
    conn: sqlite3.Connection, ticker: str, *,
    underlying: float | None = None,
) -> list[UnusualOption]:
    """Scan one ticker, persist the hits, return them.

    underlying defaults to the latest close from the prices table.
    Errors don't propagate -- options-data is best-effort, not load-bearing.
    """
    if underlying is None:
        row = conn.execute(
            "SELECT c FROM prices WHERE ticker = ? ORDER BY ts DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
        underlying = float(row[0]) if row else 0.0
    if underlying <= 0:
        return []

    try:
        provider, yf_ticker = _yfinance_provider(ticker)
        expiries = list(yf_ticker.options or [])
    except Exception:  # noqa: BLE001
        logger.debug("yfinance options unavailable for %s", ticker, exc_info=True)
        return []

    hits = detect_unusual(
        ticker=ticker, underlying=underlying,
        expiries=expiries, chain_provider=provider,
    )
    if hits:
        persist(conn, hits)
    return hits


def scan_ratio_snapshot(conn: sqlite3.Connection, ticker: str) -> OptionRatioSnapshot | None:
    """Scan one ticker's options chain and persist aggregate call/put ratios."""
    try:
        provider, yf_ticker = _yfinance_provider(ticker)
        expiries = list(yf_ticker.options or [])
    except Exception:  # noqa: BLE001
        logger.debug("yfinance options unavailable for ratio %s", ticker, exc_info=True)
        return None

    snapshot = compute_ratio_snapshot(
        ticker=ticker,
        expiries=expiries,
        chain_provider=provider,
    )
    if snapshot.expiries_scanned == 0:
        return None
    persist_ratio_snapshot(conn, snapshot)
    return snapshot


def persist(conn: sqlite3.Connection, hits: list[UnusualOption]) -> int:
    """Insert detection rows; UNIQUE(contract_symbol, detected_at) dedupes intra-day."""
    if not hits:
        return 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inserted = 0
    for h in hits:
        cur = conn.execute(
            "INSERT OR IGNORE INTO option_anomalies"
            " (ticker, contract_symbol, option_type, strike, expiry, volume,"
            " open_interest, vol_oi_ratio, implied_vol, underlying_price,"
            " distance_pct, score, flag_reason, detected_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                h.ticker, h.contract_symbol, h.option_type, h.strike, h.expiry,
                h.volume, h.open_interest, h.vol_oi_ratio, h.implied_vol,
                h.underlying_price, h.distance_pct, h.score, h.flag_reason, now,
            ),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


def persist_ratio_snapshot(conn: sqlite3.Connection, snapshot: OptionRatioSnapshot) -> int:
    """Insert one aggregate option-ratio snapshot."""
    detected_at = snapshot.detected_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT OR IGNORE INTO option_ratio_snapshots"
        " (ticker, call_volume, put_volume, call_open_interest, put_open_interest,"
        " call_put_volume_ratio, put_call_volume_ratio, call_put_oi_ratio,"
        " put_call_oi_ratio, expiries_scanned, contracts_scanned, detected_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            snapshot.ticker,
            snapshot.call_volume,
            snapshot.put_volume,
            snapshot.call_open_interest,
            snapshot.put_open_interest,
            snapshot.call_put_volume_ratio,
            snapshot.put_call_volume_ratio,
            snapshot.call_put_oi_ratio,
            snapshot.put_call_oi_ratio,
            snapshot.expiries_scanned,
            snapshot.contracts_scanned,
            detected_at,
        ),
    )
    conn.commit()
    return cur.rowcount


def recent_anomalies(
    conn: sqlite3.Connection, *, days: int = 3, limit: int = 20,
) -> list[dict]:
    """Return the highest-scoring UOA hits from the last `days` days."""
    rows = conn.execute(
        "SELECT ticker, contract_symbol, option_type, strike, expiry, volume,"
        " open_interest, vol_oi_ratio, implied_vol, underlying_price,"
        " distance_pct, score, flag_reason, detected_at"
        " FROM option_anomalies"
        " WHERE detected_at >= datetime('now', ?)"
        " ORDER BY score DESC LIMIT ?",
        (f"-{int(days)} days", int(limit)),
    ).fetchall()
    keys = [
        "ticker", "contract_symbol", "option_type", "strike", "expiry",
        "volume", "open_interest", "vol_oi_ratio", "implied_vol",
        "underlying_price", "distance_pct", "score", "flag_reason", "detected_at",
    ]
    return [dict(zip(keys, r)) for r in rows]


def recent_ratio_snapshots(
    conn: sqlite3.Connection, *, days: int = 3, limit: int = 20,
) -> list[dict]:
    """Return recent aggregate option-ratio snapshots."""
    rows = conn.execute(
        "SELECT ticker, call_volume, put_volume, call_open_interest, put_open_interest,"
        " call_put_volume_ratio, put_call_volume_ratio, call_put_oi_ratio,"
        " put_call_oi_ratio, expiries_scanned, contracts_scanned, detected_at"
        " FROM option_ratio_snapshots"
        " WHERE detected_at >= datetime('now', ?)"
        " ORDER BY detected_at DESC, ticker ASC LIMIT ?",
        (f"-{int(days)} days", int(limit)),
    ).fetchall()
    keys = [
        "ticker", "call_volume", "put_volume", "call_open_interest",
        "put_open_interest", "call_put_volume_ratio", "put_call_volume_ratio",
        "call_put_oi_ratio", "put_call_oi_ratio", "expiries_scanned",
        "contracts_scanned", "detected_at",
    ]
    return [dict(zip(keys, r)) for r in rows]


def format_uoa_block(conn: sqlite3.Connection, *, days: int = 3, limit: int = 12) -> str:
    """Render a markdown table of recent UOA hits for the research prompt.

    Returns "" when nothing is unusual -- the caller decides whether to emit
    the section header at all.
    """
    rows = recent_anomalies(conn, days=days, limit=limit)
    if not rows:
        return ""
    lines = [
        "| Ticker | Type | Strike | Expiry | Vol | OI | V/OI | IV | 距现价 | 标志 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        iv = f"{(r['implied_vol'] or 0) * 100:.0f}%" if r["implied_vol"] else "-"
        dist = f"{(r['distance_pct'] or 0) * 100:+.1f}%" if r["distance_pct"] is not None else "-"
        lines.append(
            f"| {r['ticker']} | {r['option_type']} | "
            f"${r['strike']:.0f} | {r['expiry']} | "
            f"{r['volume']:,} | {r['open_interest']:,} | "
            f"{r['vol_oi_ratio']:.1f}x | {iv} | {dist} | {r['flag_reason']} |"
        )
    return "\n".join(lines)


def format_ratio_block(conn: sqlite3.Connection, *, days: int = 3, limit: int = 12) -> str:
    """Render recent aggregate call/put option ratios as a markdown table."""
    rows = recent_ratio_snapshots(conn, days=days, limit=limit)
    if not rows:
        return ""
    lines = [
        "| Ticker | Call Vol | Put Vol | C/P Vol | P/C Vol | Call OI | Put OI | C/P OI | Exp |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        cp_vol = (
            f"{r['call_put_volume_ratio']:.2f}x"
            if r["call_put_volume_ratio"] is not None else "-"
        )
        pc_vol = (
            f"{r['put_call_volume_ratio']:.2f}x"
            if r["put_call_volume_ratio"] is not None else "-"
        )
        cp_oi = f"{r['call_put_oi_ratio']:.2f}x" if r["call_put_oi_ratio"] is not None else "-"
        lines.append(
            f"| {r['ticker']} | {r['call_volume']:,} | {r['put_volume']:,} | "
            f"{cp_vol} | {pc_vol} | {r['call_open_interest']:,} | "
            f"{r['put_open_interest']:,} | {cp_oi} | {r['expiries_scanned']} |"
        )
    return "\n".join(lines)
