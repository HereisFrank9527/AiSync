from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.agent import MasterAgent, SYSTEM_PROMPT
from app.api.websocket import ConnectionManager
from app.conversations.memory import ConversationMemory
from app.conversations.runs import AgentRunRecord, AgentRunStore, retry_mode_for_run
from app.conversations.store import ConversationStore
from app.core.config import settings
from app.core.presets import preset_store
from app.core.system_rules import compose_system_prompt, load_project_system_rules, system_rules_cache_key
from app.llm.factory import create_llm_client, create_llm_client_from_preset
from app.projects.context import ProjectContext
from app.tools.factory import create_tool_registry
from app.tools.settings import configured_default_preset_id
from app.vector.store import ProjectVectorStore

router = APIRouter(prefix="/agent", tags=["agent"])
manager = ConnectionManager()
active_agents: dict[str, MasterAgent] = {}
active_run_ids: set[str] = set()
active_conversation_ids: set[str] = set()
active_run_agents: dict[str, MasterAgent] = {}
active_conversation_agents: dict[str, MasterAgent] = {}
active_conversation_run_ids: dict[str, str] = {}
active_run_tasks: dict[str, asyncio.Task] = {}
INTERRUPTED_REPLY = "操作已中断，等待新指令。"


def settled_agent_status(result: str, termination_reason: Any) -> str:
    if result == INTERRUPTED_REPLY:
        return "interrupted"
    if termination_reason in {"human_intervention", "awaiting_choice"}:
        return "waiting_user"
    return "completed"


class AgentRunRequest(BaseModel):
    input: str
    model_input: str | None = None
    preset_id: str | None = None
    project_path: str | None = None
    conversation_id: str | None = None
    enabled_tools: list[str] | None = None
    metadata: dict = Field(default_factory=dict)


def discard_cached_agents_for_project(project_root: str) -> None:
    """Drop idle agents whose prompts may have changed on disk."""
    prefix = f"{project_root}:"
    for cache_key in [key for key in active_agents if key.startswith(prefix)]:
        active_agents.pop(cache_key, None)


@router.get("/{project_id}/runs/latest")
async def latest_agent_run(
    project_id: str,
    project_path: str = Query(...),
    conversation_id: str = Query(...),
) -> dict | None:
    runs = agent_run_store(project_id, project_path)
    record = runs.latest_for_conversation(conversation_id)
    record = settle_stale_run_if_needed(record, runs, conversation_store(project_id, project_path))
    if record and record.status in {"failed", "interrupted"}:
        basis = retry_basis_for_run(runs, record)
        record.retry_mode = retry_mode_for_run(basis)
    return record.model_dump() if record else None


async def get_agent(
    project_id: str = "demo",
    preset_id: str | None = None,
    project_path: str | None = None,
) -> MasterAgent:
    preset = preset_store.get(preset_id) if preset_id else None
    preset_version = preset.updated_at if preset else "default"
    root = settings.project_path(project_id=project_id, project_path=project_path)
    context = ProjectContext(root)
    project_system_rules = await load_project_system_rules(context)
    context_window = preset.llm.context_window if preset else settings.llm_context_window
    native_web_search = preset.llm.native_web_search if preset else settings.llm_native_web_search
    cache_key = f"{root}:{preset_id or 'default'}:{preset_version}:{context_window}:{native_web_search}:{system_rules_cache_key(project_system_rules)}"
    if cache_key in active_agents:
        return active_agents[cache_key]

    async def publish(message: dict) -> None:
        await manager.broadcast(str(root), message)

    if preset:
        llm_client = create_llm_client_from_preset(preset.llm)
        base_system_prompt = preset.behavior.system_prompt or SYSTEM_PROMPT
        base_system_source = "preset" if preset.behavior.system_prompt else "default"
        enabled_tools = preset.behavior.enabled_tools
        context_window = preset.llm.context_window
    else:
        llm_client = create_llm_client(settings)
        base_system_prompt = SYSTEM_PROMPT
        base_system_source = "default"
        enabled_tools = None
        context_window = settings.llm_context_window
    system_prompt, system_prompt_audit = compose_system_prompt(
        base_system_prompt,
        base_system_source,
        project_system_rules,
    )
    tool_registry = create_tool_registry()

    async def resolve_tool_llm(tool_name: str):
        try:
            tool = tool_registry.get_tool(tool_name)
            tool_preset_id = await configured_default_preset_id(context, tool_name, tool.default_preset_id)
        except Exception:
            return None, None
        if not tool_preset_id or tool_preset_id == (preset_id or None):
            return None, None
        tool_preset = preset_store.get(tool_preset_id)
        if not tool_preset:
            return None, None
        return create_llm_client_from_preset(tool_preset.llm), tool_preset_id

    agent = MasterAgent(
        llm_client=llm_client,
        tool_registry=tool_registry,
        project=context,
        vector_store=ProjectVectorStore(context),
        publisher=publish,
        system_prompt=system_prompt,
        system_prompt_audit=system_prompt_audit,
        enabled_tools=enabled_tools,
        tool_llm_resolver=resolve_tool_llm,
        context_window=context_window,
    )
    active_agents[cache_key] = agent
    return agent


