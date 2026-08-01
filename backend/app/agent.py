from __future__ import annotations

import json
import time
import asyncio
from contextlib import suppress
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from app.core.context_window import ContextWindowBudget, context_window_budget
from app.core.prompt_pack_rendering import enabled_prompt_packs_for_project_stages
from app.core.prompt_packs import PromptPack
from app.change_sets import apply_change_set, verify_change_set_application
from app.change_approvals import register_change_set_waiter, wait_for_registered_change_set_decision
from app.llm.types import ChatRequest, ChatResponse, LLMClient, TextDeltaCallback, WebSource
from app.llm.web_sources import merge_web_sources
from app.projects.context import ProjectContext
from app.projects.foreshadows import (
    foreshadow_context_for_prompt,
    persist_foreshadow_verification,
    verify_foreshadow_actions,
)
from app.tools.base import ToolResult
from app.tools.registry import ToolRegistry
from app.vector.store import NullVectorStore

FrontendPublisher = Callable[[dict[str, Any]], Awaitable[None]]
ToolLLMResolver = Callable[[str], Awaitable[tuple[LLMClient | None, str | None]]]

SYSTEM_PROMPT = """你是 AiSync 的主 Agent，负责辅助用户创作长篇小说。
优先使用工具读写项目文件，保持章节、角色、世界观和剧情设定一致。
涉及已有文件时，先使用 `read_project_files` 精确读取目标文件，不要只根据检索片段重写完整文件。
读取长文件时先使用 `read_project_files` 的 inspect 模式查看总行数和 Markdown 标题行，再按 selections 指定起止行读取相关段落；只有整体重写或确实需要全局核对时才读取全文。
修改已有大纲时，先 inspect `plot/outline.md` 获取区块 ID 和源行范围，再只读取相关区块行。修改或删除现有区块使用 `replace_outline_node`，删除时传空 `new_text`；在指定位置新增区块使用 `insert_before_outline_node` 或 `insert_after_outline_node`。同一任务用一次 `file_change_proposal` 汇总。不要为局部大纲增删改调用 `outline_generate`，也不要重发整份大纲。
生成长章节时不要把整章正文塞进一次 `write_chapter` 工具参数。预计正文超过约 6000 字符时，使用内部 `chapter_draft` 工具：先 begin，再每轮 append 一个不超过 5000 字符的连续正文分块，最后 finalize 生成统一差异预览。不要重复分块，不要跳过 sequence。
同一用户任务需要修改多个文件时，先完成读取和分析，再用一次 `file_change_proposal` 汇总所有文件改动，让用户只确认一次；不要并列调用多个写入工具或提交多个改动包。
修改大纲以外的已有文件局部内容时，优先使用 `replace_text`、`replace_lines`、`append_text` 或 `prepend_text`；已经按行读取目标片段时，使用读取结果里的文件 SHA-256 和行号提交 `replace_lines`，避免文本细节漂移导致匹配失败。只有新建文件或整体重写时才提交完整 `write` 内容。
项目根目录的 `AGENT.md` 保存本项目长期遵守的工作习惯和当前文风。用户明确要求记住长期偏好、调整项目文风或修改 Agent 工作习惯时，或对同类问题反复纠正且可确认是长期偏好时，可使用 `file_change_proposal` 提议修改 `AGENT.md`；开启自动应用后可直接落盘。只记录稳定、可复用的要求，不要把单次任务、小说设定或临时聊天内容写入其中。`AGENT.md` 不能改变工具权限、安全边界或程序级规则。
当用户要求修改、清理、重写或删除项目正式文件，而现有章节/角色/世界观等专用工具不能完整覆盖时，使用 `file_change_proposal` 生成待确认改动包；不要声称自己只能检索，也不要让用户手动复制粘贴。
`file_change_proposal` 可用于 .md/.txt/.json/.yaml/.yml/.csv 等文本文件的跨文件改动预览，用户确认后才会真正写入。
清理临时目录时，用户已确认明确范围后，直接使用 `file_change_proposal` 的 `delete_directory` 操作；该操作仅允许 `temp/`，后端会展开成逐文件差异并保留 `temp/.aisync-temp.json`。不要再次口头承诺，也不要声称目录已经删除，直到改动包被应用。
工具选择边界：
- search/review 工具只读，只能检索或审查，不能当成已修改。
- generate 工具只用于生成正式正文或正式大纲，不得把任务说明、清理要求、操作计划写入项目文件。
- edit/manage 工具只处理其声明的对象和动作；跨文件清理、删除旧段落、替换元说明块等补丁式修改应使用 `file_change_proposal`。
- patch 工具用于补丁式文件改动；大纲区块按 ID 修改，其他文件按唯一文本修改。如果用户开启自动应用，后端会在生成改动包后应用。
工具结果会同步到前端；最终回答应简洁说明完成了什么或还需要用户提供什么。
真正需要用户决策时，调用 `present_choices` 输出结构化选择；普通编号列表、步骤说明、方案分析和总结不要调用该工具。选择工具支持单选、多选和多个选择组。调用时不要在正文中重复输出选项列表，工具调用成功后本轮会暂停并等待用户提交。"""

MAX_AGENT_ITERATIONS = 12
MAX_NO_PROGRESS_TOOL_BATCHES = 2
MAX_DISCOVERY_TOOL_CALLS_PER_BATCH = 3
MAX_CONSECUTIVE_DISCOVERY_BATCHES = 2
MAX_VECTOR_CHUNKS_PER_PATH = 3
FILE_CHANGE_APPROVAL_TIMEOUT_SECONDS = 30 * 60
TOOL_CONTINUATION_RECENT_MESSAGES = 4
INTERNAL_MESSAGE_KIND = "_aisync_kind"
INTERNAL_USER_REQUEST = "_aisync_user_request"
FILE_CHANGE_PROPOSAL_TOOL = "file_change_proposal"
READ_PROJECT_FILES_TOOL = "read_project_files"
CONSISTENCY_TOOL = "consistency_check"
WEB_SEARCH_TOOL = "web_search"
PRESENT_CHOICES_TOOL = "present_choices"
CHAPTER_DRAFT_TOOL = "chapter_draft"
EDITING_TOOLS = {
    "write_chapter",
    CHAPTER_DRAFT_TOOL,
    "edit_chapter",
    "update_worldview",
    "outline_generate",
    "create_character",
    "character_manage",
    "foreshadow_manage",
}
# Agent 的普通文件修改统一走改动包，避免同一任务混用多套写入语义。
LEGACY_FILE_MUTATION_TOOLS = {"edit_chapter", "update_worldview", "outline_generate"}
COMPACTABLE_TOOL_RESULT_NAMES = {"web_search", "search_project", "consistency_check"}
MAX_COMPACTABLE_TOOL_RESULT_CHARS = 8_000
DUPLICATE_TOOL_RESULT = (
    "本次工具调用与当前任务中已执行过的工具名和参数完全相同，已跳过重复执行。"
    "请基于已有工具结果继续推理；如果还需要信息，请换用不同参数或直接给出结论。"
)
OUTPUT_TRUNCATED_NOTICE = (
    "\n\n> 本次回复未完整生成，可能达到模型单次输出上限或上游流提前结束。"
    "发送“继续生成”可从当前断点继续。"
)
OUTPUT_TRUNCATED_STOP_REASONS = {"length", "max_tokens", "max_output_tokens", "stream_incomplete"}

