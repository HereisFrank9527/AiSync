from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from app.llm.types import WebSource

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_MAX_RESULTS = 20
MAX_RESPONSE_BYTES = 5_000_000
MAX_SNIPPET_CHARS = 4_000


@dataclass
class TavilySearchResult:
    sources: list[WebSource]
    credits: float = 0
    request_id: str = ""
    response_time: float | None = None
    raw_usage: dict[str, Any] = field(default_factory=dict)


def _valid_url(value: Any) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def parse_tavily_response(payload: dict[str, Any], limit: int) -> TavilySearchResult:
    sources: list[WebSource] = []
    seen: set[str] = set()
    raw_results = payload.get("results")
    for item in raw_results if isinstance(raw_results, list) else []:
        if not isinstance(item, dict):
            continue
        url = _valid_url(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        raw_content = str(item.get("raw_content") or "").strip()
        content = raw_content or str(item.get("content") or "").strip()
        sources.append(
            WebSource(
                url=url,
                title=_text(item.get("title"), 240),
                snippet=_text(content, MAX_SNIPPET_CHARS),
                provider="tavily",
            )
        )
        if len(sources) >= limit:
            break

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    credits_value = usage.get("credits", 0)
    credits = float(credits_value) if isinstance(credits_value, (int, float)) else 0
    response_time_value = payload.get("response_time")
    try:
        response_time = float(response_time_value) if response_time_value is not None else None
    except (TypeError, ValueError):
        response_time = None
    return TavilySearchResult(
        sources=sources,
        credits=credits,
        request_id=str(payload.get("request_id") or ""),
        response_time=response_time,
        raw_usage=usage,
    )


async def search_tavily(
    query: str,
    api_key: str,
    limit: int,
    *,
    search_depth: str = "basic",
    include_raw_content: bool = False,
    timeout_seconds: float = 20,
    transport: httpx.AsyncBaseTransport | None = None,
) -> TavilySearchResult:
    depth = search_depth if search_depth in {"basic", "advanced"} else "basic"
    body: dict[str, Any] = {
        "query": query,
        "search_depth": depth,
        "max_results": max(1, min(int(limit), TAVILY_MAX_RESULTS)),
        "include_answer": False,
        "include_raw_content": "text" if include_raw_content else False,
        "include_images": False,
        "include_usage": True,
    }
    if depth == "advanced":
        body["chunks_per_source"] = 3
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "AiSync/0.1 (+https://github.com/HereisFrank9527/AiSync)",
    }
    async with httpx.AsyncClient(
        headers=headers,
        timeout=timeout_seconds,
        transport=transport,
    ) as client:
        response = await client.post(TAVILY_SEARCH_URL, json=body)
        response.raise_for_status()
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError("Tavily response is too large")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Tavily returned an invalid response")
    return parse_tavily_response(payload, limit)
