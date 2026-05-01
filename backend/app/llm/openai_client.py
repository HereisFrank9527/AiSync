from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI, OpenAIError

from app.core.config import Settings
from app.llm.types import ChatRequest, ChatResponse


class OpenAICompatibleLLMClient:
    """LLM client for OpenAI-compatible APIs (OpenAI, DeepSeek, etc.)."""

    def __init__(self, settings: Settings) -> None:
        api_key = settings.llm_api_key or os.getenv(settings.llm_api_key_env)
        if not api_key:
            raise OpenAIError(
                f"API key environment variable '{settings.llm_api_key_env}' is not set. "
                "Set it before starting the backend, or update the preset API key env name."
            )
        self.client = AsyncOpenAI(api_key=api_key, base_url=settings.llm_api_base)
        self.settings = settings

    async def chat(self, request: ChatRequest) -> ChatResponse:
        messages = self._prepare_messages(request.messages)
        if request.system:
            system_text = self._system_to_text(request.system)
            messages = [{"role": "system", "content": system_text}, *messages]

        tools_param = [self._to_openai_tool(t) for t in request.tools] if request.tools else None
        response = await self.client.chat.completions.create(
            model=self.settings.llm_model_name,
            messages=messages,
            tools=tools_param,
            max_tokens=request.max_tokens,
            stream=False,
        )
        message = response.choices[0].message
        # Normalize tool_calls to unified dict format: {id, name, input}
        normalized: list[dict[str, Any]] = []
        for tc in message.tool_calls or []:
            args_str = tc.function.arguments or "{}"
            try:
                args = json.loads(args_str)
            except (json.JSONDecodeError, TypeError):
                args = {}
            normalized.append({"id": tc.id, "name": tc.function.name, "input": args})

        return ChatResponse(
            content=[message.model_dump()],
            text=message.content or "",
            tool_calls=normalized,
            stop_reason=response.choices[0].finish_reason,
            raw=response,
        )

    def _prepare_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert agent-internal (Anthropic-style) messages to OpenAI chat format.

        Handles:
        - assistant messages with content block lists -> OpenAI assistant + tool_calls
        - user messages with tool_result blocks -> OpenAI role=tool messages
        """
        converted: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "assistant" and isinstance(content, list):
                text_parts: list[str] = []
                tc_list: list[dict[str, Any]] = []
                for block in content:
                    btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
                    if btype == "text":
                        text_parts.append(
                            block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
                        )
                    elif btype == "tool_use":
                        bid = block.get("id") if isinstance(block, dict) else getattr(block, "id", "")
                        bname = block.get("name") if isinstance(block, dict) else getattr(block, "name", "")
                        binput = block.get("input") if isinstance(block, dict) else getattr(block, "input", {})
                        tc_list.append({
                            "id": bid,
                            "type": "function",
                            "function": {"name": bname, "arguments": json.dumps(binput, ensure_ascii=False)},
                        })
                assistant_msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts) or None}
                if tc_list:
                    assistant_msg["tool_calls"] = tc_list
                converted.append(assistant_msg)
            elif (
                role == "user"
                and isinstance(content, list)
                and content
                and isinstance(content[0], dict)
                and content[0].get("type") == "tool_result"
            ):
                for block in content:
                    converted.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": str(block.get("content", "")),
                    })
            else:
                converted.append(msg)
        return converted

    def _to_openai_tool(self, tool: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool["input_schema"],
            },
        }

    def _system_to_text(self, system: str | list[dict[str, Any]]) -> str:
        if isinstance(system, str):
            return system
        return "\n\n".join(
            str(block.get("text", "")) for block in system if block.get("type") == "text"
        )
