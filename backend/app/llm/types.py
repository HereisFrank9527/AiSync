from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    system: str | list[dict[str, Any]] | None = None
    max_tokens: int | None = None
    stream: bool = False
    native_web_search: bool = False


class WebSource(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    provider: str = ""


class ChatResponse(BaseModel):
    content: list[Any]
    text: str
    reasoning_content: str = ""
    tool_calls: list[Any] = Field(default_factory=list)
    stop_reason: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    web_sources: list[WebSource] = Field(default_factory=list)
    raw: Any = None


TextDeltaCallback = Callable[[str], Awaitable[None]] | None


class LLMClient(Protocol):
    settings: Any

    async def chat(self, request: ChatRequest, on_text_delta: TextDeltaCallback = None) -> ChatResponse:
        ...
