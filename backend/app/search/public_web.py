from __future__ import annotations

import html
import re
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from app.llm.types import WebSource

BING_RSS_URL = "https://www.bing.com/search"
MAX_RESPONSE_BYTES = 1_000_000
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(value: str | None, limit: int) -> str:
    text = html.unescape(_TAG_RE.sub(" ", value or ""))
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _valid_url(value: str | None) -> str:
    url = (value or "").strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def parse_bing_rss(payload: str, limit: int) -> list[WebSource]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise ValueError("public search returned invalid RSS") from exc

    sources: list[WebSource] = []
    seen: set[str] = set()
    for item in root.findall("./channel/item"):
        url = _valid_url(item.findtext("link"))
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append(
            WebSource(
                url=url,
                title=_clean_text(item.findtext("title"), 240),
                snippet=_clean_text(item.findtext("description"), 500),
                provider="bing-rss",
            )
        )
        if len(sources) >= limit:
            break
    return sources


async def search_public_web(query: str, limit: int, timeout_seconds: float = 12) -> list[WebSource]:
    headers = {
        "Accept": "application/rss+xml, application/xml, text/xml",
        "User-Agent": "Mozilla/5.0 (compatible; AiSync/0.1; +https://github.com/HereisFrank9527/AiSync)",
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout_seconds) as client:
        response = await client.get(BING_RSS_URL, params={"q": query, "format": "rss"})
        response.raise_for_status()
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError("public search response is too large")
    return parse_bing_rss(response.text, limit)
