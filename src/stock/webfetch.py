"""stock.webfetch -- fetch a URL and extract a clean text body via BeautifulSoup."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECS: float = 15.0
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 stock-research/0.1"
)
DEFAULT_MAX_CHARS: int = 6000


class FetchResult(BaseModel):
    """Outcome of a single URL fetch + extract."""

    url: str
    status: int
    title: str = ""
    text: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        """Truthy when the fetch returned 2xx and produced any text."""
        return 200 <= self.status < 300 and bool(self.text)


def _strip_noise(soup: BeautifulSoup) -> None:
    """Remove obvious non-content tags before text extraction."""
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form", "iframe", "svg"]):
        tag.decompose()


def _extract_text(soup: BeautifulSoup, max_chars: int) -> str:
    """Pull readable text from the most likely content node."""
    # Prefer <article>, then <main>, then the first <div> with `article` in id/class, then <body>
    candidates: list[Any] = []
    if soup.article:
        candidates.append(soup.article)
    if soup.main:
        candidates.append(soup.main)
    candidates.extend(soup.find_all("div", id=lambda v: bool(v) and "article" in v.lower()))
    candidates.extend(soup.find_all("div", class_=lambda v: bool(v) and "article" in v.lower()))
    if soup.body:
        candidates.append(soup.body)

    for node in candidates:
        text = node.get_text(separator="\n", strip=True)
        if text and len(text) > 200:
            return text[:max_chars]

    # Last resort: whole-document text
    text = soup.get_text(separator="\n", strip=True)
    return text[:max_chars]


def fetch(url: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> FetchResult:
    """Fetch a URL and return cleaned text. Never raises; failure goes in `error`."""
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    try:
        with httpx.Client(
            timeout=HTTP_TIMEOUT_SECS,
            follow_redirects=True,
            headers=headers,
        ) as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        return FetchResult(url=url, status=0, error=f"transport error: {exc}")

    # Skip non-HTML responses cleanly
    content_type = resp.headers.get("content-type", "").lower()
    if "html" not in content_type and "xml" not in content_type:
        return FetchResult(
            url=url,
            status=resp.status_code,
            error=f"non-html content-type: {content_type or 'unknown'}",
        )

    if not (200 <= resp.status_code < 300):
        return FetchResult(url=url, status=resp.status_code, error=f"HTTP {resp.status_code}")

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:  # noqa: BLE001 -- bs4 raises generic Exception variants
        return FetchResult(url=url, status=resp.status_code, error=f"parse error: {exc}")

    title = soup.title.string.strip() if (soup.title and soup.title.string) else ""
    _strip_noise(soup)
    text = _extract_text(soup, max_chars=max_chars)
    return FetchResult(url=url, status=resp.status_code, title=title, text=text)


def fetch_many(urls: list[str], *, max_chars: int = DEFAULT_MAX_CHARS) -> list[FetchResult]:
    """Fetch a batch of URLs serially (cheap, network-bound, fine for small N)."""
    seen: set[str] = set()
    results: list[FetchResult] = []
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        results.append(fetch(url, max_chars=max_chars))
    return results