async def create_agent_for_run(
    project_id: str = "demo",
    preset_id: str | None = None,
    project_path: str | None = None,
    publisher=None,
) -> MasterAgent:
    preset = preset_store.get(preset_id) if preset_id else None
    root = settings.project_path(project_id=project_id, project_path=project_path)
    context = ProjectContext(root)
    project_system_rules = await load_project_system_rules(context)
    if preset:
        llm_client = create_llm_client_from_preset(preset.llm)
        base_system_prompt = preset.behavior.system_prompt or SYSTEM_PROMPT
        base_system_source = "preset" if preset.behavior.system_prompt else "default"
        enabled_tools = preset.behavior.enabled_tools
        context_window = preset.llm.context_window
    else:
        llm_client = create_llm_client(settings)
        base_system_prompt = SYSTEM_PROMPT
        base_system_source = "default"
        enabled_tools = None
        context_window = settings.llm_context_window
    system_prompt, system_prompt_audit = compose_system_prompt(
        base_system_prompt,
        base_system_source,
        project_system_rules,
    )
    tool_registry = create_tool_registry()

    async def resolve_tool_llm(tool_name: str):
        try:
            tool = tool_registry.get_tool(tool_name)
            tool_preset_id = await configured_default_preset_id(context, tool_name, tool.default_preset_id)
        except Exception:
            return None, None
        if not tool_preset_id or tool_preset_id == (preset_id or None):
            return None, None
        tool_preset = preset_store.get(tool_preset_id)
        if not tool_preset:
            return None, None
        return create_llm_client_from_preset(tool_preset.llm), tool_preset_id

    return MasterAgent(
        llm_client=llm_client,
        tool_registry=tool_registry,
        project=context,
        vector_store=ProjectVectorStore(context),
        publisher=publisher,
        system_prompt=system_prompt,
        system_prompt_audit=system_prompt_audit,
        enabled_tools=enabled_tools,
        tool_llm_resolver=resolve_tool_llm,
        context_window=context_window,
    )


def conversation_store(project_id: str, project_path: str | None) -> ConversationStore:
    root = settings.project_path(project_id=project_id, project_path=project_path)
    return ConversationStore(root)


def conversation_memory(project_id: str, project_path: str | None) -> ConversationMemory:
    root = settings.project_path(project_id=project_id, project_path=project_path)
    return ConversationMemory(root)


def agent_run_store(project_id: str, project_path: str | None) -> AgentRunStore:
    root = settings.project_path(project_id=project_id, project_path=project_path)
    return AgentRunStore(root)


def run_event(record: AgentRunRecord) -> dict:
    return {
        "type": "agent_run",
        "conversation_id": record.conversation_id,
        "content": record.phase_label,
        "run": record.model_dump(),
        "metadata": {
            "phase": record.phase,
            "run_id": record.run_id,
            "status": record.status,
        },
    }


def retry_input_for_run(record: AgentRunRecord) -> str:
    return record.input_text.strip() or record.input_preview.strip()


