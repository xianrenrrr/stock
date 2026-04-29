"""stock.discover -- web-discovery pipeline that hunts for AI supply-chain hidden gems."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from stock.config import get_settings
from stock.models import (
    MINIMAX_DEFAULT_MODEL,
    ChatMessage,
    ChatResponse,
    check_cost_ceiling,
    get_client,
    parse_llm_json,
)
from stock.supply_chain import (
    Layer,
    SupplyChain,
    load_chain,
    pick_focus_layer,
)
from stock.webfetch import FetchResult, fetch_many
from stock.websearch import SearchResult, WebSearchUnavailable, search_many

logger = logging.getLogger(__name__)

DISCOVER_PROMPT_PATH: str = "prompts/discover_extract.txt"
WATCHLIST_PATH: str = "data/watchlist.yaml"
DEFAULT_QUERIES_PER_SUBLAYER: int = 1
DEFAULT_TOP_LEVEL_QUERIES: int = 3
DEFAULT_RESULTS_PER_QUERY: int = 5
DEFAULT_PAGES_TO_FETCH: int = 6
DEFAULT_PAGE_MAX_CHARS: int = 4500
DISCOVERY_MAX_TOKENS: int = 4000


class HiddenGemMention(BaseModel):
    """One ticker / company surfaced by the LLM extractor."""

    ticker: str
    company: str
    layer: str
    sublayer: str = ""
    thesis: str
    conviction: str = "medium"
    is_small_cap_or_under_followed: bool = False


class ResearchTheme(BaseModel):
    """One cross-source theme synthesized by the LLM extractor."""

    theme: str
    summary: str


class DiscoverExtraction(BaseModel):
    """Structured LLM output from the discover_extract prompt."""

    mentions: list[HiddenGemMention] = []
    themes: list[ResearchTheme] = []


class DiscoverResult(BaseModel):
    """Result of a single discovery run, persisted to web_research."""

    research_id: int
    session_label: str
    layer_focus: str
    queries: list[str]
    extraction: DiscoverExtraction
    cost_usd: float
    created_at: str


@lru_cache(maxsize=1)
def _load_extract_prompt() -> tuple[str, str]:
    """Load and split the extraction prompt on [SYSTEM]/[USER] markers."""
    path = Path(DISCOVER_PROMPT_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Discover prompt not found at {DISCOVER_PROMPT_PATH}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("[USER]")
    system_part = parts[0].replace("[SYSTEM]", "").strip()
    user_part = parts[1].strip() if len(parts) > 1 else ""
    return system_part, user_part


def _session_label(now: datetime) -> str:
    """Tag a discovery run as morning/evening with a date suffix."""
    suffix = now.strftime("%Y-%m-%d")
    return f"{'morning' if now.hour < 18 else 'evening'}_{suffix}"


def generate_queries(
    chain: SupplyChain,
    *,
    focus_layer: Layer,
    watchlist: list[str],
    queries_per_sublayer: int = DEFAULT_QUERIES_PER_SUBLAYER,
    top_level_queries: int = DEFAULT_TOP_LEVEL_QUERIES,
) -> list[str]:
    """Build the search-query batch for a discovery run.

    Strategy:
      1. Per sublayer of the focus layer, generate N hidden-gem queries.
      2. Plus a small set of top-down queries on the overall AI capex theme.
      3. Plus a per-watchlist-ticker freshness query, capped to keep token costs bounded.
    """
    queries: list[str] = []
    year = datetime.now(timezone.utc).year

    # Per-sublayer queries for the focus layer
    for sub in focus_layer.sublayers:
        slug = sub.name.replace("_", " ")
        per_sublayer = [
            f"{slug} hidden gem stock {year}",
            f"{slug} supplier shortage AI capex {year}",
            f"{slug} earnings forecast {year}",
        ][:queries_per_sublayer]
        queries.extend(per_sublayer)

    # Top-down queries
    top_down = [
        f"AI supply chain hidden gem stocks {year} picks and shovels",
        f"AI capex {year} bottleneck supplier small cap",
        f"semiconductor packaging hybrid bonding HBM {year} stocks",
        f"800G 1.6T optical module supplier {year} forecast",
        f"AI data center power cooling small cap {year}",
    ][:top_level_queries]
    queries.extend(top_down)

    # Watchlist freshness queries (cap at 5 to stay cheap)
    for ticker in watchlist[:5]:
        queries.append(f"{ticker} stock {year} catalyst forecast supplier AI")

    # Dedupe while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for q in queries:
        norm = q.strip()
        if norm and norm.lower() not in seen:
            seen.add(norm.lower())
            deduped.append(norm)
    return deduped


def _build_results_block(
    search_hits: dict[str, list[SearchResult]],
    fetched: dict[str, FetchResult],
    *,
    max_chars_per_excerpt: int = 1200,
) -> str:
    """Render search results + fetched excerpts as a compact text block for the LLM."""
    lines: list[str] = []
    for query, hits in search_hits.items():
        lines.append(f"### Query: {query}")
        if not hits:
            lines.append("  (no results)")
            continue
        for hit in hits:
            lines.append(f"- [{hit.title}]({hit.url})")
            if hit.snippet:
                lines.append(f"    snippet: {hit.snippet[:280]}")
            page = fetched.get(hit.url)
            if page and page.ok:
                excerpt = page.text[:max_chars_per_excerpt].replace("\n", " ").strip()
                lines.append(f"    excerpt: {excerpt}")
            elif page and page.error:
                lines.append(f"    fetch failed: {page.error}")
        lines.append("")
    return "\n".join(lines)


def _select_urls_to_fetch(
    search_hits: dict[str, list[SearchResult]], *, top_n: int
) -> list[str]:
    """Select the highest-signal URLs across all queries to fetch in full."""
    seen: set[str] = set()
    chosen: list[tuple[float, str]] = []
    for hits in search_hits.values():
        for rank, hit in enumerate(hits[:3]):  # only top-3 per query
            if not hit.url or hit.url in seen:
                continue
            seen.add(hit.url)
            # Score = backend score (Tavily) + small reciprocal-rank boost
            chosen.append((hit.score + 1.0 / (rank + 1), hit.url))

    chosen.sort(key=lambda pair: pair[0], reverse=True)
    return [url for _, url in chosen[:top_n]]


def _persist(
    conn: sqlite3.Connection,
    *,
    session_label: str,
    layer_focus: str,
    queries: list[str],
    search_hits: dict[str, list[SearchResult]],
    fetched: dict[str, FetchResult],
    extraction: DiscoverExtraction,
    cost_usd: float,
) -> int:
    """Insert one row into web_research and return its id."""
    now = datetime.now(timezone.utc).isoformat()
    serializable_hits = {
        q: [h.model_dump() for h in hits] for q, hits in search_hits.items()
    }
    serializable_fetched = {
        url: {
            "url": page.url,
            "status": page.status,
            "title": page.title,
            "ok": page.ok,
            "error": page.error,
        }
        for url, page in fetched.items()
    }
    cursor = conn.execute(
        "INSERT INTO web_research"
        " (session_label, layer_focus, queries_json, results_json, extracted_json,"
        "  cost_usd, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            session_label,
            layer_focus,
            json.dumps(queries),
            json.dumps({"search": serializable_hits, "fetched": serializable_fetched}),
            extraction.model_dump_json(),
            cost_usd,
            now,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)


def run_discovery(
    conn: sqlite3.Connection,
    *,
    focus_layer_name: str | None = None,
    watchlist: list[str] | None = None,
    extra_query: str | None = None,
) -> DiscoverResult:
    """Run a full discovery cycle: query-gen, search, fetch, extract, persist."""
    settings = get_settings()
    chain: SupplyChain = load_chain()

    # Resolve focus layer
    if focus_layer_name:
        focus_layer: Layer | None = chain.find_layer(focus_layer_name)
        if focus_layer is None:
            raise ValueError(f"Unknown focus layer '{focus_layer_name}'")
    else:
        focus_layer = pick_focus_layer(chain)

    # Resolve watchlist
    tickers = list(watchlist) if watchlist is not None else _load_active_watchlist(conn)

    # Build query batch
    queries = generate_queries(
        chain, focus_layer=focus_layer, watchlist=tickers
    )
    if extra_query:
        queries.insert(0, extra_query.strip())

    # Run searches (raises WebSearchUnavailable if no backend configured)
    search_hits = search_many(queries, max_results_per_query=DEFAULT_RESULTS_PER_QUERY)
    logger.info(
        "Discovery searches: queries=%d hits=%d",
        len(queries),
        sum(len(v) for v in search_hits.values()),
    )

    # Fetch top URLs for richer context
    urls_to_fetch = _select_urls_to_fetch(search_hits, top_n=DEFAULT_PAGES_TO_FETCH)
    fetched_list = fetch_many(urls_to_fetch, max_chars=DEFAULT_PAGE_MAX_CHARS)
    fetched: dict[str, FetchResult] = {p.url: p for p in fetched_list}
    logger.info(
        "Discovery fetches: ok=%d failed=%d",
        sum(1 for p in fetched_list if p.ok),
        sum(1 for p in fetched_list if not p.ok),
    )

    # Build extraction prompt input
    results_block = _build_results_block(search_hits, fetched)
    queries_block = "\n".join(f"- {q}" for q in queries)
    watchlist_block = ", ".join(tickers) if tickers else "(empty)"

    # Cost-ceiling check before LLM dispatch
    check_cost_ceiling(conn, settings)

    # LLM extraction (cheap MiniMax model)
    system_template, user_template = _load_extract_prompt()
    user_message = user_template.format(
        focus_layer_name=focus_layer.layer,
        focus_layer_function=focus_layer.function,
        watchlist_block=watchlist_block,
        queries_block=queries_block,
        results_block=results_block,
    )

    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    client = get_client("minimax")
    response: ChatResponse = client.chat(
        messages=messages,
        model=MINIMAX_DEFAULT_MODEL,
        max_tokens=DISCOVERY_MAX_TOKENS,
        conn=conn,
        caller="discover.run_discovery",
        cached_system=system_template,
    )

    # Parse extraction JSON; fall back to empty on malformed output
    extraction = DiscoverExtraction()
    try:
        parsed = parse_llm_json(response.content)
        extraction = DiscoverExtraction(**parsed)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Discovery extraction returned unparseable JSON: %s", exc)

    now = datetime.now(timezone.utc)
    session_label = _session_label(now)
    research_id = _persist(
        conn,
        session_label=session_label,
        layer_focus=focus_layer.layer,
        queries=queries,
        search_hits=search_hits,
        fetched=fetched,
        extraction=extraction,
        cost_usd=response.cost_usd,
    )

    return DiscoverResult(
        research_id=research_id,
        session_label=session_label,
        layer_focus=focus_layer.layer,
        queries=queries,
        extraction=extraction,
        cost_usd=response.cost_usd,
        created_at=now.isoformat(),
    )


def get_recent_extractions(
    conn: sqlite3.Connection, *, hours: int = 12
) -> list[tuple[str, str, DiscoverExtraction]]:
    """Return (session_label, layer_focus, extraction) tuples from the last N hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        "SELECT session_label, layer_focus, extracted_json FROM web_research"
        " WHERE created_at >= ? ORDER BY created_at DESC",
        (cutoff,),
    ).fetchall()

    out: list[tuple[str, str, DiscoverExtraction]] = []
    for label, layer, raw in rows:
        try:
            parsed = json.loads(raw or "{}")
            out.append((label or "", layer or "", DiscoverExtraction(**parsed)))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return out


