from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlparse

from app.llm.types import WebSource

MAX_WEB_SOURCES = 12
_SOURCE_COLLECTION_KEYS = (
    "annotations",
    "citations",
    "sources",
    "references",
    "search_results",
    "web_sources",
    "results",
)
_RESPONSE_NESTED_KEYS = ("choices", "message", "delta", "output", "content", "data")
_MARKDOWN_URL_RE = re.compile(r"\[([^\]]+)]\((https?://[^\s)]+)\)", re.IGNORECASE)
_PLAIN_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}，。；：！？）》】"


def _value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    direct = getattr(value, key, default)
    if direct is not default:
        return direct
    extra = getattr(value, "model_extra", None)
    if isinstance(extra, dict):
        return extra.get(key, default)
    return default


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _valid_url(value: Any) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _source(value: Any, provider: str, fallback_snippet: str = "") -> WebSource | None:
    citation = _value(value, "url_citation") or _value(value, "source") or value
    url = _valid_url(
        _value(citation, "url")
        or _value(citation, "link")
        or _value(citation, "href")
        or _value(citation, "source_url")
    )
    if not url:
        return None
    snippet = (
        _value(citation, "cited_text")
        or _value(citation, "snippet")
        or _value(citation, "description")
        or fallback_snippet
    )
    return WebSource(
        url=url,
        title=_text(_value(citation, "title") or _value(citation, "name"), 240),
        snippet=_text(snippet, 500),
        provider=provider,
    )


def merge_web_sources(*groups: Iterable[WebSource]) -> list[WebSource]:
    merged: dict[str, WebSource] = {}
    for group in groups:
        for source in group:
            current = merged.get(source.url)
            if current is None:
                if len(merged) >= MAX_WEB_SOURCES:
                    continue
                merged[source.url] = source
                continue
            merged[source.url] = WebSource(
                url=current.url,
                title=current.title or source.title,
                snippet=current.snippet or source.snippet,
                provider=current.provider or source.provider,
            )
    return list(merged.values())


def _source_collection(value: Any, provider: str, depth: int = 0) -> list[WebSource]:
    if value is None or depth > 5:
        return []
    sources: list[WebSource] = []
    for candidate in _items(value):
        if isinstance(candidate, str):
            source = _source({"url": candidate}, provider)
        else:
            source = _source(candidate, provider)
        if source:
            sources.append(source)
            continue
        for key in (*_SOURCE_COLLECTION_KEYS, "items"):
            nested = _value(candidate, key)
            if nested is not None:
                sources.extend(_source_collection(nested, provider, depth + 1))
    return sources


def _extract_openai_value(value: Any, depth: int = 0) -> list[WebSource]:
    if value is None or depth > 5:
        return []
    content_value = _value(value, "content")
    content = content_value if isinstance(content_value, str) else ""
    sources: list[WebSource] = []
    for annotation in _items(_value(value, "annotations")):
        citation = _value(annotation, "url_citation") or annotation
        snippet = ""
        start = _value(citation, "start_index")
        end = _value(citation, "end_index")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(content):
            snippet = content[start:end]
        source = _source(citation, "openai", snippet)
        if source:
            sources.append(source)

    for key in _SOURCE_COLLECTION_KEYS[1:]:
        sources.extend(_source_collection(_value(value, key), "openai"))

    for key in _RESPONSE_NESTED_KEYS:
        nested = _value(value, key)
        if nested is None or isinstance(nested, str):
            continue
        for item in _items(nested):
            sources.extend(_extract_openai_value(item, depth + 1))
    return sources


def extract_openai_web_sources(*values: Any) -> list[WebSource]:
    sources: list[WebSource] = []
    for value in values:
        sources.extend(_extract_openai_value(value))
    return merge_web_sources(sources)


def extract_text_web_sources(text: str, provider: str = "provider-text") -> list[WebSource]:
    """Extract only explicit HTTP(S) links returned by a native-search response."""
    sources: list[WebSource] = []
    markdown_urls: set[str] = set()
    for title, raw_url in _MARKDOWN_URL_RE.findall(text or ""):
        url = raw_url.rstrip(_TRAILING_URL_PUNCTUATION)
        source = _source({"url": url, "title": title}, provider)
        if source:
            markdown_urls.add(source.url)
            sources.append(source)
    for raw_url in _PLAIN_URL_RE.findall(text or ""):
        url = raw_url.rstrip(_TRAILING_URL_PUNCTUATION)
        if url in markdown_urls:
            continue
        source = _source({"url": url}, provider)
        if source:
            sources.append(source)
    return merge_web_sources(sources)


def extract_anthropic_web_sources(content_blocks: Any) -> list[WebSource]:
    sources: list[WebSource] = []
    for block in _items(content_blocks):
        block_type = str(_value(block, "type") or "")
        if block_type == "text":
            for citation in _items(_value(block, "citations")):
                source = _source(citation, "anthropic")
                if source:
                    sources.append(source)
            continue

        candidates = _value(block, "content") if block_type == "web_search_tool_result" else block
        for candidate in _items(candidates):
            candidate_type = str(_value(candidate, "type") or "")
            if candidate_type not in {"web_search_result", "web_search_result_location"}:
                continue
            source = _source(candidate, "anthropic")
            if source:
                sources.append(source)
    return merge_web_sources(sources)