def retry_finalize_prompt(record: AgentRunRecord) -> str:
    usage = record.prompt_audit.get("usage") if isinstance(record.prompt_audit, dict) else {}
    applied = usage.get("applied_change_sets") if isinstance(usage, dict) else []
    applied_lines: list[str] = []
    if isinstance(applied, list):
        for item in applied:
            if not isinstance(item, dict):
                continue
            paths = item.get("paths") if isinstance(item.get("paths"), list) else []
            status = str(item.get("status") or "已应用")
            applied_lines.append(
                f"- {item.get('changeset_id') or '文件改动'}：{status}；文件：{', '.join(str(path) for path in paths) or '未记录'}"
            )
    completed_tools = [
        str(item.get("name") or "unknown")
        for item in record.tool_calls
        if isinstance(item, dict) and item.get("status") == "completed"
    ]
    return (
        "上一轮执行在最终回复前失败，但已经产生了文件或项目状态改动。\n"
        f"原始用户请求：{retry_input_for_run(record)}\n"
        f"已完成工具：{', '.join(completed_tools) or '未记录'}\n"
        f"已应用改动：\n{chr(10).join(applied_lines) or '- 已检测到写入副作用，详细改动请以当前项目文件为准。'}\n"
        f"上一轮错误：{record.error or '未记录'}\n\n"
        "请只根据以上结果和对话历史给出简短的完成情况总结。"
        "不要再次调用工具，不要重复修改文件，也不要把本段内部恢复说明复述给用户。"
    )


def retry_history_without_last_user(history: list[dict[str, str]]) -> list[dict[str, str]]:
    trimmed = list(history)
    for index in range(len(trimmed) - 1, -1, -1):
        if trimmed[index].get("role") == "user":
            del trimmed[index]
            break
    return trimmed


def retry_basis_for_run(runs: AgentRunStore, record: AgentRunRecord) -> AgentRunRecord:
    if retry_mode_for_run(record) == "finalize":
        return record
    if record.retry_of_run_id:
        try:
            parent = runs.load(record.retry_of_run_id)
        except Exception:
            parent = None
        if parent:
            return retry_basis_for_run(runs, parent)
    usage = record.prompt_audit.get("usage") if isinstance(record.prompt_audit, dict) else None
    model_requests = usage.get("model_requests") if isinstance(usage, dict) else None
    if record.tool_calls or model_requests not in {0, None}:
        return record
    records = runs.records_for_conversation(record.conversation_id)
    previous: AgentRunRecord | None = None
    for candidate in records:
        if candidate.run_id == record.run_id:
            break
        previous = candidate
    if (
        previous
        and retry_input_for_run(previous) == retry_input_for_run(record)
        and retry_mode_for_run(previous) == "finalize"
    ):
        return previous
    return record


def settle_stale_run_if_needed(
    record: AgentRunRecord | None,
    runs: AgentRunStore,
    store: ConversationStore,
) -> AgentRunRecord | None:
    if not record or record.status != "running" or record.run_id in active_run_ids:
        return record
    settled = runs.mark_interrupted_if_running(record.run_id, "上次运行已断开，已自动标记为中断。")
    try:
        conversation = store.load(record.conversation_id)
        if conversation.status == "running":
            store.set_status(record.conversation_id, "interrupted")
    except Exception:
        pass
    return settled


def format_exception(exc: Exception) -> str:
    text = str(exc).strip()
    if text:
        return text
    name = exc.__class__.__name__
    return name if name else "未知错误：异常对象没有返回错误详情。"


def is_conversation_running(conversation_id: str) -> bool:
    return conversation_id in active_conversation_ids


def mark_conversation_running(conversation_id: str, run_id: str) -> None:
    active_conversation_ids.add(conversation_id)
    active_run_ids.add(run_id)
    active_conversation_run_ids[conversation_id] = run_id


def attach_running_agent(conversation_id: str, run_id: str, agent: MasterAgent) -> None:
    active_conversation_agents[conversation_id] = agent
    active_run_agents[run_id] = agent


def attach_running_task(run_id: str, task: asyncio.Task) -> None:
    active_run_tasks[run_id] = task


def clear_conversation_running(conversation_id: str | None, run_id: str | None) -> None:
    if conversation_id:
        active_conversation_ids.discard(conversation_id)
        active_conversation_agents.pop(conversation_id, None)
        active_conversation_run_ids.pop(conversation_id, None)
    if run_id:
        active_run_ids.discard(run_id)
        active_run_agents.pop(run_id, None)
        active_run_tasks.pop(run_id, None)