def format_extractions_for_research(
    extractions: list[tuple[str, str, DiscoverExtraction]],
    *,
    max_mentions: int = 25,
    max_themes: int = 6,
) -> str:
    """Render recent extractions as a text block for the daily-research prompt."""
    if not extractions:
        return "(no recent web discovery extractions -- run `stock discover` or wait for the scheduled job)"

    # Aggregate uniquely by ticker; preserve highest-conviction entry
    mentions_by_ticker: dict[str, HiddenGemMention] = {}
    themes: list[ResearchTheme] = []
    for _label, _layer, extraction in extractions:
        for m in extraction.mentions:
            existing = mentions_by_ticker.get(m.ticker)
            if existing is None or _conviction_rank(m.conviction) > _conviction_rank(existing.conviction):
                mentions_by_ticker[m.ticker] = m
        themes.extend(extraction.themes)

    lines: list[str] = []

    # Mentions block
    lines.append("### Hidden-gem mentions (deduped, last 12h)")
    if mentions_by_ticker:
        ordered = sorted(
            mentions_by_ticker.values(),
            key=lambda m: (
                -_conviction_rank(m.conviction),
                not m.is_small_cap_or_under_followed,
            ),
        )[:max_mentions]
        for m in ordered:
            tag = " [under-followed]" if m.is_small_cap_or_under_followed else ""
            sub = f" / {m.sublayer}" if m.sublayer else ""
            lines.append(
                f"- {m.ticker} ({m.layer}{sub}){tag} -- {m.company} -- conv={m.conviction}"
                f"\n    thesis: {m.thesis}"
            )
    else:
        lines.append("- (none extracted)")

    # Themes block
    lines.append("")
    lines.append("### Cross-source themes")
    if themes:
        for t in themes[:max_themes]:
            lines.append(f"- **{t.theme}**: {t.summary}")
    else:
        lines.append("- (none extracted)")

    return "\n".join(lines)


