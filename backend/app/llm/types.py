from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    system: str | list[dict[str, Any]] | None = None
    max_tokens: int = 16000
    stream: bool = False


class ChatResponse(BaseModel):
    content: list[Any]
    text: str
    tool_calls: list[Any] = Field(default_factory=list)
    stop_reason: str | None = None
    raw: Any = None


class LLMClient(Protocol):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        ...