def interrupt_running_agent(conversation_id: str | None = None, run_id: str | None = None) -> bool:
    resolved_run_id = run_id or (active_conversation_run_ids.get(conversation_id or "") if conversation_id else None)
    agent = active_run_agents.get(resolved_run_id or "") if resolved_run_id else None
    if not agent and conversation_id:
        agent = active_conversation_agents.get(conversation_id)
    interrupted = bool(agent and agent.interrupt())
    task = active_run_tasks.get(resolved_run_id or "") if resolved_run_id else None
    if task and not task.done():
        task.cancel()
        interrupted = True
    return interrupted


def mark_interrupt_requested(
    runs: AgentRunStore,
    store: ConversationStore,
    conversation_id: str | None = None,
    run_id: str | None = None,
    reason: str = "用户已请求中断。",
) -> AgentRunRecord | None:
    resolved_run_id = run_id or (active_conversation_run_ids.get(conversation_id or "") if conversation_id else None)
    record: AgentRunRecord | None = None
    if resolved_run_id:
        try:
            record = runs.mark_interrupted_if_running(resolved_run_id, reason)
        except Exception:
            record = None
    if not record and conversation_id:
        try:
            latest = runs.latest_for_conversation(conversation_id)
            if latest and latest.status == "running":
                record = runs.mark_interrupted_if_running(latest.run_id, reason)
        except Exception:
            record = None
    target_conversation_id = conversation_id or (record.conversation_id if record else None)
    if target_conversation_id:
        try:
            conversation = store.load(target_conversation_id)
            if conversation.status == "running":
                store.set_status(target_conversation_id, "interrupted", reason)
        except Exception:
            pass
    return record


async def update_memory_background(
    conversation_id: str,
    project_id: str,
    project_path: str | None,
    preset_id: str | None,
) -> None:
    try:
        store = conversation_store(project_id, project_path)
        conversation = store.load(conversation_id)
        agent = await get_agent(project_id, preset_id, project_path)
        memory = conversation_memory(project_id, project_path)
        await memory.update_after_turn(conversation, agent.llm)
    except Exception:
        return


@router.post("/{project_id}/run")
async def run_agent(project_id: str, request: AgentRunRequest) -> dict[str, Any]:
    store = conversation_store(project_id, request.project_path)
    runs = agent_run_store(project_id, request.project_path)
    conversation = store.get_or_create(request.conversation_id)
    if is_conversation_running(conversation.id):
        raise HTTPException(status_code=409, detail="当前对话已有 Agent 正在运行，请等待完成或先中断。")
    run_record: AgentRunRecord | None = None
    agent: MasterAgent | None = None
    try:
        # Each conversation turn must observe the latest project rules and settings.
        agent = await create_agent_for_run(project_id, request.preset_id, request.project_path)
        memory = conversation_memory(project_id, request.project_path)
        memory_context = await memory.context_for(conversation)
        conversation = store.append(
            conversation.id,
            "user",
            request.input,
            "user_message",
            metadata=request.metadata,
        )
        store.set_status(conversation.id, "running")
        run_record = runs.start(
            conversation.id,
            request.input,
            preset_id=request.preset_id,
            enabled_tools=request.enabled_tools,
        )
        mark_conversation_running(conversation.id, run_record.run_id)
        attach_running_agent(conversation.id, run_record.run_id, agent)
        await manager.broadcast(
            str(settings.project_path(project_id=project_id, project_path=request.project_path)),
            run_event(run_record),
        )
        agent_input = request.model_input or request.input
        agent_task = asyncio.create_task(
            agent.run(
                agent_input,
                history=memory_context.recent_messages,
                memory_summary=memory_context.summary,
                enabled_tools=request.enabled_tools,
                override_enabled_tools="enabled_tools" in request.model_fields_set,
                auto_apply_file_changes=bool(request.metadata.get("auto_apply_file_changes")),
                user_metadata=request.metadata,
            )
        )
        attach_running_task(run_record.run_id, agent_task)
        try:
            result = await agent_task
        except asyncio.CancelledError:
            result = INTERRUPTED_REPLY
        run_record = runs.update_prompt_audit(run_record.run_id, agent.last_prompt_audit)
        final_metadata = {
            "run_id": run_record.run_id,
            "termination_reason": agent.last_prompt_audit.get("usage", {}).get("termination_reason"),
        }
        intervention = agent.last_prompt_audit.get("usage", {}).get("intervention")
        if isinstance(intervention, dict):
            final_metadata["intervention"] = intervention
        if agent.last_choice_request:
            final_metadata["choice_request"] = agent.last_choice_request
        web_sources = agent.web_source_metadata()
        if web_sources:
            final_metadata["web_sources"] = web_sources
        conversation = store.append(
            conversation.id,
            "agent",
            result,
            "agent_final",
            metadata=final_metadata,
        )
        status = settled_agent_status(result, final_metadata.get("termination_reason"))
        store.set_status(conversation.id, status)
        await manager.broadcast(
            str(settings.project_path(project_id=project_id, project_path=request.project_path)),
            run_event(runs.finish(run_record.run_id, status)),
        )
        clear_conversation_running(conversation.id, run_record.run_id)
        asyncio.create_task(
            update_memory_background(
                conversation.id,
                project_id,
                request.project_path,
                request.preset_id,
            )
        )
    except Exception as exc:
        error = format_exception(exc)
        store.set_status(conversation.id, "failed", error)
        if run_record:
            if agent and agent.last_prompt_audit:
                runs.update_prompt_audit(run_record.run_id, agent.last_prompt_audit)
            await manager.broadcast(
                str(settings.project_path(project_id=project_id, project_path=request.project_path)),
                run_event(runs.finish(run_record.run_id, "failed", error)),
            )
            clear_conversation_running(conversation.id, run_record.run_id)
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=500, detail=error) from exc
    await manager.broadcast(
        str(settings.project_path(project_id=project_id, project_path=request.project_path)),
        {
            "type": "agent_final",
            "content": result,
            "conversation_id": conversation.id,
            "metadata": final_metadata,
        },
    )
    return {"content": result, "conversation_id": conversation.id, "metadata": final_metadata}


