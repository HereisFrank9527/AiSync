from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.llm.types import ChatRequest, LLMClient, TextDeltaCallback
from app.projects.context import ProjectContext
from app.tools.base import ToolResult
from app.tools.registry import ToolRegistry
from app.vector.store import NullVectorStore

FrontendPublisher = Callable[[dict[str, Any]], Awaitable[None]]

SYSTEM_PROMPT = """你是 AiSync 的主 Agent，负责辅助用户创作长篇小说。
优先使用工具读写项目文件，保持章节、角色、世界观和剧情设定一致。
工具结果会同步到前端；最终回答应简洁说明完成了什么或还需要用户提供什么。
当需要用户在多个方案中选择时，用“可选方案：”或“下一步选项：”开头，并输出 2-6 个清晰的编号列表项。"""

MAX_MEMORY_MESSAGES = 24
MAX_MEMORY_CHARS = 24000
MAX_SINGLE_MEMORY_MESSAGE_CHARS = 4000
MAX_AGENT_ITERATIONS = 8

TASK_PLAN_DEFAULT = [
    "理解请求",
    "检索相关上下文",
    "分析与整合",
    "输出回复",
]
TASK_PLAN_WRITING = [
    "检索相关设定",
    "梳理章节目标",
    "调用写作工具",
    "整理写作结果",
    "输出回复",
]
TASK_PLAN_WORLDVIEW = [
    "检索相关设定",
    "检查设定冲突",
    "更新世界观文档",
    "整理修改结果",
    "输出回复",
]
TASK_PLAN_CHARACTER = [
    "检索角色档案",
    "比对人物关系",
    "更新角色信息",
    "整理角色结果",
    "输出回复",
]
TASK_PLAN_OUTLINE = [
    "读取大纲结构",
    "梳理剧情节点",
    "更新大纲节点",
    "整理修改结果",
    "输出回复",
]
TASK_PLAN_CONSISTENCY = [
    "检索相关设定",
    "对照冲突点",
    "执行一致性检查",
    "整理问题建议",
    "输出回复",
]
TASK_PLAN_SEARCH = [
    "检索项目索引",
    "汇总命中片段",
    "整理引用路径",
    "输出结果",
]


class AgentInterrupted(Exception):
    pass


def build_task_plan(user_input: str, tool_names: set[str] | None = None) -> list[str]:
    text = user_input.lower()
    names = tool_names or set()
    if "consistency_check" in names or any(
        keyword in text for keyword in ["一致性", "冲突", "矛盾", "检查设定"]
    ):
        return TASK_PLAN_CONSISTENCY
    if "write_chapter" in names or "edit_chapter" in names or any(
        keyword in text for keyword in ["续写", "写章节", "章节", "写作"]
    ):
        return TASK_PLAN_WRITING
    if "update_worldview" in names or any(
        keyword in text for keyword in ["世界观", "设定", "地理", "历史", "规则"]
    ):
        return TASK_PLAN_WORLDVIEW
    if "create_character" in names or any(
        keyword in text for keyword in ["角色", "人物档案", "人设", "角色卡"]
    ):
        return TASK_PLAN_CHARACTER
    if "outline_generate" in names or "plot_outline" in names or any(
        keyword in text for keyword in ["大纲", "剧情", "情节", "节点"]
    ):
        return TASK_PLAN_OUTLINE
    if "search_project" in names or any(
        keyword in text for keyword in ["搜索", "查找", "检索", "引用路径", "资料"]
    ):
        return TASK_PLAN_SEARCH
    return TASK_PLAN_DEFAULT


class MasterAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        project: ProjectContext,
        vector_store: NullVectorStore | None = None,
        publisher: FrontendPublisher | None = None,
        system_prompt: str | None = None,
        enabled_tools: list[str] | None = None,
    ) -> None:
        self.llm = llm_client
        self.tools = tool_registry
        self.project = project
        self.vector_store = vector_store or NullVectorStore()
        self.publisher = publisher
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.enabled_tools = set(enabled_tools) if enabled_tools is not None else None
        self._interrupted = False
        self._running = False

    async def run(
        self,
        user_input: str,
        on_text_delta: TextDeltaCallback = None,
        history: list[dict[str, str]] | None = None,
        memory_summary: str | None = None,
        enabled_tools: list[str] | None = None,
        override_enabled_tools: bool = False,
        max_iterations: int = MAX_AGENT_ITERATIONS,
    ) -> str:
        self._interrupted = False
        self._running = True
        try:
            effective_tools = (
                set(enabled_tools)
                if override_enabled_tools and enabled_tools is not None
                else self.enabled_tools
            )
            if override_enabled_tools and enabled_tools is None:
                effective_tools = None
            task_plan = build_task_plan(user_input)
            await self._push_task_list(task_plan, 0, "retrieving")
            await self._push_agent_status("正在检索项目上下文", "retrieving")
            relevant_context = await self.vector_store.query(user_input)
            messages = self._build_initial_messages(
                user_input,
                relevant_context,
                history or [],
                memory_summary or "",
            )
            await self._push_task_list(task_plan, min(1, len(task_plan) - 1), "thinking")
            context_status = (
                f"已注入 {len(relevant_context)} 条相关上下文"
                if relevant_context
                else "未检索到相关上下文，使用对话历史继续"
            )
            await self._push_agent_status(
                context_status,
                "context_ready",
                {"context_count": len(relevant_context)},
            )

            async def guarded_text_delta(delta: str) -> None:
                if self._interrupted:
                    raise AgentInterrupted()
                if on_text_delta:
                    await on_text_delta(delta)

            iterations = 0
            while True:
                if self._interrupted:
                    return await self._finish_interrupted()
                if iterations >= max_iterations:
                    message = (
                        f"已达到本轮 Agent 最大迭代次数（{max_iterations}）。"
                        "为避免工具调用循环，已暂停继续执行。请根据当前结果继续给出下一步指令。"
                    )
                    await self._push_agent_event("agent_limit_reached", message, {"max_iterations": max_iterations})
                    await self._push_agent_status(message, "error", {"max_iterations": max_iterations})
                    return message
                iterations += 1

                await self._push_agent_status("正在请求模型", "thinking", {"iteration": iterations})
                await self._push_task_list(
                    task_plan,
                    min(1, len(task_plan) - 1),
                    "thinking",
                    {"iteration": iterations},
                )
                try:
                    response = await self.llm.chat(
                        ChatRequest(
                            messages=messages,
                            tools=self.tools.get_schemas(effective_tools),
                            system=self.system_prompt,
                            stream=True,
                        ),
                        on_text_delta=guarded_text_delta,
                    )
                except AgentInterrupted:
                    return await self._finish_interrupted()

                if self._interrupted:
                    return await self._finish_interrupted()

                if not response.tool_calls:
                    final_index = len(task_plan) - 1
                    await self._push_task_list(
                        task_plan,
                        final_index,
                        "finalizing",
                        {"iteration": iterations},
                    )
                    await self._push_agent_status("回复已生成", "done", {"iteration": iterations})
                    await self._push_task_list(
                        task_plan,
                        len(task_plan),
                        "done",
                        {"iteration": iterations},
                    )
                    return response.text

                tool_names = {
                    name
                    for call in response.tool_calls
                    if (name := self._tool_call_value(call, "name"))
                }
                refined_task_plan = build_task_plan(user_input, tool_names)
                if refined_task_plan != task_plan:
                    task_plan = refined_task_plan
                await self._push_agent_status(
                    f"模型请求调用 {len(response.tool_calls)} 个工具",
                    "tool_calling",
                    {"iteration": iterations, "tool_calls": len(response.tool_calls)},
                )
                await self._push_task_list(
                    task_plan,
                    min(2, len(task_plan) - 1),
                    "tool_calling",
                    {"iteration": iterations, "tool_calls": len(response.tool_calls)},
                )
                assistant_blocks: list[dict[str, Any]] = []
                if response.text:
                    assistant_blocks.append({"type": "text", "text": response.text})
                for call in response.tool_calls:
                    assistant_blocks.append(
                        {
                            "type": "tool_use",
                            "id": self._tool_call_value(call, "id"),
                            "name": self._tool_call_value(call, "name"),
                            "input": self._tool_call_value(call, "input") or {},
                        }
                    )
                if assistant_blocks:
                    messages.append({"role": "assistant", "content": assistant_blocks})
                tool_results: list[dict[str, Any]] = []
                for call in response.tool_calls:
                    if self._interrupted:
                        return await self._finish_interrupted()
                    result = await self._execute_tool_call(call, effective_tools)
                    await self._push_to_frontend(result)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": self._tool_call_value(call, "id"),
                            "content": result.content,
                        }
                    )
                messages.append({"role": "user", "content": tool_results})
                await self._push_task_list(
                    task_plan,
                    len(task_plan) - 1,
                    "finalizing",
                    {"iteration": iterations},
                )
        finally:
            self._running = False

    def interrupt(self) -> bool:
        if not self._running:
            return False
        self._interrupted = True
        return True

    async def _finish_interrupted(self) -> str:
        self._interrupted = False
        message = "操作已中断，等待新指令。"
        await self._push_agent_status(message, "interrupted")
        return message

    def _build_initial_messages(
        self,
        user_input: str,
        relevant_context: list[dict],
        history: list[dict[str, str]],
        memory_summary: str,
    ) -> list[dict[str, Any]]:
        memory_messages = self._conversation_memory_messages(history)
        summary_message = self._summary_memory_message(memory_summary)
        current_content = user_input
        if relevant_context:
            current_content = (
                "相关项目上下文：\n"
                f"{self._compact_context(relevant_context)}\n\n"
                "用户请求：\n"
                f"{user_input}"
            )
        return [*summary_message, *memory_messages, {"role": "user", "content": current_content}]

    def _summary_memory_message(self, memory_summary: str) -> list[dict[str, Any]]:
        summary = memory_summary.strip()
        if not summary:
            return []
        return [
            {
                "role": "user",
                "content": (
                    "以下是本会话较早内容的压缩记忆。它是历史上下文，不是当前新指令：\n\n"
                    f"{summary}"
                ),
            }
        ]

    def _conversation_memory_messages(self, history: list[dict[str, str]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, str]] = []
        for item in history:
            role = item.get("role")
            if role not in {"user", "agent", "assistant"}:
                continue
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            if len(content) > MAX_SINGLE_MEMORY_MESSAGE_CHARS:
                content = f"{content[:MAX_SINGLE_MEMORY_MESSAGE_CHARS]}\n\n[以上历史消息已截断]"
            normalized.append({"role": "assistant" if role in {"agent", "assistant"} else "user", "content": content})

        recent = normalized[-MAX_MEMORY_MESSAGES:]
        total = 0
        selected: list[dict[str, str]] = []
        for item in reversed(recent):
            length = len(item["content"])
            if selected and total + length > MAX_MEMORY_CHARS:
                break
            total += length
            selected.append(item)
        return list(reversed(selected))

    def _compact_context(self, relevant_context: list[dict]) -> str:
        lines: list[str] = []
        for item in relevant_context[:8]:
            path = item.get("path") or item.get("file") or "unknown"
            content = item.get("content") or item.get("text")
            if content is None:
                content = json.dumps(item, ensure_ascii=False, indent=2)
            else:
                content = str(content)
            if len(content) > 1200:
                content = f"{content[:1200]}\n[上下文片段已截断]"
            lines.append(f"- {path}:\n{content}")
        return "\n\n".join(lines)

    async def _execute_tool_call(self, call: Any, enabled_tools: set[str] | None = None) -> ToolResult:
        name = self._tool_call_value(call, "name")
        params = self._tool_call_value(call, "input") or {}
        started = time.perf_counter()
        await self._push_tool_event("tool_call_start", name, params)
        if enabled_tools is not None and name not in enabled_tools:
            result = ToolResult(content=f"Tool {name} is disabled for this agent preset.", metadata={"is_error": True})
            await self._push_tool_event("tool_call_error", name, params, started, result.content)
            return result
        tool = self.tools.get_tool(name)
        try:
            result = await tool.execute(params, self.project)
            await self._push_tool_event("tool_call_end", name, params, started)
            return result
        except Exception as exc:
            result = ToolResult(content=f"Tool {name} failed: {exc}", metadata={"is_error": True})
            await self._push_tool_event("tool_call_error", name, params, started, str(exc))
            return result

    def _tool_call_value(self, call: Any, key: str) -> Any:
        if isinstance(call, dict):
            return call.get(key)
        return getattr(call, key, None)

    async def _push_to_frontend(self, result: ToolResult) -> None:
        if not self.publisher:
            return
        await self.publisher({"type": "tool_result", "content": result.content, "ui_hint": result.ui_hint})

    async def _push_agent_event(
        self,
        event_type: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.publisher:
            return
        event: dict[str, Any] = {"type": event_type, "content": content}
        if metadata:
            event["metadata"] = metadata
        await self.publisher(event)

    async def _push_agent_status(
        self,
        content: str,
        phase: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        data = {"phase": phase}
        if metadata:
            data.update(metadata)
        await self._push_agent_event("agent_status", content, data)

    async def _push_task_list(
        self,
        task_plan: list[str],
        current_index: int,
        phase: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.publisher:
            return
        tasks = []
        safe_index = max(0, current_index)
        for index, label in enumerate(task_plan):
            if index < safe_index:
                status = "done"
            elif index == safe_index:
                status = "active"
            else:
                status = "pending"
            if safe_index >= len(task_plan):
                status = "done"
            tasks.append({"label": label, "status": status})
        payload: dict[str, Any] = {
            "type": "agent_task_list",
            "content": "Agent 任务列表已更新",
            "metadata": {
                "phase": phase,
                "current_task_index": min(safe_index, len(task_plan)),
                "tasks": tasks,
            },
        }
        if metadata:
            payload["metadata"].update(metadata)
        await self.publisher(payload)

    async def _push_tool_event(
        self,
        event_type: str,
        name: str,
        params: dict[str, Any],
        started: float | None = None,
        error: str | None = None,
    ) -> None:
        if not self.publisher:
            return
        event: dict[str, Any] = {
            "type": event_type,
            "tool": {"name": name, "params": self._summarize_params(params)},
        }
        if started is not None:
            event["tool"]["duration_ms"] = round((time.perf_counter() - started) * 1000)
        if error:
            event["tool"]["error"] = error
        await self.publisher(event)

    def _summarize_params(self, params: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str):
                summary[key] = f"{value[:120]}..." if len(value) > 120 else value
            elif isinstance(value, (int, float, bool)) or value is None:
                summary[key] = value
            elif isinstance(value, list):
                summary[key] = f"list[{len(value)}]"
            elif isinstance(value, dict):
                summary[key] = f"object[{len(value)}]"
            else:
                summary[key] = str(value)[:120]
        return summary