def _conviction_rank(level: str) -> int:
    """Cheap ordering helper for sorting mentions by conviction."""
    return {"high": 3, "medium": 2, "low": 1}.get((level or "").lower(), 0)


def _load_active_watchlist(conn: sqlite3.Connection) -> list[str]:
    """Return active watchlist tickers from the DB, fall back to YAML."""
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE active = 1 ORDER BY ticker"
    ).fetchall()
    if rows:
        return [r[0] for r in rows]

    path = Path(WATCHLIST_PATH)
    if not path.exists():
        return []

    import yaml  # local to keep top-of-file imports light

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows_yaml = raw.get("tickers") or []
    return [str(t).upper() for t in rows_yaml if t]


def get_latest_discovery(conn: sqlite3.Connection) -> DiscoverResult | None:
    """Read the most recent discovery row back as a DiscoverResult."""
    row = conn.execute(
        "SELECT id, session_label, layer_focus, queries_json, extracted_json,"
        " cost_usd, created_at"
        " FROM web_research ORDER BY created_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None

    queries: list[str] = []
    try:
        queries = list(json.loads(row[3] or "[]"))
    except (json.JSONDecodeError, TypeError):
        pass

    extraction = DiscoverExtraction()
    try:
        parsed = json.loads(row[4] or "{}")
        extraction = DiscoverExtraction(**parsed)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    return DiscoverResult(
        research_id=row[0],
        session_label=row[1] or "",
        layer_focus=row[2] or "",
        queries=queries,
        extraction=extraction,
        cost_usd=row[5] or 0.0,
        created_at=row[6] or "",
    )