@router.post("/{project_id}/interrupt")
async def interrupt_agent(
    project_id: str,
    project_path: str | None = None,
    preset_id: str | None = None,
    conversation_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, str | bool]:
    interrupted = interrupt_running_agent(conversation_id=conversation_id, run_id=run_id)
    if not interrupted:
        agent = await get_agent(project_id, preset_id=preset_id, project_path=project_path)
        interrupted = agent.interrupt()
    record = None
    if interrupted or conversation_id or run_id:
        runs = agent_run_store(project_id, project_path)
        store = conversation_store(project_id, project_path)
        record = mark_interrupt_requested(runs, store, conversation_id=conversation_id, run_id=run_id)
        if record and record.status == "interrupted":
            interrupted = True
        if record:
            await manager.broadcast(
                str(settings.project_path(project_id=project_id, project_path=project_path)),
                run_event(record),
            )
    return {"status": "interrupt_requested" if interrupted else "no_active_run", "interrupted": interrupted}


@router.websocket("/{project_id}/ws")
async def agent_websocket(project_id: str, websocket: WebSocket, project_path: str | None = Query(default=None)) -> None:
    root = settings.project_path(project_id=project_id, project_path=project_path)
    await manager.connect(str(root), websocket)
    socket_available = True

    async def safe_send(message: dict, conversation_id: str | None = None) -> bool:
        nonlocal socket_available
        if not socket_available:
            return False
        payload = dict(message)
        if conversation_id and not payload.get("conversation_id"):
            payload["conversation_id"] = conversation_id
        try:
            await websocket.send_json(payload)
            return True
        except (WebSocketDisconnect, RuntimeError, OSError):
            socket_available = False
            manager.disconnect(str(root), websocket)
            return False

    async def broadcast_event(message: dict, conversation_id: str | None = None) -> None:
        payload = dict(message)
        if conversation_id and not payload.get("conversation_id"):
            payload["conversation_id"] = conversation_id
        await manager.broadcast(str(root), payload)

    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await safe_send({"type": "pong"})
                continue
            run_record: AgentRunRecord | None = None
            try:
                if message.get("type") in {"user_message", "retry_run"}:
                    store = ConversationStore(root)
                    runs = AgentRunStore(root)
                    retry_source: AgentRunRecord | None = None
                    retry_mode = None
                    retry_of_run_id = None
                    append_user_message = message.get("type") == "user_message"

                    if message.get("type") == "retry_run":
                        retry_of_run_id = str(message.get("run_id") or "").strip()
                        try:
                            retry_source = runs.load(retry_of_run_id)
                        except Exception:
                            await safe_send({"type": "error", "content": "找不到需要重试的 Agent 运行记录。"})
                            continue
                        latest = runs.latest_for_conversation(retry_source.conversation_id)
                        if not latest or latest.run_id != retry_source.run_id:
                            await safe_send({"type": "error", "content": "只能重试当前对话的最后一轮运行。"})
                            continue
                        termination = retry_source.prompt_audit.get("usage", {}).get("termination_reason")
                        if retry_source.status == "running" or (
                            retry_source.status == "completed" and termination == "completed"
                        ):
                            await safe_send({"type": "error", "content": "该运行仍在进行或已经正常完成，无需重试。"})
                            continue
                        conversation = store.get_or_create(retry_source.conversation_id)
                        retry_basis = retry_basis_for_run(runs, retry_source)
                        content = retry_input_for_run(retry_basis)
                        if not content:
                            await safe_send({"type": "error", "content": "原始输入未保存，无法安全重试。"})
                            continue
                        preset_id = retry_basis.preset_id
                        enabled_tools: list[str] | None = retry_basis.enabled_tools
                        override_enabled_tools = enabled_tools is not None
                        retry_mode = retry_mode_for_run(retry_basis)
                        metadata = {
                            "retry_of_run_id": retry_source.run_id,
                            "retry_basis_run_id": retry_basis.run_id,
                            "retry_mode": retry_mode,
                        }
                        auto_apply_file_changes = False
                        model_content = content
                        memory = ConversationMemory(root)
                        memory_context = await memory.context_for(conversation)
                        if retry_mode == "restart":
                            memory_context.recent_messages = retry_history_without_last_user(
                                memory_context.recent_messages
                            )
                        else:
                            model_content = retry_finalize_prompt(retry_basis)
                            enabled_tools = []
                            override_enabled_tools = True
                    else:
                        content = str(message.get("content", ""))
                        model_content = (
                            str(message.get("model_content", "")) if message.get("model_content") else content
                        )
                        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
                        auto_apply_file_changes = bool(metadata.get("auto_apply_file_changes"))
                        preset_id = message.get("preset_id")
                        conversation_id = message.get("conversation_id")
                        enabled_tools = message.get("enabled_tools")
                        override_enabled_tools = "enabled_tools" in message
                        if enabled_tools is not None and not isinstance(enabled_tools, list):
                            enabled_tools = None
                            override_enabled_tools = False
                        conversation = store.get_or_create(str(conversation_id) if conversation_id else None)
                        memory = ConversationMemory(root)
                        memory_context = await memory.context_for(conversation)

                    if is_conversation_running(conversation.id):
                        await safe_send({
                            "type": "error",
                            "content": "当前对话已有 Agent 正在运行，请等待完成或先中断。",
                        }, conversation.id)
                        continue
                    if append_user_message:
                        conversation = store.append(
                            conversation.id,
                            "user",
                            content,
                            "user_message",
                            metadata=metadata,
                        )
                    store.set_status(conversation.id, "running")
                    run_record = runs.start(
                        conversation.id,
                        content,
                        preset_id=str(preset_id) if preset_id else None,
                        enabled_tools=[str(item) for item in enabled_tools] if isinstance(enabled_tools, list) else None,
                        retry_of_run_id=retry_of_run_id,
                        retry_mode=retry_mode,
                    )
                    mark_conversation_running(conversation.id, run_record.run_id)
                    await safe_send({"type": "conversation", "conversation_id": conversation.id})
                    await broadcast_event(run_event(run_record), conversation.id)
                    if retry_mode:
                        await broadcast_event({
                            "type": "agent_status",
                            "content": "正在继续收尾" if retry_mode == "finalize" else "正在重新发送本轮请求",
                            "metadata": {"phase": "retrying", "retry_mode": retry_mode},
                        }, conversation.id)
                    await broadcast_event({
                        "type": "memory_status",
                        "content": "会话记忆已注入",
                        "memory": {
                            "summary": bool(memory_context.summary),
                            "recent_messages": len(memory_context.recent_messages),
                            "summary_pending": memory_context.summary_pending,
                            "summary_quality": memory_context.summary_quality,
                            "summary_updated_at": memory_context.summary_updated_at,
                            "summary_chars": memory_context.summary_chars,
                            "recent_window": memory_context.recent_window,
                            "old_message_count": memory_context.old_message_count,
                            "total_message_count": memory_context.total_message_count,
                        },
                    }, conversation.id)

                    async def on_text_delta(delta: str) -> None:
                        draft = runs.append_draft(run_record.run_id, delta)
                        await broadcast_event(
                            {
                                "type": "stream",
                                "content": delta,
                                "metadata": {
                                    "run_id": run_record.run_id,
                                    "stream_version": draft.draft_version,
                                },
                            },
                            conversation.id,
                        )

                    async def publish_with_run(message: dict) -> None:
                        event_type = message.get("type")
                        if event_type == "agent_status":
                            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
                            phase = str(metadata.get("phase") or "running")
                            run = runs.update_phase(run_record.run_id, phase, str(message.get("content") or phase))
                            await broadcast_event(run_event(run), conversation.id)
                        elif event_type in {"tool_call_start", "tool_call_end", "tool_call_error"}:
                            tool = message.get("tool") if isinstance(message.get("tool"), dict) else {}
                            name = str(tool.get("name") or "unknown")
                            call_id = str(tool.get("call_id") or "")
                            params = tool.get("params") if isinstance(tool.get("params"), dict) else None
                            if event_type == "tool_call_start":
                                run = runs.start_tool_event(
                                    run_record.run_id,
                                    name,
                                    call_id,
                                    params=params,
                                )
                            else:
                                run = runs.add_tool_event(
                                    run_record.run_id,
                                    name,
                                    "failed" if event_type == "tool_call_error" else "completed",
                                    duration_ms=(
                                        int(tool["duration_ms"])
                                        if isinstance(tool.get("duration_ms"), int)
                                        else None
                                    ),
                                    error=str(tool.get("error")) if tool.get("error") else None,
                                    preset_id=str(tool.get("preset_id")) if tool.get("preset_id") else None,
                                    mode=str(tool.get("mode")) if tool.get("mode") else None,
                                    params=params if event_type == "tool_call_error" else None,
                                    call_id=call_id,
                                )
                            await broadcast_event(run_event(run), conversation.id)
                        elif event_type == "prompt_audit":
                            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
                            prompt_audit = metadata.get("prompt_audit")
                            if isinstance(prompt_audit, dict):
                                run = runs.update_prompt_audit(run_record.run_id, prompt_audit)
                                await broadcast_event(run_event(run), conversation.id)
                        elif event_type == "tool_result":
                            ui_hint = message.get("ui_hint") if isinstance(message.get("ui_hint"), dict) else None
                            if ui_hint and ui_hint.get("type") in {"changeset:proposal", "list:issues"}:
                                message_metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
                                store.append(
                                    conversation.id,
                                    "agent",
                                    str(message.get("content") or ""),
                                    "tool_result",
                                    ui_hint=ui_hint,
                                    metadata={**message_metadata, "run_id": run_record.run_id},
                                )
                        elif event_type == "changeset_update":
                            ui_hint = message.get("ui_hint") if isinstance(message.get("ui_hint"), dict) else None
                            data = ui_hint.get("data") if ui_hint else None
                            change_set_id = str(data.get("id") or "") if isinstance(data, dict) else ""
                            if ui_hint and change_set_id:
                                store.update_change_set_message(
                                    conversation.id,
                                    change_set_id,
                                    content=str(message.get("content") or ""),
                                    ui_hint=ui_hint,
                                    metadata=message.get("metadata") if isinstance(message.get("metadata"), dict) else None,
                                )
                        await broadcast_event(message, conversation.id)

                    agent = await create_agent_for_run(project_id, preset_id, project_path, publish_with_run)
                    attach_running_agent(conversation.id, run_record.run_id, agent)

                    try:
                        agent_task = asyncio.create_task(
                            agent.run(
                                model_content,
                                on_text_delta=on_text_delta,
                                history=memory_context.recent_messages,
                                memory_summary=memory_context.summary,
                                enabled_tools=[str(item) for item in enabled_tools] if isinstance(enabled_tools, list) else None,
                                override_enabled_tools=override_enabled_tools,
                                auto_apply_file_changes=auto_apply_file_changes,
                                user_metadata=metadata,
                            )
                        )
                        attach_running_task(run_record.run_id, agent_task)
                        try:
                            result = await agent_task
                        except asyncio.CancelledError:
                            result = INTERRUPTED_REPLY
                    except Exception as exc:
                        error = format_exception(exc)
                        store.set_status(conversation.id, "failed", error)
                        runs.flush_draft(run_record.run_id)
                        if agent.last_prompt_audit:
                            runs.update_prompt_audit(run_record.run_id, agent.last_prompt_audit)
                        await broadcast_event(
                            run_event(runs.finish(run_record.run_id, "failed", error)),
                            conversation.id,
                        )
                        clear_conversation_running(conversation.id, run_record.run_id)
                        await broadcast_event({"type": "error", "content": error}, conversation.id)
                        continue
                    draft = runs.flush_draft(run_record.run_id)
                    await broadcast_event(
                        {
                            "type": "stream_end",
                            "metadata": {
                                "run_id": run_record.run_id,
                                "stream_version": draft.draft_version,
                            },
                        },
                        conversation.id,
                    )
                    if agent.last_prompt_audit:
                        run_record = runs.update_prompt_audit(run_record.run_id, agent.last_prompt_audit)
                    final_metadata = {
                        "run_id": run_record.run_id,
                        "termination_reason": agent.last_prompt_audit.get("usage", {}).get("termination_reason"),
                    }
                    intervention = agent.last_prompt_audit.get("usage", {}).get("intervention")
                    if isinstance(intervention, dict):
                        final_metadata["intervention"] = intervention
                    if agent.last_choice_request:
                        final_metadata["choice_request"] = agent.last_choice_request
                    web_sources = agent.web_source_metadata()
                    if web_sources:
                        final_metadata["web_sources"] = web_sources
                    conversation = store.append(
                        conversation.id,
                        "agent",
                        result,
                        "agent_final",
                        metadata=final_metadata,
                    )
                    status = settled_agent_status(result, final_metadata.get("termination_reason"))
                    store.set_status(conversation.id, status)
                    await broadcast_event(run_event(runs.finish(run_record.run_id, status)), conversation.id)
                    clear_conversation_running(conversation.id, run_record.run_id)
                    asyncio.create_task(
                        update_memory_background(
                            conversation.id,
                            project_id,
                            project_path,
                            str(preset_id) if preset_id else None,
                        )
                    )
                    final_event = {
                        "type": "agent_final",
                        "content": result,
                        "conversation_id": conversation.id,
                        "metadata": final_metadata,
                    }
                    await broadcast_event(final_event, conversation.id)
                elif message.get("type") == "interrupt":
                    preset_id = message.get("preset_id")
                    conversation_id = str(message.get("conversation_id") or "") or None
                    run_id = str(message.get("run_id") or "") or None
                    interrupted = interrupt_running_agent(conversation_id=conversation_id, run_id=run_id)
                    if not interrupted:
                        agent = await get_agent(project_id, str(preset_id) if preset_id else None, project_path)
                        interrupted = agent.interrupt()
                    record = None
                    if interrupted:
                        record = mark_interrupt_requested(
                            AgentRunStore(root),
                            ConversationStore(root),
                            conversation_id=conversation_id,
                            run_id=run_id,
                        )
                    if record:
                        await safe_send(run_event(record))
                    await safe_send({
                        "type": "agent_status",
                        "content": "已请求中断当前回复" if interrupted else "当前没有正在运行的 Agent",
                        "metadata": {"phase": "interrupt_requested", "interrupted": interrupted},
                    }, conversation_id)
            except Exception as exc:
                if run_record:
                    clear_conversation_running(run_record.conversation_id, run_record.run_id)
                    try:
                        AgentRunStore(root).mark_interrupted_if_running(
                            run_record.run_id,
                            "运行连接异常，已自动标记为中断。",
                        )
                    except Exception:
                        pass
                await safe_send(
                    {"type": "error", "content": format_exception(exc)},
                    run_record.conversation_id if run_record else None,
                )
    except (WebSocketDisconnect, RuntimeError, OSError):
        manager.disconnect(str(root), websocket)
