from __future__ import annotations

import os
from typing import Any

from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from app.core.config import Settings
from app.llm.types import ChatRequest, ChatResponse


class AnthropicLLMClient:
    def __init__(self, settings: Settings) -> None:
        api_key = settings.llm_api_key or os.getenv(settings.llm_api_key_env)
        kwargs: dict[str, Any] = {"max_retries": 3}
        if api_key:
            kwargs["api_key"] = api_key
        if settings.llm_api_base:
            kwargs["base_url"] = settings.llm_api_base
            kwargs["http_client"] = DefaultAsyncHttpxClient()
        self.client = AsyncAnthropic(**kwargs)
        self.settings = settings

    async def chat(self, request: ChatRequest) -> ChatResponse:
        params: dict[str, Any] = {
            "model": self.settings.llm_model_name,
            "max_tokens": request.max_tokens,
            "messages": request.messages,
        }
        if request.tools:
            params["tools"] = request.tools
        if request.system:
            params["system"] = self._system_with_cache(request.system)
        elif self.settings.llm_prompt_cache:
            params["cache_control"] = {"type": "ephemeral"}
        if self.settings.llm_enable_thinking:
            params["thinking"] = {"type": "adaptive"}
            params["output_config"] = {"effort": self.settings.llm_effort}

        if request.stream:
            async with self.client.messages.stream(**params) as stream:
                async for _ in stream:
                    pass
                response = await stream.get_final_message()
        else:
            response = await self.client.messages.create(**params)

        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        tool_calls: list[dict[str, Any]] = [
            {"id": block.id, "name": block.name, "input": block.input, "type": "tool_use"}
            for block in response.content
            if getattr(block, "type", None) == "tool_use"
        ]
        return ChatResponse(
            content=response.content,
            text=text,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            raw=response,
        )

    def _system_with_cache(self, system: str | list[dict[str, Any]]) -> str | list[dict[str, Any]]:
        if not self.settings.llm_prompt_cache:
            return system
        if isinstance(system, str):
            return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if not system:
            return system
        copied = [dict(block) for block in system]
        copied[-1]["cache_control"] = {"type": "ephemeral"}
        return copied
