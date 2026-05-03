"""stock.discovery_engine -- forward-looking candidate scoring + auto-promotion.

F19: scans a universe of tickers, computes the Future-Winner Probability (FWP)
score from stock.leading, persists discovery_candidates rows, and (when gated)
promotes top-N candidates onto the active watchlist for deep research.

Universe sources, in priority order:
  1. Tickers in active watchlist (re-score them too)
  2. Holdings (always score)
  3. Tickers in data/ai_supply_chain.yaml (the AI-supply-chain map)
  4. Tickers that have appeared in news in the last N days (broader coverage)

We dedupe + cap at MAX_UNIVERSE so the daily run stays bounded. Score updates
are upserts -- we keep one row per ticker with `last_score_at` stamping the
most recent run, but `first_flagged_at` preserves discovery date.

Auto-promotion is gated by:
  - FWP >= AUTO_PROMOTE_FWP_THRESHOLD (0.65 default; conservative)
  - QAP gate must be True (no promote on bad-pattern names)
  - At most AUTO_PROMOTE_MAX_PER_RUN per run (avoid spammy adds)
  - Skip if ticker is already on watchlist
  - Skip if ticker was recently dismissed by operator

Operator can dismiss a candidate via CLI; dismissed tickers won't be re-promoted
for DISMISS_COOLDOWN_DAYS.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel

from stock import holdings
from stock.leading import (
    CandidateScore,
    compute_future_winner_probability,
    fetch_apewisdom_snapshot,
)

logger = logging.getLogger(__name__)

WATCHLIST_PATH: str = "data/watchlist.yaml"
SUPPLY_CHAIN_PATH: str = "data/ai_supply_chain.yaml"
NEWS_LOOKBACK_DAYS: int = 14
MAX_UNIVERSE: int = 120
AUTO_PROMOTE_FWP_THRESHOLD: float = 0.65
AUTO_PROMOTE_MAX_PER_RUN: int = 3
DISMISS_COOLDOWN_DAYS: int = 30


class DiscoveryRunResult(BaseModel):
    """Summary of a run_discovery_engine pass."""

    universe_size: int
    scored: int
    new_candidates: int
    updated_candidates: int
    promoted_tickers: list[str]
    top_candidates: list[CandidateScore]
    apewisdom_hit: bool


def _load_supply_chain_tickers() -> set[str]:
    """Pull every ticker mentioned in data/ai_supply_chain.yaml."""
    path = Path(SUPPLY_CHAIN_PATH)
    if not path.exists():
        return set()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return set()
    out: set[str] = set()
    # Schema: layers -> sublayers -> players -> {ticker, ...}
    for layer in raw.get("layers", []) or []:
        for sublayer in (layer or {}).get("sublayers", []) or []:
            for player in (sublayer or {}).get("players", []) or []:
                t = (player or {}).get("ticker", "")
                if t:
                    out.add(str(t).upper())
    return out


def _load_yaml_watchlist() -> set[str]:
    """Read tickers off data/watchlist.yaml as a fallback."""
    path = Path(WATCHLIST_PATH)
    if not path.exists():
        return set()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("tickers"), list):
        return set()
    return {str(t).upper() for t in raw["tickers"] if t}


def build_discovery_universe(conn: sqlite3.Connection) -> list[str]:
    """Build the deduped universe of tickers to score this run.

    Order matters slightly because if MAX_UNIVERSE is hit we want watchlist +
    holdings to always make the cut.
    """
    universe: list[str] = []

    # Active watchlist (DB-driven)
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE active = 1 ORDER BY ticker"
    ).fetchall()
    for (t,) in rows:
        if t and t.upper() not in universe:
            universe.append(t.upper())

    # YAML watchlist fallback
    for t in _load_yaml_watchlist():
        if t not in universe:
            universe.append(t)

    # Active holdings -- always score
    for h in holdings.list_holdings(conn, active_only=True):
        if h.ticker.upper() not in universe:
            universe.append(h.ticker.upper())

    # Supply-chain map
    for t in sorted(_load_supply_chain_tickers()):
        if t not in universe:
            universe.append(t)
        if len(universe) >= MAX_UNIVERSE:
            break

    # Recent-news tickers (broader coverage)
    if len(universe) < MAX_UNIVERSE:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=NEWS_LOOKBACK_DAYS)
        ).isoformat()
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM news WHERE ts >= ? ORDER BY ticker",
            (cutoff,),
        ).fetchall()
        for (t,) in rows:
            if t and t.upper() not in universe:
                universe.append(t.upper())
            if len(universe) >= MAX_UNIVERSE:
                break

    return universe[:MAX_UNIVERSE]


def _upsert_candidate(
    conn: sqlite3.Connection, score: CandidateScore
) -> bool:
    """Insert or update a candidate row. Returns True if a NEW row was created."""
    now_iso = datetime.now(timezone.utc).isoformat()
    components_json = json.dumps(score.components, separators=(",", ":"))

    existing = conn.execute(
        "SELECT id, status FROM discovery_candidates WHERE ticker = ?",
        (score.ticker,),
    ).fetchone()

    if existing is None:
        conn.execute(
            "INSERT INTO discovery_candidates ("
            "  ticker, score, components_json, qap_gate,"
            "  first_flagged_at, last_score_at, last_score, status"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate')",
            (
                score.ticker, score.fwp, components_json,
                1 if score.qap_gate else 0, now_iso, now_iso, score.fwp,
            ),
        )
        conn.commit()
        return True

    conn.execute(
        "UPDATE discovery_candidates SET"
        "  score = ?, components_json = ?, qap_gate = ?,"
        "  last_score_at = ?, last_score = ?"
        " WHERE id = ?",
        (
            score.fwp, components_json, 1 if score.qap_gate else 0,
            now_iso, score.fwp, existing[0],
        ),
    )
    conn.commit()
    return False


def _is_recently_dismissed(conn: sqlite3.Connection, ticker: str) -> bool:
    """True if operator dismissed this ticker within the cooldown window."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=DISMISS_COOLDOWN_DAYS)
    ).isoformat()
    row = conn.execute(
        "SELECT 1 FROM discovery_candidates"
        " WHERE ticker = ? AND status = 'dismissed'"
        " AND COALESCE(dismissed_at, '') >= ?",
        (ticker, cutoff),
    ).fetchone()
    return row is not None


