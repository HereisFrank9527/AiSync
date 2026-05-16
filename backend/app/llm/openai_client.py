from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI, OpenAIError

from app.core.config import Settings
from app.llm.types import ChatRequest, ChatResponse, TextDeltaCallback


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

    async def chat(self, request: ChatRequest, on_text_delta: TextDeltaCallback = None) -> ChatResponse:
        messages = self._prepare_messages(request.messages)
        if request.system:
            system_text = self._system_to_text(request.system)
            messages = [{"role": "system", "content": system_text}, *messages]

        tools_param = [self._to_openai_tool(t) for t in request.tools] if request.tools else None
        params = self._chat_params(messages, tools_param, request.max_tokens)

        stream = request.stream and on_text_delta and not self._should_disable_streaming_for_reasoning_tools(request)
        if stream and on_text_delta:
            response = await self.client.chat.completions.create(
                **params,
                stream=True,
            )
            chunks: list[Any] = []
            tool_call_buffers: dict[int, dict[str, Any]] = {}
            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            async for chunk in response:
                chunks.append(chunk)
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    text_parts.append(delta.content)
                    await on_text_delta(delta.content)
                if delta:
                    reasoning_delta = self._extract_reasoning_content(delta)
                    if reasoning_delta:
                        reasoning_parts.append(reasoning_delta)
                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_call_buffers:
                            tool_call_buffers[idx] = {"id": tc.id or "", "name": "", "arguments": ""}
                        if tc.id:
                            tool_call_buffers[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_call_buffers[idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_call_buffers[idx]["arguments"] += tc.function.arguments
            normalized: list[dict[str, Any]] = []
            for buf in tool_call_buffers.values():
                try:
                    args = json.loads(buf["arguments"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {}
                normalized.append({"id": buf["id"], "name": buf["name"], "input": args})
            return ChatResponse(
                content=chunks,
                text="".join(text_parts),
                reasoning_content="".join(reasoning_parts),
                tool_calls=normalized,
                stop_reason=None,
                raw=chunks,
            )
        else:
            response = await self.client.chat.completions.create(
                **params,
                stream=False,
            )
            message = response.choices[0].message
            reasoning_content = self._extract_reasoning_content(message)
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
                reasoning_content=reasoning_content,
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
                reasoning_content = ""
                for block in content:
                    btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
                    if btype == "text":
                        text_parts.append(
                            block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
                        )
                    elif btype == "reasoning":
                        reasoning_content = str(
                            block.get("reasoning_content", "") if isinstance(block, dict) else getattr(block, "reasoning_content", "")
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
                if reasoning_content and self._should_replay_reasoning_content():
                    assistant_msg["reasoning_content"] = reasoning_content
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

    def _chat_params(
        self,
        messages: list[dict[str, Any]],
        tools_param: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.settings.llm_model_name,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools_param:
            params["tools"] = tools_param
        if self._is_deepseek_thinking_model():
            params["extra_body"] = {
                "thinking": {"type": "enabled" if self.settings.llm_enable_thinking else "disabled"}
            }
            if self.settings.llm_enable_thinking:
                params["reasoning_effort"] = self._deepseek_reasoning_effort()
        return params

    def _should_disable_streaming_for_reasoning_tools(self, request: ChatRequest) -> bool:
        return bool(request.tools and self._should_replay_reasoning_content())

    def _extract_reasoning_content(self, value: Any) -> str:
        direct = getattr(value, "reasoning_content", None)
        if direct:
            return str(direct)
        if isinstance(value, dict):
            nested = value.get("reasoning_content")
            return str(nested) if nested else ""
        extra = getattr(value, "model_extra", None)
        if isinstance(extra, dict) and extra.get("reasoning_content"):
            return str(extra["reasoning_content"])
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                data = model_dump()
            except Exception:
                data = {}
            if isinstance(data, dict) and data.get("reasoning_content"):
                return str(data["reasoning_content"])
        return ""

    def _is_deepseek_provider(self) -> bool:
        marker = f"{self.settings.llm_api_base or ''} {self.settings.llm_model_name}".lower()
        return "deepseek" in marker

    def _is_legacy_deepseek_reasoner(self) -> bool:
        return self.settings.llm_model_name.lower().strip() == "deepseek-reasoner"

    def _is_deepseek_thinking_model(self) -> bool:
        return self._is_deepseek_provider() and not self._is_legacy_deepseek_reasoner()

    def _should_replay_reasoning_content(self) -> bool:
        return self.settings.llm_enable_thinking and self._is_deepseek_thinking_model()

    def _deepseek_reasoning_effort(self) -> str:
        effort = self.settings.llm_effort
        if effort in {"max", "xhigh"}:
            return "max"
        return "high"

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