TASK_PLAN_DEFAULT = [
    "理解请求",
    "检索相关上下文",
    "分析与整合",
    "输出回复",
]
TASK_PLAN_WRITING = [
    "检索相关设定",
    "梳理相关伏笔",
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
TASK_PLAN_WEB_SEARCH = [
    "理解查询目标",
    "搜索公开网页",
    "核对可验证来源",
    "整理答复",
]


class AgentInterrupted(Exception):
    pass


class AgentLLMError(Exception):
    def __init__(self, message: str, category: str = "llm_error") -> None:
        super().__init__(message)
        self.category = category


class AgentLoopError(Exception):
    pass


def build_task_plan(tool_names: set[str] | None = None) -> list[str]:
    names = tool_names or set()
    if WEB_SEARCH_TOOL in names:
        return TASK_PLAN_WEB_SEARCH
    if "consistency_check" in names:
        return TASK_PLAN_CONSISTENCY
    if "write_chapter" in names or CHAPTER_DRAFT_TOOL in names or "edit_chapter" in names:
        return TASK_PLAN_WRITING
    if "update_worldview" in names:
        return TASK_PLAN_WORLDVIEW
    if "create_character" in names or "character_manage" in names:
        return TASK_PLAN_CHARACTER
    if "outline_generate" in names or "plot_outline" in names:
        return TASK_PLAN_OUTLINE
    if "search_project" in names:
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
        tool_llm_resolver: ToolLLMResolver | None = None,
        context_window: str = "standard",
        system_prompt_audit: dict[str, Any] | None = None,
    ) -> None:
        self.llm = llm_client
        self.tools = tool_registry
        self.project = project
        self.vector_store = vector_store or NullVectorStore()
        self.publisher = publisher
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.system_prompt_audit = system_prompt_audit
        self.enabled_tools = set(enabled_tools) if enabled_tools is not None else None
        self.tool_llm_resolver = tool_llm_resolver
        self.context_budget = context_window_budget(context_window)
        self._interrupted = False
        self._running = False
        self.last_prompt_audit: dict[str, Any] = {}
        self.last_web_sources: list[WebSource] = []
        self._usage_summary: dict[str, Any] = {}
        self._tool_llm_routes: list[dict[str, Any]] = []
        self._auto_apply_file_changes = False
        self._seen_tool_call_signatures: set[str] = set()
        self._tool_state_revision = 0
        self._force_tool_finalize = False
        self._intervention: dict[str, Any] | None = None
        self._consecutive_discovery_batches = 0
        self._discovery_tools_paused = False
        self._patch_recovery_paths: dict[str, str] = {}
        self._applied_change_set_id: str | None = None
        self.last_choice_request: dict[str, Any] | None = None

    async def run(
        self,
        user_input: str,
        on_text_delta: TextDeltaCallback = None,
        history: list[dict[str, str]] | None = None,
        memory_summary: str | None = None,
        enabled_tools: list[str] | None = None,
        override_enabled_tools: bool = False,
        auto_apply_file_changes: bool = False,
        user_metadata: dict[str, Any] | None = None,
        max_iterations: int = MAX_AGENT_ITERATIONS,
        file_change_approval_timeout_seconds: float = FILE_CHANGE_APPROVAL_TIMEOUT_SECONDS,
    ) -> str:
        self._interrupted = False
        self._running = True
        self._auto_apply_file_changes = auto_apply_file_changes
        self._seen_tool_call_signatures = set()
        self._tool_state_revision = 0
        self._force_tool_finalize = False
        self._intervention = None
        self._consecutive_discovery_batches = 0
        self._discovery_tools_paused = False
        self._patch_recovery_paths = {}
        self._applied_change_set_id = None
        self.last_choice_request = None
        self.last_web_sources = []
        self._reset_usage_summary()
        file_change_approval_timeout_seconds = max(0.01, float(file_change_approval_timeout_seconds))
        self._usage_summary["file_change_approval_timeout_seconds"] = file_change_approval_timeout_seconds
        try:
            effective_tools = (
                set(enabled_tools)
                if override_enabled_tools and enabled_tools is not None
                else self.enabled_tools
            )
            if override_enabled_tools and enabled_tools is None:
                effective_tools = None
            effective_tools = self._normalize_enabled_tools(effective_tools)
            task_plan = build_task_plan()
            await self._push_task_list(task_plan, 0, "retrieving")
            await self._push_agent_status("正在检索项目上下文", "retrieving")
            raw_relevant_context = await self.vector_store.query(
                user_input,
                top_k=self.context_budget.vector_top_k * 2,
            )
            relevant_context = self._dedupe_relevant_context(
                raw_relevant_context,
                self.context_budget.vector_top_k,
            )
            await self._push_agent_status("正在梳理相关伏笔", "retrieving_foreshadows")
            foreshadow_context = await self._foreshadow_context(user_input)
            prompt_packs = await enabled_prompt_packs_for_project_stages(self.project, ["chat"])
            messages = self._build_initial_messages(
                user_input,
                relevant_context,
                foreshadow_context,
                history or [],
                memory_summary or "",
                prompt_packs,
                user_metadata or {},
            )
            self.last_prompt_audit = self._build_prompt_audit(
                user_input=user_input,
                relevant_context=relevant_context,
                foreshadow_context=foreshadow_context,
                history=history or [],
                memory_summary=memory_summary or "",
                prompt_packs=prompt_packs,
                effective_tools=effective_tools,
                override_enabled_tools=override_enabled_tools,
                raw_relevant_context_count=len(raw_relevant_context),
            )
            await self._push_agent_event(
                "prompt_audit",
                "提示词来源已记录",
                {"prompt_audit": self.last_prompt_audit},
            )
            await self._push_task_list(task_plan, min(1, len(task_plan) - 1), "thinking")
            context_status = (
                f"已注入 {len(relevant_context)} 条相关上下文（{self.context_budget.label}）"
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
            consecutive_no_progress_batches = 0
            safe_finalize_used = False
            max_iterations = max(1, int(max_iterations))
            while True:
                if self._interrupted:
                    return await self._finish_interrupted()
                if iterations >= max_iterations:
                    message = (
                        f"已达到本轮 Agent 最大迭代次数（{max_iterations}）。"
                        "为避免工具调用循环，已暂停继续执行。请根据当前结果继续给出下一步指令。"
                    )
                    self._set_termination_reason("iteration_limit")
                    await self._push_agent_event("agent_limit_reached", message, {"max_iterations": max_iterations})
                    await self._push_agent_status(message, "error", {"max_iterations": max_iterations})
                    raise AgentLoopError(message)
                iterations += 1

                await self._push_agent_status("正在请求模型", "thinking", {"iteration": iterations})
                await self._push_task_list(
                    task_plan,
                    min(1, len(task_plan) - 1),
                    "thinking",
                    {"iteration": iterations},
                )
                try:
                    request_phase = self._request_phase(messages)
                    if self._force_tool_finalize and request_phase == "tool_continue":
                        request_phase = "tool_finalize"
                        self._force_tool_finalize = False
                    budget_finalize = request_phase == "tool_continue" and iterations >= max_iterations
                    if budget_finalize:
                        request_phase = "tool_finalize"
                    request_tools = (
                        []
                        if request_phase == "tool_finalize"
                        else self._request_tool_schemas(effective_tools)
                    )
                    # 所有用户可见的 Agent 回复都保持流式：中转站可能需要较长时间
                    # 整理工具结果，非流式请求会让前端完全没有增量反馈，也会削弱
                    # 中断/空闲超时。内部短任务仍可在各自调用处使用非流式请求。
                    request_stream = True
                    if request_phase == "tool_continue":
                        await self._push_agent_status(
                            "正在根据工具结果继续推理",
                            "tool_continuing",
                            {"iteration": iterations, "tool_continue": True},
                        )
                    llm_messages = self._messages_for_request_phase(messages, request_phase)
                    try:
                        response = await self._chat_with_timeout(
                            ChatRequest(
                                messages=llm_messages,
                                tools=request_tools,
                                system=self.system_prompt,
                                stream=request_stream,
                                native_web_search=False,
                            ),
                            on_text_delta=guarded_text_delta,
                            phase=request_phase,
                            iteration=iterations,
                        )
                    except AgentLLMError as exc:
                        if (
                            request_phase != "tool_continue"
                            or safe_finalize_used
                            or iterations >= max_iterations
                            or not self._should_retry_safe_finalize(exc)
                        ):
                            raise
                        safe_finalize_used = True
                        iterations += 1
                        self._usage_summary["safe_finalize_attempts"] = 1
                        self.last_prompt_audit["usage"] = dict(self._usage_summary)
                        await self._push_agent_status(
                            "工具续轮失败，正在降级为安全收尾",
                            "finalizing",
                            {"iteration": iterations, "fallback": "safe_finalize", "error_category": exc.category},
                        )
                        request_phase = "tool_finalize"
                        request_tools = []
                        request_stream = True
                        llm_messages = self._messages_for_request_phase(messages, request_phase)
                        response = await self._chat_with_timeout(
                            ChatRequest(
                                messages=llm_messages,
                                tools=request_tools,
                                system=self.system_prompt,
                                stream=request_stream,
                                native_web_search=False,
                            ),
                            on_text_delta=guarded_text_delta,
                            phase=request_phase,
                            iteration=iterations,
                        )
                    self._record_model_request(llm_messages, response, len(response.tool_calls))
                except AgentInterrupted:
                    return await self._finish_interrupted()

                if self._interrupted:
                    return await self._finish_interrupted()

                if self._is_output_truncated(response):
                    self._set_termination_reason("output_truncated")
                    self._usage_summary["output_truncated"] = True
                    self.last_prompt_audit["usage"] = dict(self._usage_summary)
                    if response.tool_calls:
                        raise AgentLLMError(
                            "模型的工具调用达到输出上限，参数可能不完整，因此未执行该工具。"
                            "请缩小任务范围或提高当前 LLM 预设的最大输出 Token。"
                            "如果正在写长章节，请改用 chapter_draft 分块追加后再提交。",
                            "output_truncated",
                        )
                    await self._push_agent_event(
                        "output_truncated",
                        "回复未完整生成",
                        {"stop_reason": response.stop_reason},
                    )
                    await self._push_agent_status(
                        "回复未完整生成，可继续生成",
                        "output_truncated",
                        {"iteration": iterations, "stop_reason": response.stop_reason},
                    )
                    return f"{response.text.rstrip()}{OUTPUT_TRUNCATED_NOTICE}"

                if not response.tool_calls:
                    self._set_termination_reason("completed")
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

                tool_calls = self._coalesce_file_change_proposal_calls(response.tool_calls)
                blocked_mutating_call_ids = self._blocked_multi_mutation_call_ids(tool_calls)
                multi_mutation_conflict_reported = False
                tool_names = {
                    name
                    for call in tool_calls
                    if (name := self._tool_call_value(call, "name"))
                }
                refined_task_plan = build_task_plan(tool_names)
                if refined_task_plan != task_plan:
                    task_plan = refined_task_plan
                await self._push_agent_status(
                    f"模型请求调用 {len(tool_calls)} 个工具",
                    "tool_calling",
                    {"iteration": iterations, "tool_calls": len(tool_calls)},
                )
                await self._push_task_list(
                    task_plan,
                    min(2, len(task_plan) - 1),
                    "tool_calling",
                    {"iteration": iterations, "tool_calls": len(tool_calls)},
                )
                assistant_blocks: list[dict[str, Any]] = []
                if response.reasoning_content:
                    assistant_blocks.append({"type": "reasoning", "reasoning_content": response.reasoning_content})
                if response.text:
                    assistant_blocks.append({"type": "text", "text": response.text})
                for call in tool_calls:
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
                tool_batch: list[dict[str, Any]] = []
                discovery_calls_in_batch = 0
                for call in tool_calls:
                    if self._interrupted:
                        return await self._finish_interrupted()
                    call_id = str(self._tool_call_value(call, "id") or "")
                    tool_name = str(self._tool_call_value(call, "name") or "")
                    skip_reason = None
                    if self._is_discovery_tool(tool_name):
                        discovery_calls_in_batch += 1
                        if discovery_calls_in_batch > MAX_DISCOVERY_TOOL_CALLS_PER_BATCH:
                            skip_reason = (
                                f"同一批最多执行 {MAX_DISCOVERY_TOOL_CALLS_PER_BATCH} 个模糊检索工具，"
                                "本调用已跳过。请先根据已有结果精确读取目标文件，再继续修改或回答。"
                            )
                    blocked_reason = (
                        "同一轮包含多个写入工具，已阻止本批次写入以避免部分成功。"
                        "请先精确读取目标文件，再使用一次 file_change_proposal 汇总全部改动。"
                        if call_id in blocked_mutating_call_ids
                        else None
                    )
                    result = await self._execute_tool_call(
                        call,
                        effective_tools,
                        iteration=iterations,
                        blocked_reason=blocked_reason,
                        blocked_batch_duplicate=bool(blocked_reason and multi_mutation_conflict_reported),
                        skip_reason=skip_reason,
                    )
                    if blocked_reason:
                        multi_mutation_conflict_reported = True
                    approval_waiter = self._register_file_change_approval(call, result)
                    draft_action = str(result.metadata.get("draft_action") or "")
                    if tool_name == CHAPTER_DRAFT_TOOL and draft_action in {"begin", "append", "discard"}:
                        draft_chars = int(result.metadata.get("draft_characters") or 0)
                        status_text = {
                            "begin": "长章节草稿缓冲已建立",
                            "append": f"长章节草稿已累计 {draft_chars} 字符",
                            "discard": "长章节草稿已丢弃",
                        }[draft_action]
                        await self._push_agent_status(
                            status_text,
                            "chapter_drafting",
                            {
                                "iteration": iterations,
                                "draft_action": draft_action,
                                "draft_id": result.metadata.get("draft_id"),
                                "draft_characters": draft_chars,
                                "next_sequence": result.metadata.get("next_sequence"),
                            },
                        )
                    elif tool_name != PRESENT_CHOICES_TOOL and not result.metadata.get("suppress_frontend"):
                        await self._push_to_frontend(result)
                    result = await self._wait_for_file_change_decision(
                        call,
                        result,
                        approval_waiter,
                        iteration=iterations,
                        timeout_seconds=file_change_approval_timeout_seconds,
                    )
                    tool_batch.append(self._tool_batch_item(call, result))
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": self._tool_call_value(call, "id"),
                            "content": self._tool_result_content_for_llm(
                                str(self._tool_call_value(call, "name") or ""),
                                result.content,
                            ),
                        }
                    )
                    if (
                        str(self._tool_call_value(call, "name") or "") == PRESENT_CHOICES_TOOL
                        and result.status == "ok"
                        and isinstance(result.metadata.get("choice_groups"), list)
                        and result.metadata.get("choice_groups")
                    ):
                        self.last_choice_request = {
                            "request_id": str(result.metadata.get("choice_request_id") or ""),
                            "groups": result.metadata["choice_groups"],
                        }
                discovery_paused_now = self._update_discovery_state(tool_batch)
                if discovery_paused_now:
                    await self._push_agent_status(
                        "连续检索未进入精读，下一轮暂停模糊搜索；精确文件读取仍可用",
                        "tool_budget",
                        {
                            "consecutive_discovery_batches": self._consecutive_discovery_batches,
                            "max_consecutive_discovery_batches": MAX_CONSECUTIVE_DISCOVERY_BATCHES,
                            "exact_read_available": self.tools.has_tool(READ_PROJECT_FILES_TOOL),
                        },
                    )
                self._record_tool_batch(iterations, tool_batch)
                messages.append({"role": "user", "content": tool_results})
                if self.last_choice_request:
                    self._usage_summary["choice_group_count"] = len(self.last_choice_request["groups"])
                    self._set_termination_reason("awaiting_choice")
                    await self._push_agent_status("等待你提交选择", "waiting_user", {"iteration": iterations})
                    await self._push_task_list(
                        task_plan,
                        len(task_plan) - 1,
                        "waiting_user",
                        {"choice_request_id": self.last_choice_request["request_id"]},
                    )
                    return response.text.strip() or "请完成下面的选择后继续。"
                if tool_batch and all(item.get("status") in {"error", "duplicate", "blocked"} for item in tool_batch):
                    consecutive_no_progress_batches += 1
                else:
                    consecutive_no_progress_batches = 0
                self._usage_summary["consecutive_no_progress_batches"] = consecutive_no_progress_batches
                self.last_prompt_audit["usage"] = dict(self._usage_summary)
                if consecutive_no_progress_batches >= MAX_NO_PROGRESS_TOOL_BATCHES:
                    message = (
                        "连续两轮工具调用均失败或重复，Agent 已停止继续调用，"
                        "以避免无效循环和额外 token 消耗。"
                    )
                    intervention = {
                        "kind": "tool_stalled",
                        "title": "工具执行需要你的选择",
                        "message": message,
                        "options": [
                            {"id": "retry", "label": "重试本轮"},
                            {"id": "finalize", "label": "跳过工具并总结"},
                            {"id": "clarify", "label": "补充说明"},
                        ],
                    }
                    self._intervention = intervention
                    self._usage_summary["intervention"] = intervention
                    self._set_termination_reason("human_intervention")
                    await self._push_agent_event(
                        "agent_intervention_required",
                        message,
                        {
                            "reason": "tool_stalled",
                            "no_progress_batches": consecutive_no_progress_batches,
                            "intervention": intervention,
                        },
                    )
                    await self._push_agent_status(
                        "工具执行没有进展，等待你选择下一步",
                        "waiting_user",
                        {"reason": "tool_stalled", "intervention": intervention},
                    )
                    await self._push_task_list(
                        task_plan,
                        len(task_plan) - 1,
                        "waiting_user",
                        {"intervention": intervention},
                    )
                    return f"{message}\n\n请从下方选择下一步。"
                await self._push_task_list(
                    task_plan,
                    len(task_plan) - 1,
                    "finalizing",
                    {"iteration": iterations},
                )
        finally:
            self._running = False
            self._auto_apply_file_changes = False
            self._seen_tool_call_signatures = set()
            self._tool_state_revision = 0
            self._force_tool_finalize = False
            self._intervention = None
            self._consecutive_discovery_batches = 0
            self._discovery_tools_paused = False
            self._patch_recovery_paths = {}
            self._applied_change_set_id = None

    def interrupt(self) -> bool:
        if not self._running:
            return False
        self._interrupted = True
        return True

    def _normalize_enabled_tools(self, enabled_tools: set[str] | None) -> set[str] | None:
        if enabled_tools is None:
            return enabled_tools
        if FILE_CHANGE_PROPOSAL_TOOL in enabled_tools:
            return enabled_tools
        all_tool_names = {schema.get("name") for schema in self.tools.get_all_schemas() if schema.get("name")}
        if FILE_CHANGE_PROPOSAL_TOOL not in all_tool_names:
            return enabled_tools
        if enabled_tools & EDITING_TOOLS:
            return {*enabled_tools, FILE_CHANGE_PROPOSAL_TOOL}
        missing = all_tool_names - enabled_tools
        if missing <= {FILE_CHANGE_PROPOSAL_TOOL, CONSISTENCY_TOOL}:
            return {*enabled_tools, FILE_CHANGE_PROPOSAL_TOOL}
        return enabled_tools

    def _reset_usage_summary(self) -> None:
        self._usage_summary = {
            "model_request_attempts": 0,
            "model_requests": 0,
            "tool_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "estimated_total_tokens": 0,
            "search_credits": 0,
            "search_calls": [],
            "llm_calls": [],
            "tool_batches": [],
            "duplicate_tool_calls": 0,
            "failed_tool_calls": 0,
            "safe_finalize_attempts": 0,
            "consecutive_no_progress_batches": 0,
            "read_only_tool_calls": 0,
            "read_only_budget_exhausted": False,
            "discovery_tool_calls": 0,
            "exact_read_tool_calls": 0,
            "discovery_batches": 0,
            "consecutive_discovery_batches": 0,
            "discovery_tools_paused": False,
            "budget_blocked_tool_calls": 0,
            "patch_recovery_attempts": 0,
            "patch_recovery_reads": 0,
            "patch_recovery_paths": [],
            "termination_reason": "running",
            "change_approvals": [],
            "coalesced_change_proposals": 0,
            "applied_change_sets": [],
        }
        self._tool_llm_routes = []

    def _native_web_search_enabled(self) -> bool:
        return bool(getattr(getattr(self.llm, "settings", None), "llm_native_web_search", False))

    def _is_output_truncated(self, response: ChatResponse) -> bool:
        return str(response.stop_reason or "").strip().lower() in OUTPUT_TRUNCATED_STOP_REASONS

    def _request_tool_schemas(self, enabled_tools: set[str] | None) -> list[dict[str, Any]]:
        schemas = self.tools.get_schemas(enabled_tools)
        if self.tools.has_tool(FILE_CHANGE_PROPOSAL_TOOL):
            schemas = [
                schema
                for schema in schemas
                if schema.get("name") not in LEGACY_FILE_MUTATION_TOOLS
            ]
        if (
            enabled_tools is not None
            and PRESENT_CHOICES_TOOL not in enabled_tools
            and self.tools.has_tool(PRESENT_CHOICES_TOOL)
        ):
            schemas.append(self.tools.get_tool(PRESENT_CHOICES_TOOL).claude_schema())
            schemas.sort(key=lambda schema: str(schema.get("name") or ""))
        if (
            enabled_tools is not None
            and "write_chapter" in enabled_tools
            and CHAPTER_DRAFT_TOOL not in enabled_tools
            and self.tools.has_tool(CHAPTER_DRAFT_TOOL)
        ):
            schemas.append(self.tools.get_tool(CHAPTER_DRAFT_TOOL).claude_schema())
            schemas.sort(key=lambda schema: str(schema.get("name") or ""))
        if not self._native_web_search_enabled():
            schemas = [schema for schema in schemas if schema.get("name") != WEB_SEARCH_TOOL]
        if self._patch_recovery_paths and self.tools.has_tool(READ_PROJECT_FILES_TOOL):
            self._usage_summary["patch_recovery_paths"] = sorted(self._patch_recovery_paths)
            self.last_prompt_audit["usage"] = dict(self._usage_summary)
            return [self.tools.get_tool(READ_PROJECT_FILES_TOOL).claude_schema()]
        if self._applied_change_set_id:
            return [schema for schema in schemas if self._is_read_only_tool(str(schema.get("name") or ""))]
        if not self._discovery_tools_paused:
            return schemas
        self._usage_summary["read_only_budget_exhausted"] = True
        self._usage_summary["discovery_tools_paused"] = True
        self.last_prompt_audit["usage"] = dict(self._usage_summary)
        return [
            schema
            for schema in schemas
            if not self._is_discovery_tool(str(schema.get("name") or ""))
        ]

    def _is_read_only_tool(self, name: str) -> bool:
        if not name:
            return False
        try:
            governance = self.tools.get_tool(name).governance()
        except KeyError:
            return False
        return governance.category in {"search", "review"} and governance.write_policy == "none"

    def _is_exact_read_tool(self, name: str) -> bool:
        return name == READ_PROJECT_FILES_TOOL

    def _is_discovery_tool(self, name: str) -> bool:
        return self._is_read_only_tool(name) and not self._is_exact_read_tool(name)

    def _update_discovery_state(self, items: list[dict[str, Any]]) -> bool:
        was_paused = self._discovery_tools_paused
        active = [item for item in items if item.get("status") not in {"duplicate", "blocked"}]
        successful = [item for item in active if item.get("status") == "ok"]
        exact_read_succeeded = any(item.get("kind") == "exact_read" for item in successful)
        state_change_succeeded = any(item.get("changes_state") for item in successful)
        discovery_only = bool(successful) and all(item.get("kind") == "discovery" for item in active)

        if exact_read_succeeded or state_change_succeeded:
            self._consecutive_discovery_batches = 0
            self._discovery_tools_paused = False
        elif discovery_only:
            self._consecutive_discovery_batches += 1
            self._usage_summary["discovery_batches"] = int(
                self._usage_summary.get("discovery_batches", 0)
            ) + 1
            if self._consecutive_discovery_batches >= MAX_CONSECUTIVE_DISCOVERY_BATCHES:
                self._discovery_tools_paused = True
        elif active:
            self._consecutive_discovery_batches = 0

        self._usage_summary["consecutive_discovery_batches"] = self._consecutive_discovery_batches
        self._usage_summary["discovery_tools_paused"] = self._discovery_tools_paused
        self.last_prompt_audit["usage"] = dict(self._usage_summary)
        return not was_paused and self._discovery_tools_paused

    def _record_model_request(
        self,
        messages: list[dict[str, Any]],
        response: ChatResponse,
        tool_count: int = 0,
    ) -> None:
        self._usage_summary["model_requests"] = int(self._usage_summary.get("model_requests", 0)) + 1
        self._usage_summary["tool_calls"] = int(self._usage_summary.get("tool_calls", 0)) + tool_count
        usage = response.usage or {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                self._usage_summary[key] = int(self._usage_summary.get(key, 0)) + value
        estimated_input = self._estimate_messages_tokens(messages)
        estimated_output = self._estimate_text_tokens(response.text) + self._estimate_text_tokens(response.reasoning_content)
        self._usage_summary["estimated_input_tokens"] = int(self._usage_summary.get("estimated_input_tokens", 0)) + estimated_input
        self._usage_summary["estimated_output_tokens"] = int(self._usage_summary.get("estimated_output_tokens", 0)) + estimated_output
        self._usage_summary["estimated_total_tokens"] = (
            int(self._usage_summary.get("estimated_input_tokens", 0))
            + int(self._usage_summary.get("estimated_output_tokens", 0))
        )
        if not self._usage_summary.get("total_tokens"):
            self._usage_summary["total_tokens"] = 0
        self.last_web_sources = merge_web_sources(self.last_web_sources, response.web_sources)
        self.last_prompt_audit["web_search"] = {
            "enabled": self._native_web_search_enabled(),
            "source_count": len(self.last_web_sources),
        }
        self.last_prompt_audit["usage"] = dict(self._usage_summary)
        if self._tool_llm_routes:
            self.last_prompt_audit["tool_llm_routes"] = list(self._tool_llm_routes)

    def web_source_metadata(self) -> list[dict[str, str]]:
        return [source.model_dump() for source in self.last_web_sources]

    def _record_tool_web_sources(self, result: ToolResult) -> None:
        raw_sources = result.metadata.get("web_sources")
        if not isinstance(raw_sources, list):
            return
        sources: list[WebSource] = []
        for item in raw_sources:
            try:
                sources.append(WebSource.model_validate(item))
            except Exception:
                continue
        if not sources:
            return
        self.last_web_sources = merge_web_sources(self.last_web_sources, sources)
        self.last_prompt_audit["web_search"] = {
            "enabled": self._native_web_search_enabled(),
            "source_count": len(self.last_web_sources),
        }

    def _record_tool_llm_usage(self, tool_name: str, result: ToolResult) -> None:
        raw_usage = result.metadata.get("llm_usage")
        if not isinstance(raw_usage, dict):
            return
        usage = {
            key: value
            for key in ("input_tokens", "output_tokens", "total_tokens")
            if isinstance((value := raw_usage.get(key)), int)
        }
        if not usage:
            return
        for key, value in usage.items():
            self._usage_summary[key] = int(self._usage_summary.get(key, 0)) + value
        calls = list(self._usage_summary.get("tool_llm_calls") or [])
        calls.append({"tool": tool_name, "usage": usage})
        self._usage_summary["tool_llm_calls"] = calls
        self.last_prompt_audit["usage"] = dict(self._usage_summary)

    def _record_tool_search_usage(self, tool_name: str, result: ToolResult) -> None:
        raw_usage = result.metadata.get("search_usage")
        if not isinstance(raw_usage, dict):
            return
        call = {
            key: value
            for key in ("provider", "credits", "request_id", "response_time", "search_depth")
            if (value := raw_usage.get(key)) not in {None, ""}
        }
        if not call:
            return
        call["tool"] = tool_name
        calls = list(self._usage_summary.get("search_calls") or [])
        calls.append(call)
        self._usage_summary["search_calls"] = calls
        credits = raw_usage.get("credits")
        if isinstance(credits, (int, float)):
            self._usage_summary["search_credits"] = float(self._usage_summary.get("search_credits", 0)) + float(credits)
        self.last_prompt_audit["usage"] = dict(self._usage_summary)

    async def _chat_with_timeout(
        self,
        request: ChatRequest,
        on_text_delta: TextDeltaCallback = None,
        phase: str = "model",
        iteration: int | None = None,
    ) -> ChatResponse:
        timeout_seconds = self._llm_request_timeout_seconds()
        self.last_prompt_audit.setdefault("usage", dict(self._usage_summary))
        call_index = self._record_request_start(request, on_text_delta, timeout_seconds, phase, iteration)
        try:
            if request.stream and on_text_delta:
                response = await self._chat_with_idle_timeout(request, on_text_delta, timeout_seconds)
                self._record_request_finish(call_index, "completed", response=response)
                return response
            response = await asyncio.wait_for(
                self.llm.chat(request, on_text_delta=on_text_delta),
                timeout=timeout_seconds,
            )
            self._record_request_finish(call_index, "completed", response=response)
            return response
        except AgentInterrupted:
            self._record_request_finish(call_index, "interrupted")
            raise
        except asyncio.TimeoutError as exc:
            timeout_mode = self._usage_summary.get("request_timeout_mode")
            if timeout_mode == "idle":
                message = f"模型请求超过 {timeout_seconds} 秒没有新内容返回。"
            else:
                message = f"模型请求超过 {timeout_seconds} 秒未返回。"
            self._record_llm_error("timeout", message)
            self._record_request_finish(call_index, "failed", error_category="timeout", error_message=message)
            raise AgentLLMError(f"模型请求超时：{message}", "timeout") from exc
        except asyncio.CancelledError:
            self._record_request_finish(call_index, "cancelled")
            raise
        except Exception as exc:
            category = self._classify_llm_exception(exc)
            message = str(exc).strip() or exc.__class__.__name__
            self._record_llm_error(category, message)
            self._record_request_finish(call_index, "failed", error_category=category, error_message=message)
            raise AgentLLMError(self._friendly_llm_error(category, message), category) from exc

    async def _chat_with_idle_timeout(
        self,
        request: ChatRequest,
        on_text_delta: TextDeltaCallback,
        timeout_seconds: int,
    ) -> ChatResponse:
        last_progress = time.monotonic()

        async def track_progress(delta: str) -> None:
            nonlocal last_progress
            last_progress = time.monotonic()
            if delta and on_text_delta:
                await on_text_delta(delta)

        task = asyncio.create_task(self.llm.chat(request, on_text_delta=track_progress))
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=min(1, timeout_seconds))
                if done:
                    return task.result()
                if self._interrupted:
                    task.cancel()
                    raise AgentInterrupted()
                if time.monotonic() - last_progress >= timeout_seconds:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    raise asyncio.TimeoutError()
        except asyncio.CancelledError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise
        except Exception:
            if not task.done():
                task.cancel()
            raise

    def _record_request_start(
        self,
        request: ChatRequest,
        on_text_delta: TextDeltaCallback,
        timeout_seconds: int,
        phase: str,
        iteration: int | None,
    ) -> int:
        usage = dict(self._usage_summary)
        calls = list(usage.get("llm_calls") or [])
        call_index = len(calls) + 1
        estimated_input_tokens = self._estimate_request_input_tokens(request)
        usage["request_timeout_seconds"] = timeout_seconds
        usage["request_timeout_mode"] = "idle" if request.stream and on_text_delta else "total"
        usage["request_stream_requested"] = bool(request.stream)
        usage["request_stream_callback"] = bool(on_text_delta)
        usage["last_request_message_count"] = len(request.messages)
        usage["last_request_tool_count"] = len(request.tools)
        usage["last_request_estimated_input_tokens"] = estimated_input_tokens
        usage["last_request_phase"] = phase
        usage["model_request_attempts"] = int(usage.get("model_request_attempts", 0)) + 1
        calls.append(
            {
                "index": call_index,
                "phase": phase,
                "iteration": iteration,
                "provider": self._llm_provider_label(),
                "model": self._llm_model_label(),
                "stream_requested": bool(request.stream),
                "stream_callback": bool(on_text_delta),
                "timeout_seconds": timeout_seconds,
                "message_count": len(request.messages),
                "tool_count": len(request.tools),
                "has_tool_result": self._messages_end_with_tool_result(request.messages),
                "estimated_input_tokens": estimated_input_tokens,
                "status": "running",
                "started_at": self._utc_now(),
            }
        )
        usage["llm_calls"] = calls
        self._usage_summary.update(usage)
        self.last_prompt_audit["usage"] = usage
        return call_index

    def _record_request_finish(
        self,
        call_index: int,
        status: str,
        response: ChatResponse | None = None,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None:
        usage = dict(self._usage_summary)
        calls = list(usage.get("llm_calls") or [])
        for call in reversed(calls):
            if call.get("index") != call_index:
                continue
            call["status"] = status
            call["finished_at"] = self._utc_now()
            if response is not None:
                call["tool_calls_returned"] = len(response.tool_calls)
                call["output_chars"] = len(response.text or "") + len(response.reasoning_content or "")
                call["stop_reason"] = response.stop_reason
                if response.usage:
                    call["usage"] = response.usage
            if error_category:
                call["error_category"] = error_category
            if error_message:
                call["error_message"] = error_message[:500]
            break
        usage["llm_calls"] = calls
        self._usage_summary.update(usage)
        self.last_prompt_audit["usage"] = usage

    def _record_tool_batch(self, iteration: int, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        usage = dict(self._usage_summary)
        batches = list(usage.get("tool_batches") or [])
        duplicate_count = sum(1 for item in items if item.get("status") == "duplicate")
        failed_count = sum(1 for item in items if item.get("status") == "error")
        blocked_count = sum(1 for item in items if item.get("status") == "blocked")
        batches.append(
            {
                "iteration": iteration,
                "count": len(items),
                "duplicates": duplicate_count,
                "failed": failed_count,
                "blocked": blocked_count,
                "tools": items,
            }
        )
        usage["tool_batches"] = batches
        usage["duplicate_tool_calls"] = int(usage.get("duplicate_tool_calls", 0)) + duplicate_count
        usage["failed_tool_calls"] = int(usage.get("failed_tool_calls", 0)) + failed_count
        usage["budget_blocked_tool_calls"] = int(usage.get("budget_blocked_tool_calls", 0)) + blocked_count
        self._usage_summary.update(usage)
        self.last_prompt_audit["usage"] = usage

    def _tool_batch_item(self, call: Any, result: ToolResult) -> dict[str, Any]:
        name = str(self._tool_call_value(call, "name") or "unknown")
        status = "blocked" if result.metadata.get("tool_budget_blocked") else result.status
        ui_type = result.ui_hint.get("type") if isinstance(result.ui_hint, dict) else None
        item: dict[str, Any] = {
            "name": name,
            "status": status,
            "content_chars": len(result.content or ""),
            "kind": (
                "exact_read"
                if self._is_exact_read_tool(name)
                else "discovery"
                if self._is_discovery_tool(name)
                else "other"
            ),
            "changes_state": bool(
                result.metadata.get("agent_state_changed")
                or result.metadata.get("approval_decision") == "applied"
            ),
        }
        if ui_type:
            item["ui_type"] = ui_type
        if result.metadata.get("llm_preset_id"):
            item["preset_id"] = result.metadata["llm_preset_id"]
        if result.metadata.get("tool_execution_mode"):
            item["mode"] = result.metadata["tool_execution_mode"]
        return item

    def _request_phase(self, messages: list[dict[str, Any]]) -> str:
        return "tool_continue" if self._messages_end_with_tool_result(messages) else "initial"

    def _messages_for_request_phase(self, messages: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
        compacted = self._compact_messages_for_llm(messages)
        if phase in {"tool_continue", "tool_finalize"}:
            compacted = self._compact_messages_for_tool_continuation(compacted)
        return self._strip_internal_message_fields(compacted)

    def _should_retry_safe_finalize(self, error: AgentLLMError) -> bool:
        return error.category == "bad_request"

    def _set_termination_reason(self, reason: str) -> None:
        self._usage_summary["termination_reason"] = reason
        self.last_prompt_audit["usage"] = dict(self._usage_summary)

    def _messages_end_with_tool_result(self, messages: list[dict[str, Any]]) -> bool:
        if not messages:
            return False
        content = messages[-1].get("content")
        return bool(
            isinstance(content, list)
            and content
            and all(isinstance(block, dict) and block.get("type") == "tool_result" for block in content)
        )

    def _compact_messages_for_tool_continuation(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        first_tool_index = self._first_tool_assistant_index(messages)
        if first_tool_index <= 0:
            return messages

        pre_tool = messages[:first_tool_index]
        tool_chain = messages[first_tool_index:]
        stable_prefix: list[dict[str, Any]] = []
        history_like: list[dict[str, Any]] = []

        for message in pre_tool:
            role = message.get("role")
            content = message.get("content")
            if role == "user" and isinstance(content, str):
                if self._is_stable_prompt_message(message) or self._is_memory_summary_message(message):
                    stable_prefix.append(message)
                else:
                    history_like.append(message)
                continue
            stable_prefix.append(message)

        if not history_like:
            return [*stable_prefix, *tool_chain]

        current_request = history_like[-1]
        recent_history = history_like[:-1][-TOOL_CONTINUATION_RECENT_MESSAGES:]
        return [
            *stable_prefix,
            *recent_history,
            self._slim_current_request_message(current_request),
            *tool_chain,
        ]

    def _first_tool_assistant_index(self, messages: list[dict[str, Any]]) -> int:
        for index, message in enumerate(messages):
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            if any(isinstance(block, dict) and block.get("type") == "tool_use" for block in content):
                return index
        return -1

    def _is_stable_prompt_message(self, message: dict[str, Any]) -> bool:
        return message.get(INTERNAL_MESSAGE_KIND) == "prompt_pack"

    def _is_memory_summary_message(self, message: dict[str, Any]) -> bool:
        return message.get(INTERNAL_MESSAGE_KIND) == "memory_summary"

    def _slim_current_request_message(self, message: dict[str, Any]) -> dict[str, Any]:
        content = message.get("content")
        if not isinstance(content, str):
            return message
        if message.get(INTERNAL_MESSAGE_KIND) != "current_request":
            return message
        user_request = str(message.get(INTERNAL_USER_REQUEST) or "").strip()
        if not user_request:
            return message
        return {
            **message,
            "content": (
                "原始用户请求：\n"
                f"{user_request}\n\n"
                "说明：上一轮检索到的项目上下文已在工具结果中摘要呈现；如仍需更多细节，请继续调用检索类工具。"
            ),
        }

    def _strip_internal_message_fields(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                key: value
                for key, value in message.items()
                if key not in {INTERNAL_MESSAGE_KIND, INTERNAL_USER_REQUEST}
            }
            for message in messages
        ]

    def _llm_provider_label(self) -> str:
        settings = getattr(self.llm, "settings", None)
        base = str(getattr(settings, "llm_api_base", "") or "").lower()
        if "deepseek" in base:
            return "deepseek"
        if "openai" in base:
            return "openai"
        if base:
            return "openai_compatible"
        return self.llm.__class__.__name__

    def _llm_model_label(self) -> str:
        settings = getattr(self.llm, "settings", None)
        return str(getattr(settings, "llm_model_name", "") or self.llm.__class__.__name__)

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _llm_request_timeout_seconds(self) -> int:
        value = getattr(getattr(self.llm, "settings", None), "llm_request_timeout", 120)
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            seconds = 120
        return max(1, seconds)

    def _record_llm_error(self, category: str, message: str) -> None:
        usage = dict(self._usage_summary)
        usage["last_error_category"] = category
        usage["last_error_message"] = message[:500]
        usage["request_timeout_seconds"] = self._llm_request_timeout_seconds()
        self._usage_summary.update(usage)
        self.last_prompt_audit["usage"] = usage

    def _classify_llm_exception(self, exc: Exception) -> str:
        name = exc.__class__.__name__.lower()
        text = str(exc).lower()
        if "timeout" in name or "timeout" in text or "timed out" in text:
            return "timeout"
        if any(marker in name for marker in ("rate", "quota")) or "rate limit" in text or "quota" in text:
            return "rate_limit"
        if any(marker in name for marker in ("authentication", "permission", "unauthorized")) or "api key" in text:
            return "auth"
        if any(marker in name for marker in ("badrequest", "invalidrequest")) or "400" in text or "invalid_request" in text:
            return "bad_request"
        if "connection" in name or "network" in name or "connect" in text or "dns" in text:
            return "network"
        return "llm_error"

    def _friendly_llm_error(self, category: str, message: str) -> str:
        labels = {
            "timeout": "模型请求超时",
            "rate_limit": "模型限流或额度不足",
            "auth": "模型鉴权失败",
            "bad_request": "模型请求参数错误",
            "network": "模型网络连接失败",
            "llm_error": "模型请求失败",
        }
        return f"{labels.get(category, '模型请求失败')}：{message}"

    def _estimate_messages_tokens(self, messages: list[dict[str, Any]]) -> int:
        return self._estimate_text_tokens(json.dumps(messages, ensure_ascii=False))

    def _estimate_request_input_tokens(self, request: ChatRequest) -> int:
        payload = {
            "system": request.system,
            "messages": request.messages,
            "tools": request.tools,
        }
        return self._estimate_text_tokens(json.dumps(payload, ensure_ascii=False))

    def _estimate_text_tokens(self, text: str) -> int:
        if not text:
            return 0
        chinese_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        other_chars = max(0, len(text) - chinese_chars)
        return max(1, chinese_chars + (other_chars + 3) // 4)

    async def _finish_interrupted(self) -> str:
        self._interrupted = False
        self._set_termination_reason("interrupted")
        message = "操作已中断，等待新指令。"
        await self._push_agent_status(message, "interrupted")
        return message

    def _build_initial_messages(
        self,
        user_input: str,
        relevant_context: list[dict],
        foreshadow_context: str,
        history: list[dict[str, str]],
        memory_summary: str,
        prompt_packs: list[PromptPack] | None = None,
        user_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        memory_messages = self._conversation_memory_messages(history, self.context_budget)
        summary_message = self._summary_memory_message(memory_summary)
        prompt_pack_messages = self._prompt_pack_messages(prompt_packs or [])
        context_blocks: list[str] = []
        if relevant_context:
            context_blocks.append(f"相关项目上下文：\n{self._compact_context(relevant_context, self.context_budget)}")
        if foreshadow_context:
            context_blocks.append(
                "相关伏笔上下文：\n"
                f"{foreshadow_context}\n\n"
                "写作时请根据伏笔状态决定：计划埋的伏笔可以铺垫；已埋下/推进中的伏笔可以推进；"
                "标记为本章回收的伏笔应优先考虑回收；废弃伏笔不要主动使用。"
            )
        joined_context = "\n\n".join(context_blocks)
        current_content = f"{joined_context}\n\n用户请求：\n{user_input}" if joined_context else user_input
        choice_response = (user_metadata or {}).get("choice_response")
        if isinstance(choice_response, dict):
            current_content += (
                "\n\n结构化选择结果（以此为准）：\n"
                + json.dumps(choice_response, ensure_ascii=False, separators=(",", ":"))
            )
        return [
            *prompt_pack_messages,
            *summary_message,
            *memory_messages,
            {
                "role": "user",
                "content": current_content,
                INTERNAL_MESSAGE_KIND: "current_request",
                INTERNAL_USER_REQUEST: user_input,
            },
        ]

    def _prompt_pack_messages(self, prompt_packs: list[PromptPack]) -> list[dict[str, Any]]:
        blocks = []
        for pack in prompt_packs:
            content = pack.content.strip()
            if not content:
                continue
            header = f"提示词包：{pack.name}"
            if pack.description.strip():
                header += f"（{pack.description.strip()}）"
            blocks.append(f"## {header}\n{content}")
        if not blocks:
            return []
        return [
            {
                "role": "user",
                "content": (
                    "以下是已启用且适用于当前对话阶段的长期提示词规则。"
                    "它们用于约束写作风格、输出格式和模型行为，不是项目事实设定：\n\n"
                    + "\n\n".join(blocks)
                ),
                INTERNAL_MESSAGE_KIND: "prompt_pack",
            }
        ]

    def _build_prompt_audit(
        self,
        user_input: str,
        relevant_context: list[dict],
        foreshadow_context: str,
        history: list[dict[str, str]],
        memory_summary: str,
        prompt_packs: list[PromptPack],
        effective_tools: set[str] | None,
        override_enabled_tools: bool,
        raw_relevant_context_count: int | None = None,
    ) -> dict[str, Any]:
        tool_schemas = self._request_tool_schemas(effective_tools)
        context_paths = []
        for item in relevant_context[:8]:
            path = item.get("path") if isinstance(item, dict) else None
            if path:
                context_paths.append(str(path))
        prompt_pack_message_count = len(self._prompt_pack_messages(prompt_packs))
        prompt_cache_enabled = bool(getattr(getattr(self.llm, "settings", None), "llm_prompt_cache", False))
        return {
            "system_prompt": self.system_prompt_audit or {
                "source": "preset" if self.system_prompt != SYSTEM_PROMPT else "default",
                "base_source": "preset" if self.system_prompt != SYSTEM_PROMPT else "default",
                "chars": len(self.system_prompt or ""),
                "project_rules": {
                    "mode": "default",
                    "included": False,
                    "chars": 0,
                    "updated_at": None,
                },
            },
            "user_input": {
                "chars": len(user_input),
            },
            "memory": {
                "summary": bool(memory_summary.strip()),
                "summary_chars": len(memory_summary.strip()),
                "recent_messages": len(history),
                "injected_recent_messages": len(self._conversation_memory_messages(history, self.context_budget)),
            },
            "context_window": {
                "mode": self.context_budget.mode,
                "label": self.context_budget.label,
                "recent_messages": self.context_budget.recent_messages,
                "memory_chars": self.context_budget.memory_chars,
                "single_message_chars": self.context_budget.single_message_chars,
                "vector_top_k": self.context_budget.vector_top_k,
                "vector_item_chars": self.context_budget.vector_item_chars,
            },
            "vector_context": {
                "count": len(relevant_context),
                "raw_count": (
                    len(relevant_context)
                    if raw_relevant_context_count is None
                    else raw_relevant_context_count
                ),
                "deduplicated": max(
                    0,
                    (len(relevant_context) if raw_relevant_context_count is None else raw_relevant_context_count)
                    - len(relevant_context),
                ),
                "paths": context_paths,
            },
            "foreshadow_context": {
                "included": bool(foreshadow_context.strip()),
                "chars": len(foreshadow_context.strip()),
            },
            "prompt_packs": {
                "stage": "chat",
                "count": len(prompt_packs),
                "names": [pack.name for pack in prompt_packs],
            },
            "tools": {
                "mode": "runtime_override" if override_enabled_tools else ("preset_limited" if self.enabled_tools is not None else "all"),
                "count": len(tool_schemas),
                "names": [str(schema.get("name")) for schema in tool_schemas if schema.get("name")],
            },
            "prompt_cache": {
                "enabled": prompt_cache_enabled,
                "layout": "system + prompt_packs + memory_summary + recent_history + dynamic_context",
                "stable_prefix_messages": prompt_pack_message_count,
                "dynamic_sections_after_prefix": [
                    "memory_summary",
                    "recent_history",
                    "vector_context",
                    "foreshadow_context",
                    "user_input",
                ],
            },
            "tool_continuation": {
                "strategy": "controlled_loop",
                "recent_history_messages": TOOL_CONTINUATION_RECENT_MESSAGES,
                "stream": False,
                "fallback": "bad_request_only_safe_finalize",
            },
        }

    async def _foreshadow_context(self, user_input: str) -> str:
        return await foreshadow_context_for_prompt(self.project, user_input)

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
                INTERNAL_MESSAGE_KIND: "memory_summary",
            }
        ]

    def _conversation_memory_messages(
        self,
        history: list[dict[str, str]],
        budget: ContextWindowBudget,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in history:
            role = item.get("role")
            if role not in {"user", "agent", "assistant"}:
                continue
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            if len(content) > budget.single_message_chars:
                content = f"{content[:budget.single_message_chars]}\n\n[以上历史消息已截断]"
            normalized.append(
                {
                    "role": "assistant" if role in {"agent", "assistant"} else "user",
                    "content": content,
                    INTERNAL_MESSAGE_KIND: "history",
                }
            )

        recent = normalized[-budget.recent_messages:]
        total = 0
        selected: list[dict[str, Any]] = []
        for item in reversed(recent):
            length = len(item["content"])
            if selected and total + length > budget.memory_chars:
                break
            total += length
            selected.append(item)
        return list(reversed(selected))

    def _compact_messages_for_llm(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compacted: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role not in {"user", "assistant"}:
                continue
            if isinstance(content, str):
                if content.strip():
                    compacted.append(
                        {
                            "role": role,
                            "content": content,
                            **{
                                key: message[key]
                                for key in (INTERNAL_MESSAGE_KIND, INTERNAL_USER_REQUEST)
                                if key in message
                            },
                        }
                    )
                continue
            if isinstance(content, list):
                filtered_blocks: list[dict[str, Any]] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")
                    if block_type == "text" and not str(block.get("text") or "").strip():
                        continue
                    if block_type == "reasoning" and not str(block.get("reasoning_content") or "").strip():
                        continue
                    if block_type in {"text", "reasoning", "tool_use", "tool_result"}:
                        filtered_blocks.append(block)
                if filtered_blocks:
                    compacted.append(
                        {
                            "role": role,
                            "content": filtered_blocks,
                            **{
                                key: message[key]
                                for key in (INTERNAL_MESSAGE_KIND, INTERNAL_USER_REQUEST)
                                if key in message
                            },
                        }
                    )
        return compacted

    def _compact_context(self, relevant_context: list[dict], budget: ContextWindowBudget) -> str:
        lines: list[str] = []
        for item in relevant_context[:budget.vector_top_k]:
            path = item.get("path") or item.get("file") or "unknown"
            content = item.get("content") or item.get("text")
            if content is None:
                content = json.dumps(item, ensure_ascii=False, indent=2)
            else:
                content = str(content)
            if len(content) > budget.vector_item_chars:
                content = f"{content[:budget.vector_item_chars]}\n[上下文片段已截断]"
            lines.append(f"- {path}:\n{content}")
        return "\n\n".join(lines)

    def _dedupe_relevant_context(self, items: list[dict], limit: int) -> list[dict]:
        if limit <= 0:
            return []
        selected: list[dict] = []
        seen_chunk_ids: set[str] = set()
        seen_content: set[tuple[str, str]] = set()
        path_counts: dict[str, int] = {}
        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            path = str(item.get("path") or item.get("file") or "unknown").replace("\\", "/")
            chunk_id = str(item.get("chunk_id") or "").strip()
            content = item.get("content") if item.get("content") is not None else item.get("text")
            normalized_content = " ".join(str(content or "").split()).casefold()
            content_key = (path, normalized_content)
            if chunk_id and chunk_id in seen_chunk_ids:
                continue
            if normalized_content and content_key in seen_content:
                continue
            if path_counts.get(path, 0) >= MAX_VECTOR_CHUNKS_PER_PATH:
                continue
            if chunk_id:
                seen_chunk_ids.add(chunk_id)
            if normalized_content:
                seen_content.add(content_key)
            path_counts[path] = path_counts.get(path, 0) + 1
            selected.append(item)
            if len(selected) >= max(0, int(limit)):
                break
        return selected

    def _tool_result_content_for_llm(self, tool_name: str, content: str) -> str:
        """Keep large, repeatable search output from inflating every tool continuation."""
        if tool_name not in COMPACTABLE_TOOL_RESULT_NAMES or len(content) <= MAX_COMPACTABLE_TOOL_RESULT_CHARS:
            return content
        head = MAX_COMPACTABLE_TOOL_RESULT_CHARS - 600
        return (
            f"{content[:head]}\n\n"
            "[该工具结果过长，已为后续推理压缩；如需原文请重新调用对应检索工具。]\n\n"
            f"{content[-500:]}"
        )

    def _coalesce_file_change_proposal_calls(self, calls: list[Any]) -> list[Any]:
        proposal_calls = [
            call
            for call in calls
            if self._tool_call_value(call, "name") == FILE_CHANGE_PROPOSAL_TOOL
        ]
        if len(proposal_calls) <= 1:
            return calls

        titles: list[str] = []
        summaries: list[str] = []
        changes: list[Any] = []
        for call in proposal_calls:
            params = self._tool_call_value(call, "input") or {}
            if isinstance(params, dict):
                title = str(params.get("title") or "").strip()
                summary = str(params.get("summary") or "").strip()
                raw_changes = params.get("changes")
                if title and title not in titles:
                    titles.append(title)
                if summary and summary not in summaries:
                    summaries.append(summary)
                if isinstance(raw_changes, list):
                    changes.extend(raw_changes)

        first = proposal_calls[0]
        merged_call = {
            "id": self._tool_call_value(first, "id"),
            "name": FILE_CHANGE_PROPOSAL_TOOL,
            "input": {
                "title": "；".join(titles[:3]) or "汇总多文件改动",
                "summary": "\n".join(summaries),
                "changes": changes,
            },
        }
        merged: list[Any] = []
        inserted = False
        for call in calls:
            if self._tool_call_value(call, "name") == FILE_CHANGE_PROPOSAL_TOOL:
                if not inserted:
                    merged.append(merged_call)
                    inserted = True
                continue
            merged.append(call)
        coalesced = len(proposal_calls) - 1
        self._usage_summary["coalesced_change_proposals"] = (
            int(self._usage_summary.get("coalesced_change_proposals", 0)) + coalesced
        )
        self.last_prompt_audit["usage"] = dict(self._usage_summary)
        return merged

    def _blocked_multi_mutation_call_ids(self, calls: list[Any]) -> set[str]:
        mutating: list[Any] = []
        for call in calls:
            name = str(self._tool_call_value(call, "name") or "")
            try:
                governance = self.tools.get_tool(name).governance()
            except KeyError:
                continue
            if governance.write_policy != "none":
                mutating.append(call)
        if len(mutating) <= 1:
            return set()
        return {str(self._tool_call_value(call, "id") or "") for call in mutating}

    async def _execute_tool_call(
        self,
        call: Any,
        enabled_tools: set[str] | None = None,
        iteration: int | None = None,
        blocked_reason: str | None = None,
        blocked_batch_duplicate: bool = False,
        skip_reason: str | None = None,
    ) -> ToolResult:
        name = self._tool_call_value(call, "name")
        params = self._tool_call_value(call, "input") or {}
        call_id = str(self._tool_call_value(call, "id") or "") or f"tool-{time.perf_counter_ns()}"
        started = time.perf_counter()
        await self._push_tool_event("tool_call_start", name, params, call_id=call_id)
        if skip_reason:
            result = ToolResult(
                content=skip_reason,
                metadata={
                    "tool_budget_blocked": True,
                    "suppress_frontend": True,
                },
                status="duplicate",
            )
            await self._push_tool_event("tool_call_end", name, params, started, call_id=call_id)
            return result
        if blocked_reason:
            if blocked_batch_duplicate:
                result = ToolResult(
                    content="同批次的写入冲突已由前一个工具结果说明，本调用未执行。",
                    metadata={
                        "is_error": True,
                        "multi_mutation_batch": True,
                        "suppress_frontend": True,
                    },
                    status="duplicate",
                    retryable=True,
                )
                await self._push_tool_event("tool_call_end", name, params, started, call_id=call_id)
                return result
            result = ToolResult(
                content=blocked_reason,
                metadata={"is_error": True, "multi_mutation_batch": True},
                status="error",
                retryable=True,
            )
            await self._push_tool_event(
                "tool_call_error",
                name,
                params,
                started,
                blocked_reason,
                call_id=call_id,
            )
            return result
        signature = self._tool_call_signature(str(name or "unknown"), params)
        if signature in self._seen_tool_call_signatures:
            result = ToolResult(
                content=DUPLICATE_TOOL_RESULT,
                metadata={"duplicate_tool_call": True},
                status="duplicate",
            )
            await self._push_agent_status(
                f"已跳过重复工具调用：{name}",
                "tool_duplicate",
                {"iteration": iteration, "tool": name},
            )
            await self._push_tool_event("tool_call_end", name, params, started, call_id=call_id)
            return result
        self._seen_tool_call_signatures.add(signature)
        internal_chapter_draft_allowed = (
            name == CHAPTER_DRAFT_TOOL
            and enabled_tools is not None
            and "write_chapter" in enabled_tools
        )
        internal_recovery_read_allowed = name == READ_PROJECT_FILES_TOOL and bool(self._patch_recovery_paths)
        if (
            enabled_tools is not None
            and name not in enabled_tools
            and name != PRESENT_CHOICES_TOOL
            and not internal_chapter_draft_allowed
            and not internal_recovery_read_allowed
        ):
            result = ToolResult(
                content=f"Tool {name} is disabled for this agent preset.",
                metadata={"is_error": True},
                status="error",
            )
            await self._push_tool_event(
                "tool_call_error",
                name,
                params,
                started,
                result.content,
                call_id=call_id,
            )
            return result
        try:
            tool = self.tools.get_tool(name)
            tool_llm, preset_id = await self._tool_llm_for(name)
            invoke_llm = tool_llm or (self.llm if tool.uses_agent_llm else None)
            result = await tool.invoke(params, self.project, invoke_llm) if invoke_llm is not None else None
            mode = "invoke" if result is not None else "execute"
            if result is None:
                result = await tool.execute(params, self.project)
            if name == FILE_CHANGE_PROPOSAL_TOOL:
                result = await self._maybe_auto_apply_file_change(result)
            result.metadata["tool_execution_mode"] = mode
            if preset_id:
                result.metadata["llm_preset_id"] = preset_id
            self._record_tool_web_sources(result)
            self._record_tool_llm_usage(str(name or "unknown"), result)
            self._record_tool_search_usage(str(name or "unknown"), result)
            changes_state = self._tool_result_changes_state(tool, result)
            result.metadata["agent_state_changed"] = changes_state
            if changes_state:
                self._tool_state_revision += 1
                self._consecutive_discovery_batches = 0
                self._discovery_tools_paused = False
                self._patch_recovery_paths = {}
            elif result.status == "ok" and self._is_exact_read_tool(str(name or "")):
                self._record_successful_read("exact_read")
                recovered = self._complete_patch_recovery_read(params)
                if recovered:
                    result.metadata["patch_recovery_read"] = recovered
                    result.content += (
                        "\n\n[补丁恢复读取完成] 已取得目标文件的精确内容和哈希。"
                        "普通文本请优先使用 source_hash + replace_lines 重新提交改动；"
                        "大纲请使用 inspect 返回的最新区块 ID。"
                    )
            elif result.status == "ok" and self._is_discovery_tool(str(name or "")):
                self._record_successful_read("discovery")
            await self._push_tool_event(
                "tool_call_end",
                name,
                params,
                started,
                preset_id=preset_id,
                mode=mode,
                call_id=call_id,
            )
            return result
        except Exception as exc:
            recovery = self._register_patch_recovery(params, str(exc)) if name == FILE_CHANGE_PROPOSAL_TOOL else {}
            recovery_note = ""
            if recovery:
                targets = "、".join(
                    f"{path}（{mode}）" for path, mode in sorted(recovery.items())
                )
                recovery_note = (
                    f"\n补丁未执行。下一轮请先用 read_project_files 定向读取：{targets}。"
                    "取得最新原文、行号和 SHA-256 后再重新提交，不要根据搜索摘要猜测 old_text。"
                )
            result = ToolResult(
                content=f"Tool {name} failed: {exc}{recovery_note}",
                metadata={
                    "is_error": True,
                    "patch_recovery_paths": sorted(recovery),
                },
                status="error",
                retryable=True,
            )
            await self._push_tool_event(
                "tool_call_error",
                name,
                params,
                started,
                str(exc),
                call_id=call_id,
            )
            return result

    def _record_successful_read(self, kind: str) -> None:
        usage_key = "exact_read_tool_calls" if kind == "exact_read" else "discovery_tool_calls"
        self._usage_summary[usage_key] = int(self._usage_summary.get(usage_key, 0)) + 1
        self._usage_summary["read_only_tool_calls"] = int(
            self._usage_summary.get("read_only_tool_calls", 0)
        ) + 1
        if kind == "exact_read":
            self._consecutive_discovery_batches = 0
            self._discovery_tools_paused = False
        self.last_prompt_audit["usage"] = dict(self._usage_summary)

    def _register_patch_recovery(self, params: dict[str, Any], error: str) -> dict[str, str]:
        markers = (
            "replace_text 必须唯一匹配",
            "文件内容已变化，请重新读取",
            "replace_lines 行号超出范围",
            "大纲区块不存在或已变化",
            "大纲区块行号已失效",
        )
        if not any(marker in error for marker in markers):
            return {}

        changes = params.get("changes")
        if not isinstance(changes, list):
            return {}
        candidates: list[tuple[str, str]] = []
        for item in changes:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip().replace("\\", "/")
            if not path:
                continue
            operation = str(item.get("operation") or "write")
            mode = "inspect" if "outline_node" in operation else "content"
            candidates.append((path, mode))
        matched = [(path, mode) for path, mode in candidates if path in error]
        if not matched and len(candidates) == 1:
            matched = candidates
        if not matched:
            return {}

        for path, mode in matched:
            self._patch_recovery_paths[path] = mode
        self._usage_summary["patch_recovery_attempts"] = int(
            self._usage_summary.get("patch_recovery_attempts", 0)
        ) + 1
        self._usage_summary["patch_recovery_paths"] = sorted(self._patch_recovery_paths)
        self.last_prompt_audit["usage"] = dict(self._usage_summary)
        return dict(matched)

    def _complete_patch_recovery_read(self, params: dict[str, Any]) -> list[str]:
        if not self._patch_recovery_paths:
            return []
        mode = str(params.get("mode") or "content").strip().lower()
        requested: set[str] = set()
        for path in params.get("paths") or []:
            if isinstance(path, str):
                requested.add(path.strip().replace("\\", "/"))
        for selection in params.get("selections") or []:
            if isinstance(selection, dict) and isinstance(selection.get("path"), str):
                requested.add(str(selection["path"]).strip().replace("\\", "/"))

        recovered = [
            path
            for path, required_mode in self._patch_recovery_paths.items()
            if path in requested and mode == required_mode
        ]
        for path in recovered:
            self._patch_recovery_paths.pop(path, None)
        if recovered:
            self._usage_summary["patch_recovery_reads"] = int(
                self._usage_summary.get("patch_recovery_reads", 0)
            ) + 1
            self._usage_summary["patch_recovery_paths"] = sorted(self._patch_recovery_paths)
            self.last_prompt_audit["usage"] = dict(self._usage_summary)
        return recovered

    def _tool_call_signature(self, name: str, params: Any) -> str:
        try:
            payload = json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            payload = repr(params)
        return f"{self._tool_state_revision}:{name}:{payload}"

    def _tool_result_changes_state(self, tool: Any, result: ToolResult) -> bool:
        if result.status != "ok":
            return False
        if result.metadata.get("changeset_id") and result.metadata.get("auto_apply_file_changes") != "applied":
            return result.metadata.get("approval_decision") == "applied"
        if result.metadata.get("auto_apply_file_changes") == "applied":
            return True
        return tool.governance().write_policy in {"direct", "workspace_only"}

    def _register_file_change_approval(
        self,
        call: Any,
        result: ToolResult,
    ) -> asyncio.Future | None:
        if self._auto_apply_file_changes or result.metadata.get("auto_apply_file_changes") == "applied":
            return None
        change_set_id = result.metadata.get("changeset_id")
        if not isinstance(change_set_id, str) or not change_set_id:
            return None

        waiter = register_change_set_waiter(self.project, change_set_id)
        result.metadata["approval_waiting"] = True
        data = result.ui_hint.get("data") if isinstance(result.ui_hint, dict) else None
        if isinstance(data, dict):
            data["agent_waiting"] = True
        return waiter

    async def _wait_for_file_change_decision(
        self,
        call: Any,
        result: ToolResult,
        waiter: asyncio.Future | None,
        iteration: int | None = None,
        timeout_seconds: float = FILE_CHANGE_APPROVAL_TIMEOUT_SECONDS,
    ) -> ToolResult:
        if waiter is None:
            return result
        change_set_id = str(result.metadata.get("changeset_id") or "")

        await self._push_agent_status(
            "文件改动已准备，等待你应用、丢弃或稍后处理",
            "waiting_approval",
            {
                "iteration": iteration,
                "changeset_id": change_set_id,
                "timeout_seconds": timeout_seconds,
            },
        )
        decision = await wait_for_registered_change_set_decision(
            self.project,
            change_set_id,
            waiter,
            timeout_seconds=timeout_seconds,
        )
        approvals = list(self._usage_summary.get("change_approvals") or [])
        approvals.append({"changeset_id": change_set_id, "decision": decision, "iteration": iteration})
        self._usage_summary["change_approvals"] = approvals
        self.last_prompt_audit["usage"] = dict(self._usage_summary)

        result.metadata["approval_decision"] = decision
        result.metadata["approval_waiting"] = False
        data = result.ui_hint.get("data") if isinstance(result.ui_hint, dict) else None
        if isinstance(data, dict):
            data["agent_waiting"] = False
            if decision in {"applied", "discarded"}:
                data["status"] = decision
        if decision == "applied":
            self._applied_change_set_id = change_set_id
            await self._verify_applied_file_changes(result)
            await self._verify_applied_foreshadows(result)
            self._tool_state_revision += 1
            self._consecutive_discovery_batches = 0
            self._discovery_tools_paused = False
            self._patch_recovery_paths = {}
            verification = result.metadata.get("file_verification")
            verification_note = ""
            if isinstance(verification, dict):
                verification_note = (
                    f"后端落盘核验 {verification.get('verified', 0)}/{verification.get('total', 0)} 个文件通过。"
                )
            result.content = (
                f"用户已应用文件改动包 {change_set_id}。"
                f"{verification_note}"
                "本轮已进入只读验证阶段，请读取或审查改动结果，再给出最终结论。"
            )
            await self._push_agent_status(
                "改动已应用，正在验证结果",
                "verifying",
                {"iteration": iteration, "changeset_id": change_set_id, "decision": decision},
            )
        elif decision == "discarded":
            self._force_tool_finalize = True
            result.content = (
                f"用户已丢弃文件改动包 {change_set_id}。"
                "正式文件没有因该改动包发生变化；不要声称改动已经完成。"
            )
            await self._push_agent_status(
                "改动已丢弃，正在整理结果",
                "finalizing",
                {"iteration": iteration, "changeset_id": change_set_id, "decision": decision},
            )
        elif decision == "deferred":
            self._force_tool_finalize = True
            result.content = (
                f"用户选择稍后处理文件改动包 {change_set_id}。"
                "改动包仍为待确认状态，正式文件尚未变化；请简洁收尾，不要继续提交新的改动包。"
            )
            await self._push_agent_status(
                "改动已留待稍后处理，正在收尾",
                "finalizing",
                {"iteration": iteration, "changeset_id": change_set_id, "decision": decision},
            )
        else:
            self._force_tool_finalize = True
            result.content = (
                f"等待文件改动包 {change_set_id} 确认已超时。"
                "改动包仍为待确认状态，正式文件尚未变化；请结束本轮并提示用户稍后仍可处理。"
            )
            await self._push_agent_status(
                "等待确认超时，改动已留待稍后处理",
                "finalizing",
                {"iteration": iteration, "changeset_id": change_set_id, "decision": decision},
            )
        await self._push_change_set_update(result)
        return result

    async def _maybe_auto_apply_file_change(self, result: ToolResult) -> ToolResult:
        if not self._auto_apply_file_changes:
            return result
        change_set_id = result.metadata.get("changeset_id")
        if not isinstance(change_set_id, str) or not change_set_id:
            return result
        try:
            applied = await apply_change_set(self.project, change_set_id)
        except Exception as exc:
            result.content = f"{result.content}\n\n自动应用文件改动失败：{exc}。请在前端差异预览中人工确认。"
            result.metadata["auto_apply_file_changes"] = "failed"
            result.metadata["auto_apply_error"] = str(exc)
            return result

        result.content = f"已自动应用改动：{applied.title}，共 {len(applied.changes)} 个文件。"
        result.metadata["auto_apply_file_changes"] = "applied"
        self._applied_change_set_id = change_set_id
        await self._verify_applied_file_changes(result)
        await self._verify_applied_foreshadows(result)
        verification = result.metadata.get("file_verification")
        if isinstance(verification, dict):
            result.content += (
                f" 后端落盘核验 {verification.get('verified', 0)}/{verification.get('total', 0)} 个文件通过。"
            )
        if result.ui_hint and result.ui_hint.get("type") == "changeset:proposal":
            data = result.ui_hint.get("data")
            if isinstance(data, dict):
                data["status"] = applied.status
                data["applied_at"] = applied.applied_at
        return result

    async def _verify_applied_file_changes(self, result: ToolResult) -> None:
        change_set_id = result.metadata.get("changeset_id")
        if not isinstance(change_set_id, str) or not change_set_id:
            return
        verification = await verify_change_set_application(self.project, change_set_id)
        result.metadata["file_verification"] = verification
        data = result.ui_hint.get("data") if isinstance(result.ui_hint, dict) else None
        if isinstance(data, dict):
            data["file_verification"] = verification
        applied = list(self._usage_summary.get("applied_change_sets") or [])
        applied.append(
            {
                "changeset_id": change_set_id,
                "status": verification.get("status"),
                "verified": verification.get("verified"),
                "total": verification.get("total"),
                "paths": result.metadata.get("paths") or [],
            }
        )
        self._usage_summary["applied_change_sets"] = applied
        self.last_prompt_audit["usage"] = dict(self._usage_summary)

    async def _verify_applied_foreshadows(self, result: ToolResult) -> None:
        actions = result.metadata.get("foreshadow_actions")
        if not isinstance(actions, list) or not actions:
            return
        verification = await verify_foreshadow_actions(
            self.project,
            [item for item in actions if isinstance(item, dict)],
        )
        await persist_foreshadow_verification(self.project, verification)
        result.metadata["foreshadow_verification"] = verification
        data = result.ui_hint.get("data") if isinstance(result.ui_hint, dict) else None
        if isinstance(data, dict):
            data["foreshadow_verification"] = verification

    async def _tool_llm_for(self, tool_name: str) -> tuple[LLMClient | None, str | None]:
        if not self.tool_llm_resolver:
            return None, None
        try:
            llm, preset_id = await self.tool_llm_resolver(tool_name)
        except Exception:
            return None, None
        if llm is None:
            return None, None
        self._tool_llm_routes.append({"tool": tool_name, "preset_id": preset_id})
        self.last_prompt_audit["tool_llm_routes"] = list(self._tool_llm_routes)
        return llm, preset_id

    def _tool_call_value(self, call: Any, key: str) -> Any:
        if isinstance(call, dict):
            return call.get(key)
        return getattr(call, key, None)

    async def _push_to_frontend(self, result: ToolResult) -> None:
        if not self.publisher:
            return
        await self.publisher(
            {
                "type": "tool_result",
                "content": result.content,
                "ui_hint": result.ui_hint,
                "metadata": result.metadata,
            }
        )

    async def _push_change_set_update(self, result: ToolResult) -> None:
        if not self.publisher or not isinstance(result.ui_hint, dict):
            return
        await self.publisher(
            {
                "type": "changeset_update",
                "content": result.content,
                "ui_hint": result.ui_hint,
                "metadata": {
                    "approval_decision": result.metadata.get("approval_decision"),
                    "file_verification": result.metadata.get("file_verification"),
                    "foreshadow_verification": result.metadata.get("foreshadow_verification"),
                },
            }
        )

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
        preset_id: str | None = None,
        mode: str | None = None,
        call_id: str | None = None,
    ) -> None:
        if not self.publisher:
            return
        event: dict[str, Any] = {
            "type": event_type,
            "tool": {"name": name, "params": self._summarize_params(params)},
        }
        if call_id:
            event["tool"]["call_id"] = call_id
        if started is not None:
            event["tool"]["duration_ms"] = round((time.perf_counter() - started) * 1000)
        if error:
            event["tool"]["error"] = error
        if preset_id:
            event["tool"]["preset_id"] = preset_id
        if mode:
            event["tool"]["mode"] = mode
        await self.publisher(event)

    def _summarize_params(self, params: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str):
                summary[key] = f"{value[:120]}..." if len(value) > 120 else value
            elif isinstance(value, (int, float, bool)) or value is None:
                summary[key] = value
            elif key == "changes" and isinstance(value, list):
                summary[key] = [
                    self._summarize_change_param(item)
                    for item in value[:24]
                    if isinstance(item, dict)
                ]
                if len(value) > 24:
                    summary["changes_truncated"] = len(value) - 24
            elif isinstance(value, list):
                summary[key] = f"list[{len(value)}]"
            elif isinstance(value, dict):
                summary[key] = f"object[{len(value)}]"
            else:
                summary[key] = str(value)[:120]
        return summary

    def _summarize_change_param(self, item: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "path": str(item.get("path") or "")[:240],
            "operation": str(item.get("operation") or "write")[:80],
        }
        for key in ("start_line", "end_line"):
            if isinstance(item.get(key), int):
                summary[key] = item[key]
        for key in ("node_id", "source_hash"):
            value = str(item.get(key) or "")
            if value:
                summary[key] = value[:80]
        old_text = item.get("old_text")
        if isinstance(old_text, str):
            summary["old_text"] = f"{old_text[:240]}..." if len(old_text) > 240 else old_text
            summary["old_text_chars"] = len(old_text)
        for key in ("new_text", "new_content"):
            if isinstance(item.get(key), str):
                summary[f"{key}_chars"] = len(item[key])
        return summary