def _is_on_watchlist(conn: sqlite3.Connection, ticker: str) -> bool:
    """True if ticker is already on the active watchlist."""
    row = conn.execute(
        "SELECT 1 FROM watchlist WHERE ticker = ? AND active = 1",
        (ticker,),
    ).fetchone()
    return row is not None


def promote_candidate(
    conn: sqlite3.Connection, ticker: str, *, score: float
) -> bool:
    """Promote a candidate onto the watchlist + flip its discovery row.

    Idempotent on the watchlist (INSERT OR IGNORE); always stamps the discovery
    candidate's promoted_at + status='promoted' so the operator can audit.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO watchlist (ticker, added_at, active)"
        " VALUES (?, ?, 1)",
        (ticker.upper(), now_iso),
    )
    conn.execute(
        "UPDATE discovery_candidates SET status = 'promoted', promoted_at = ?,"
        " notes = COALESCE(notes, '') || ?"
        " WHERE ticker = ?",
        (now_iso, f"\nPromoted at {now_iso} with FWP={score:.3f}", ticker.upper()),
    )
    conn.commit()
    logger.info(
        "discovery: promoted %s to watchlist (FWP=%.3f)", ticker, score,
    )
    return True


def dismiss_candidate(
    conn: sqlite3.Connection, ticker: str, *, reason: str = ""
) -> bool:
    """Operator marks a candidate as dismissed (won't be re-promoted for cooldown days)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "UPDATE discovery_candidates SET status = 'dismissed',"
        " dismissed_at = ?, notes = COALESCE(notes, '') || ?"
        " WHERE ticker = ?",
        (now_iso, f"\nDismissed at {now_iso}: {reason or '(no reason)'}",
         ticker.upper()),
    )
    conn.commit()
    return cursor.rowcount > 0


