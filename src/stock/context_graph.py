"""stock.context_graph -- memoized prediction-context nodes (plan H phase H1).

Every shared prompt section becomes a NODE: a rendered text block with a
declared input fingerprint (a cheap probe of its source rows). `get_block`
recomputes the block only when the fingerprint changed; otherwise it returns
the stored copy. A 25-ticker prediction batch therefore renders the macro /
market-internals / sector-breadth blocks ONCE instead of 25 times, and every
prediction records WHICH node versions it saw (`context_manifest` in
feature_context_json) so grading can attribute hit-rate differences to
specific context versions.

Per-ticker nodes (news digest, knowledge card) arrive with plan H phase H2.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)

SHARED_SCOPE: str = "*"


@dataclass(frozen=True)
class NodeSpec:
    """One context node: how to probe its inputs and how to render it."""

    name: str
    fingerprint: Callable[[sqlite3.Connection, str], str]
    render: Callable[[sqlite3.Connection, str], str]


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# --- node implementations ----------------------------------------------------

def _macro_fingerprint(conn: sqlite3.Connection, _scope: str) -> str:
    row = conn.execute(
        "SELECT MAX(id) FROM research_reports WHERE kind = 'macro'",
    ).fetchone()
    # Date in the fingerprint: format_macro_block has a 4-day staleness window,
    # so the rendered text can change with the calendar even without new rows.
    return f"macro:{row[0] if row else None}:{_today()}"


def _macro_render(conn: sqlite3.Connection, _scope: str) -> str:
    from stock.macro import format_macro_block

    return format_macro_block(conn)


def _internals_fingerprint(conn: sqlite3.Connection, _scope: str) -> str:
    from stock.market_context import INDEX_TICKERS

    placeholders = ",".join("?" * len(INDEX_TICKERS))
    row = conn.execute(
        f"SELECT MAX(ts), COUNT(*) FROM prices WHERE ticker IN ({placeholders})",
        INDEX_TICKERS,
    ).fetchone()
    return f"internals:{row[0]}:{row[1]}" if row else "internals:none"


def _internals_render(conn: sqlite3.Connection, _scope: str) -> str:
    from stock.market_context import format_market_internals

    return format_market_internals(conn)


def _breadth_fingerprint(conn: sqlite3.Connection, _scope: str) -> str:
    from stock.predict import AI_INFRA_TICKERS

    tickers = sorted(AI_INFRA_TICKERS)
    placeholders = ",".join("?" * len(tickers))
    row = conn.execute(
        f"SELECT MAX(ts), COUNT(*) FROM prices WHERE ticker IN ({placeholders})",
        tickers,
    ).fetchone()
    return f"breadth:{row[0]}:{row[1]}" if row else "breadth:none"


def _breadth_render(conn: sqlite3.Connection, _scope: str) -> str:
    """AI-infra peer breadth, promoted from guardrail math to a visible block."""
    from stock.predict import (
        AI_INFRA_SECTOR_LEADERS,
        AI_INFRA_TICKERS,
        _latest_return_for_ticker,
    )

    returns: dict[str, float] = {}
    for peer in AI_INFRA_TICKERS:
        ret = _latest_return_for_ticker(peer, conn)
        if ret is not None:
            returns[peer] = ret
    if len(returns) < 5:
        return "(insufficient AI-infra peer data for breadth)"
    positive_share = sum(1 for r in returns.values() if r > 0) / len(returns)
    ordered = sorted(returns.values())
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    leaders = {
        t: returns[t] for t in sorted(AI_INFRA_SECTOR_LEADERS) if t in returns
    }
    leaders_s = ", ".join(f"{t} {r * 100:+.1f}%" for t, r in leaders.items())
    return (
        f"AI-infra peer breadth ({len(returns)} names): "
        f"{positive_share * 100:.0f}% positive on the day, "
        f"median move {median * 100:+.1f}%. Leaders: {leaders_s}."
    )


NODES: dict[str, NodeSpec] = {
    "macro": NodeSpec("macro", _macro_fingerprint, _macro_render),
    "market_internals": NodeSpec(
        "market_internals", _internals_fingerprint, _internals_render,
    ),
    "sector_breadth": NodeSpec(
        "sector_breadth", _breadth_fingerprint, _breadth_render,
    ),
}


# --- memoized resolution -------------------------------------------------------

def get_block(
    conn: sqlite3.Connection, name: str, scope: str = SHARED_SCOPE
) -> tuple[str, str]:
    """Return (content, content_hash) for a node, recomputing only on change.

    Any failure in the fingerprint/cache path degrades to a direct render --
    memoization must never break a prediction.
    """
    spec = NODES[name]
    try:
        fp = spec.fingerprint(conn, scope)
        row = conn.execute(
            "SELECT content, content_hash, input_fingerprint FROM context_nodes"
            " WHERE node = ? AND scope = ?",
            (name, scope),
        ).fetchone()
        if row is not None and str(row[2]) == fp:
            return str(row[0]), str(row[1])

        content = spec.render(conn, scope)
        content_hash = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
        conn.execute(
            "INSERT INTO context_nodes"
            " (node, scope, content, content_hash, input_fingerprint,"
            " token_estimate, computed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(node, scope) DO UPDATE SET"
            " content = excluded.content, content_hash = excluded.content_hash,"
            " input_fingerprint = excluded.input_fingerprint,"
            " token_estimate = excluded.token_estimate,"
            " computed_at = excluded.computed_at",
            (name, scope, content, content_hash, fp,
             max(1, len(content) // 4), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return content, content_hash
    except Exception:
        logger.exception("context node %s/%s failed; rendering uncached", name, scope)
        content = spec.render(conn, scope)
        return content, hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
