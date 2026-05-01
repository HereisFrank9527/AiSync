from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.llm.types import ChatRequest, LLMClient
from app.projects.context import ProjectContext
from app.tools.base import ToolResult
from app.tools.registry import ToolRegistry
from app.vector.store import NullVectorStore

FrontendPublisher = Callable[[dict[str, Any]], Awaitable[None]]

SYSTEM_PROMPT = """你是 AiSync 的主 Agent，负责辅助用户创作长篇小说。
优先使用工具读写项目文件，保持章节、角色、世界观和剧情设定一致。
工具结果会同步到前端；最终回答应简洁说明完成了什么或还需要用户提供什么。"""


class MasterAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        project: ProjectContext,
        vector_store: NullVectorStore | None = None,
        publisher: FrontendPublisher | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.llm = llm_client
        self.tools = tool_registry
        self.project = project
        self.vector_store = vector_store or NullVectorStore()
        self.publisher = publisher
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self._interrupted = False

    async def run(self, user_input: str) -> str:
        relevant_context = await self.vector_store.query(user_input)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": self._build_user_content(user_input, relevant_context)}
        ]

        while True:
            if self._interrupted:
                self._interrupted = False
                return "操作已中断，等待新指令。"

            response = await self.llm.chat(
                ChatRequest(
                    messages=messages,
                    tools=self.tools.get_all_schemas(),
                    system=self.system_prompt,
                    stream=True,
                )
            )

            if not response.tool_calls:
                return response.text

            messages.append({"role": "assistant", "content": response.content})
            tool_results: list[dict[str, Any]] = []
            for call in response.tool_calls:
                result = await self._execute_tool_call(call)
                await self._push_to_frontend(result)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": self._tool_call_value(call, "id"),
                        "content": result.content,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

    def interrupt(self) -> None:
        self._interrupted = True

    def _build_user_content(self, user_input: str, relevant_context: list[dict]) -> str:
        if not relevant_context:
            return user_input
        context_text = json.dumps(relevant_context, ensure_ascii=False, indent=2)
        return f"相关项目上下文：\n{context_text}\n\n用户请求：\n{user_input}"

    async def _execute_tool_call(self, call: Any) -> ToolResult:
        name = self._tool_call_value(call, "name")
        params = self._tool_call_value(call, "input") or {}
        tool = self.tools.get_tool(name)
        try:
            return await tool.execute(params, self.project)
        except Exception as exc:
            return ToolResult(content=f"Tool {name} failed: {exc}", metadata={"is_error": True})

    def _tool_call_value(self, call: Any, key: str) -> Any:
        if isinstance(call, dict):
            return call.get(key)
        return getattr(call, key, None)

    async def _push_to_frontend(self, result: ToolResult) -> None:
        if not self.publisher:
            return
        await self.publisher({"type": "tool_result", "content": result.content, "ui_hint": result.ui_hint})