def list_candidates(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[CandidateScore]:
    """Read the discovery_candidates table back as CandidateScore models."""
    if status:
        rows = conn.execute(
            "SELECT ticker, score, components_json, qap_gate, last_score_at"
            " FROM discovery_candidates WHERE status = ?"
            " ORDER BY score DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT ticker, score, components_json, qap_gate, last_score_at"
            " FROM discovery_candidates"
            " ORDER BY score DESC LIMIT ?",
            (limit,),
        ).fetchall()

    out: list[CandidateScore] = []
    for ticker, score, comp_json, qap, last_at in rows:
        try:
            components = json.loads(comp_json or "{}")
        except (json.JSONDecodeError, TypeError):
            components = {}
        out.append(CandidateScore(
            ticker=str(ticker), fwp=float(score), fwp_pre_gate=float(score),
            qap_gate=bool(qap), components=components, score_at=str(last_at),
        ))
    return out


def format_candidates_block(candidates: list[CandidateScore], *, limit: int = 5) -> str:
    """Render top candidates as a markdown block for the daily research note."""
    if not candidates:
        return "(no discovery candidates yet -- forward-looking pipeline hasn't found anything)"
    lines: list[str] = []
    for c in candidates[:limit]:
        gate = "GATE" if c.qap_gate else "no-gate"
        ocis = c.components.get("ocis_raw", 0.0)
        novelty = c.components.get("novelty_raw", 0.0)
        cluster = int(c.components.get("ocis_cluster_max", 0))
        accel = c.components.get("reddit_accel", 0.0)
        lines.append(
            f"- {c.ticker} FWP={c.fwp:.3f} [{gate}]"
            f" insider_score={ocis:.1f} (cluster={cluster})"
            f" novelty={novelty:.2f} reddit_accel={accel:+.2f}"
        )
    return "\n".join(lines)


def run_discovery_engine(
    conn: sqlite3.Connection,
    *,
    auto_promote: bool = True,
) -> DiscoveryRunResult:
    """End-to-end pass: score the universe, persist, optionally auto-promote.

    Pulls one ApeWisdom snapshot up front so we don't hammer the API once per
    ticker. Best-effort: a snapshot failure means reddit signals are zero for
    this run but everything else still scores.
    """
    universe = build_discovery_universe(conn)
    snapshot = fetch_apewisdom_snapshot()
    snapshot_ok = bool(snapshot)

    scored: list[CandidateScore] = []
    new_count = 0
    updated_count = 0

    for ticker in universe:
        try:
            cs = compute_future_winner_probability(
                ticker, conn, apewisdom_snapshot=snapshot,
            )
        except Exception:
            logger.exception("discovery: scoring failed for %s", ticker)
            continue
        scored.append(cs)
        is_new = _upsert_candidate(conn, cs)
        if is_new:
            new_count += 1
        else:
            updated_count += 1

    # Sort by score so promotion picks the strongest
    scored.sort(key=lambda x: x.fwp, reverse=True)

    promoted_tickers: list[str] = []
    if auto_promote:
        for cs in scored:
            if len(promoted_tickers) >= AUTO_PROMOTE_MAX_PER_RUN:
                break
            if cs.fwp < AUTO_PROMOTE_FWP_THRESHOLD:
                continue
            if not cs.qap_gate:
                continue
            if _is_on_watchlist(conn, cs.ticker):
                continue
            if _is_recently_dismissed(conn, cs.ticker):
                continue
            try:
                promote_candidate(conn, cs.ticker, score=cs.fwp)
                promoted_tickers.append(cs.ticker)
            except Exception:
                logger.exception(
                    "discovery: promote failed for %s", cs.ticker,
                )

    return DiscoveryRunResult(
        universe_size=len(universe),
        scored=len(scored),
        new_candidates=new_count,
        updated_candidates=updated_count,
        promoted_tickers=promoted_tickers,
        top_candidates=scored[:10],
        apewisdom_hit=snapshot_ok,
    )
