from __future__ import annotations

import os
from typing import Any

from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from app.core.config import Settings
from app.llm.types import ChatRequest, ChatResponse, TextDeltaCallback
from app.llm.web_sources import extract_anthropic_web_sources


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

    async def chat(self, request: ChatRequest, on_text_delta: TextDeltaCallback = None) -> ChatResponse:
        params = self._request_params(request)

        if request.stream:
            async with self.client.messages.stream(**params) as stream:
                async for event in stream:
                    if on_text_delta:
                        if getattr(event, "type", None) == "content_block_delta":
                            delta = getattr(event, "delta", None)
                            if delta and getattr(delta, "type", None) == "text_delta":
                                text = getattr(delta, "text", "") or ""
                                if text:
                                    await on_text_delta(text)
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
            usage=self._usage(response),
            web_sources=extract_anthropic_web_sources(response.content),
            raw=response,
        )

    def _request_params(self, request: ChatRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.settings.llm_model_name,
            "max_tokens": request.max_tokens or self.settings.llm_max_tokens,
            "messages": request.messages,
        }
        tools = self._tools_with_cache(request.tools) if request.tools else []
        if request.native_web_search:
            tools.append(
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 5,
                }
            )
        if tools:
            params["tools"] = tools
        if request.system:
            params["system"] = self._system_with_cache(request.system)
        elif self.settings.llm_prompt_cache:
            params["cache_control"] = {"type": "ephemeral"}
        if getattr(self.settings, "llm_enable_thinking", False):
            params["thinking"] = {"type": "adaptive"}
            params["output_config"] = {"effort": self._anthropic_effort()}
        return params

    def _anthropic_effort(self) -> str:
        effort = getattr(self.settings, "llm_effort", "high")
        return effort if effort in {"low", "medium", "high", "max"} else "max"

    def _usage(self, response: Any) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        if not usage:
            return {}
        result: dict[str, int] = {}
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if isinstance(input_tokens, int):
            result["input_tokens"] = input_tokens
        if isinstance(output_tokens, int):
            result["output_tokens"] = output_tokens
        if result:
            result["total_tokens"] = result.get("input_tokens", 0) + result.get("output_tokens", 0)
        return result

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

    def _tools_with_cache(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.settings.llm_prompt_cache or not tools:
            return tools
        copied = [dict(tool) for tool in tools]
        copied[-1]["cache_control"] = {"type": "ephemeral"}
        return copied
