"""stock.websearch -- web search clients (Tavily primary, Serper / Brave fallbacks)."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import BaseModel

from stock.config import get_settings

logger = logging.getLogger(__name__)

TAVILY_URL: str = "https://api.tavily.com/search"
SERPER_URL: str = "https://google.serper.dev/search"
BRAVE_URL: str = "https://api.search.brave.com/res/v1/web/search"
HTTP_TIMEOUT_SECS: float = 20.0


class SearchResult(BaseModel):
    """One search hit, normalized across backends."""

    title: str
    url: str
    snippet: str = ""
    score: float = 0.0
    backend: str = ""


class WebSearchUnavailable(RuntimeError):
    """Raised when no search backend is configured / reachable."""


def _normalize_tavily(payload: dict[str, Any]) -> list[SearchResult]:
    """Map Tavily JSON to SearchResult list."""
    out: list[SearchResult] = []
    for row in payload.get("results", []) or []:
        if not isinstance(row, dict):
            continue
        out.append(
            SearchResult(
                title=str(row.get("title", "")).strip(),
                url=str(row.get("url", "")).strip(),
                snippet=str(row.get("content", "") or row.get("description", "")).strip(),
                score=float(row.get("score", 0.0) or 0.0),
                backend="tavily",
            )
        )
    return out


def _normalize_serper(payload: dict[str, Any]) -> list[SearchResult]:
    """Map Serper.dev JSON to SearchResult list."""
    out: list[SearchResult] = []
    for row in payload.get("organic", []) or []:
        if not isinstance(row, dict):
            continue
        out.append(
            SearchResult(
                title=str(row.get("title", "")).strip(),
                url=str(row.get("link", "")).strip(),
                snippet=str(row.get("snippet", "")).strip(),
                score=0.0,
                backend="serper",
            )
        )
    return out


def _normalize_brave(payload: dict[str, Any]) -> list[SearchResult]:
    """Map Brave Search JSON to SearchResult list."""
    out: list[SearchResult] = []
    web = payload.get("web") or {}
    for row in web.get("results", []) or []:
        if not isinstance(row, dict):
            continue
        out.append(
            SearchResult(
                title=str(row.get("title", "")).strip(),
                url=str(row.get("url", "")).strip(),
                snippet=str(row.get("description", "")).strip(),
                score=0.0,
                backend="brave",
            )
        )
    return out


def _search_tavily(query: str, *, max_results: int, api_key: str) -> list[SearchResult]:
    """Hit Tavily's search endpoint."""
    body = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }
    with httpx.Client(timeout=HTTP_TIMEOUT_SECS) as client:
        resp = client.post(TAVILY_URL, json=body)
    resp.raise_for_status()
    return _normalize_tavily(resp.json())


def _search_serper(query: str, *, max_results: int, api_key: str) -> list[SearchResult]:
    """Hit Serper.dev (Google results via API)."""
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    body = {"q": query, "num": max_results}
    with httpx.Client(timeout=HTTP_TIMEOUT_SECS) as client:
        resp = client.post(SERPER_URL, json=body, headers=headers)
    resp.raise_for_status()
    return _normalize_serper(resp.json())


def _search_brave(query: str, *, max_results: int, api_key: str) -> list[SearchResult]:
    """Hit Brave Search Web API."""
    headers = {"X-Subscription-Token": api_key, "Accept": "application/json"}
    params = {"q": query, "count": max_results}
    with httpx.Client(timeout=HTTP_TIMEOUT_SECS) as client:
        resp = client.get(BRAVE_URL, headers=headers, params=params)
    resp.raise_for_status()
    return _normalize_brave(resp.json())


def search(
    query: str, *, max_results: int = 5
) -> list[SearchResult]:
    """Run a single web search via the configured backend.

    Backend resolution order: explicit `WEB_SEARCH_BACKEND` env override,
    else first non-empty key among Tavily, Serper, Brave.
    Raises WebSearchUnavailable when no backend is configured.
    """
    settings = get_settings()
    preferred = (settings.web_search_backend or "").strip().lower()

    candidates: list[tuple[str, str]] = []
    if preferred == "tavily" and settings.tavily_api_key:
        candidates.append(("tavily", settings.tavily_api_key))
    if preferred == "serper" and settings.serper_api_key:
        candidates.append(("serper", settings.serper_api_key))
    if preferred == "brave" and settings.brave_api_key:
        candidates.append(("brave", settings.brave_api_key))

    # Fall back to "first key set" order if no explicit preference matched
    if not candidates:
        if settings.tavily_api_key:
            candidates.append(("tavily", settings.tavily_api_key))
        if settings.serper_api_key:
            candidates.append(("serper", settings.serper_api_key))
        if settings.brave_api_key:
            candidates.append(("brave", settings.brave_api_key))

    if not candidates:
        raise WebSearchUnavailable(
            "no search backend configured -- set TAVILY_API_KEY (preferred),"
            " SERPER_API_KEY, or BRAVE_API_KEY in .env"
        )

    last_error: Exception | None = None
    for backend, key in candidates:
        try:
            if backend == "tavily":
                return _search_tavily(query, max_results=max_results, api_key=key)
            if backend == "serper":
                return _search_serper(query, max_results=max_results, api_key=key)
            if backend == "brave":
                return _search_brave(query, max_results=max_results, api_key=key)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("web search backend %s failed: %s", backend, exc)
            last_error = exc
            continue

    raise WebSearchUnavailable(f"all configured backends failed; last error: {last_error}")


def search_many(
    queries: list[str], *, max_results_per_query: int = 5
) -> dict[str, list[SearchResult]]:
    """Run a batch of queries serially. Per-query failures are logged, not raised."""
    out: dict[str, list[SearchResult]] = {}
    for query in queries:
        if not query.strip():
            continue
        try:
            out[query] = search(query, max_results=max_results_per_query)
        except WebSearchUnavailable:
            raise  # propagate config errors immediately
        except Exception as exc:
            logger.warning("search failed for query=%r: %s", query, exc)
            out[query] = []
    return out
