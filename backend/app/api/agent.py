from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.agent import MasterAgent
from app.api.websocket import ConnectionManager
from app.conversations.memory import ConversationMemory
from app.conversations.runs import AgentRunRecord, AgentRunStore
from app.conversations.store import ConversationStore
from app.core.config import settings
from app.core.presets import preset_store
from app.llm.factory import create_llm_client, create_llm_client_from_preset
from app.projects.context import ProjectContext
from app.tools.factory import create_tool_registry
from app.vector.store import ProjectVectorStore

router = APIRouter(prefix="/agent", tags=["agent"])
manager = ConnectionManager()
active_agents: dict[str, MasterAgent] = {}
INTERRUPTED_REPLY = "操作已中断，等待新指令。"


class AgentRunRequest(BaseModel):
    input: str
    model_input: str | None = None
    preset_id: str | None = None
    project_path: str | None = None
    conversation_id: str | None = None
    enabled_tools: list[str] | None = None


@router.get("/{project_id}/runs/latest")
async def latest_agent_run(
    project_id: str,
    project_path: str = Query(...),
    conversation_id: str = Query(...),
) -> dict | None:
    runs = agent_run_store(project_id, project_path)
    record = runs.latest_for_conversation(conversation_id)
    return record.model_dump() if record else None


async def get_agent(
    project_id: str = "demo",
    preset_id: str | None = None,
    project_path: str | None = None,
) -> MasterAgent:
    preset = preset_store.get(preset_id) if preset_id else None
    preset_version = preset.updated_at if preset else "default"
    root = settings.project_path(project_id=project_id, project_path=project_path)
    cache_key = f"{root}:{preset_id or 'default'}:{preset_version}"
    if cache_key in active_agents:
        return active_agents[cache_key]

    context = ProjectContext(root)

    async def publish(message: dict) -> None:
        await manager.broadcast(str(root), message)

    if preset:
        llm_client = create_llm_client_from_preset(preset.llm)
        system_prompt = preset.behavior.system_prompt
        enabled_tools = preset.behavior.enabled_tools
    else:
        llm_client = create_llm_client(settings)
        system_prompt = None
        enabled_tools = None

    agent = MasterAgent(
        llm_client=llm_client,
        tool_registry=create_tool_registry(),
        project=context,
        vector_store=ProjectVectorStore(context),
        publisher=publish,
        system_prompt=system_prompt,
        enabled_tools=enabled_tools,
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
    if preset:
        llm_client = create_llm_client_from_preset(preset.llm)
        system_prompt = preset.behavior.system_prompt
        enabled_tools = preset.behavior.enabled_tools
    else:
        llm_client = create_llm_client(settings)
        system_prompt = None
        enabled_tools = None
    return MasterAgent(
        llm_client=llm_client,
        tool_registry=create_tool_registry(),
        project=context,
        vector_store=ProjectVectorStore(context),
        publisher=publisher,
        system_prompt=system_prompt,
        enabled_tools=enabled_tools,
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
        "content": record.phase_label,
        "run": record.model_dump(),
        "metadata": {
            "phase": record.phase,
            "run_id": record.run_id,
            "status": record.status,
        },
    }


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
async def run_agent(project_id: str, request: AgentRunRequest) -> dict[str, str]:
    store = conversation_store(project_id, request.project_path)
    runs = agent_run_store(project_id, request.project_path)
    conversation = store.get_or_create(request.conversation_id)
    run_record: AgentRunRecord | None = None
    try:
        agent = await get_agent(project_id, request.preset_id, request.project_path)
        memory = conversation_memory(project_id, request.project_path)
        memory_context = await memory.context_for(conversation)
        conversation = store.append(conversation.id, "user", request.input, "user_message")
        store.set_status(conversation.id, "running")
        run_record = runs.start(
            conversation.id,
            request.input,
            preset_id=request.preset_id,
            enabled_tools=request.enabled_tools,
        )
        await manager.broadcast(
            str(settings.project_path(project_id=project_id, project_path=request.project_path)),
            run_event(run_record),
        )
        agent_input = request.model_input or request.input
        result = await agent.run(
            agent_input,
            history=memory_context.recent_messages,
            memory_summary=memory_context.summary,
            enabled_tools=request.enabled_tools,
            override_enabled_tools="enabled_tools" in request.model_fields_set,
        )
        conversation = store.append(conversation.id, "agent", result, "agent_final")
        status = "interrupted" if result == INTERRUPTED_REPLY else "completed"
        store.set_status(conversation.id, status)
        await manager.broadcast(
            str(settings.project_path(project_id=project_id, project_path=request.project_path)),
            run_event(runs.finish(run_record.run_id, status)),
        )
        asyncio.create_task(
            update_memory_background(
                conversation.id,
                project_id,
                request.project_path,
                request.preset_id,
            )
        )
    except Exception as exc:
        store.set_status(conversation.id, "failed", str(exc))
        if run_record:
            await manager.broadcast(
                str(settings.project_path(project_id=project_id, project_path=request.project_path)),
                run_event(runs.finish(run_record.run_id, "failed", str(exc))),
            )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await manager.broadcast(
        str(settings.project_path(project_id=project_id, project_path=request.project_path)),
        {"type": "agent_final", "content": result, "conversation_id": conversation.id},
    )
    return {"content": result, "conversation_id": conversation.id}


@router.post("/{project_id}/interrupt")
async def interrupt_agent(
    project_id: str,
    project_path: str | None = None,
    preset_id: str | None = None,
) -> dict[str, str | bool]:
    agent = await get_agent(project_id, preset_id=preset_id, project_path=project_path)
    interrupted = agent.interrupt()
    return {"status": "interrupt_requested" if interrupted else "no_active_run", "interrupted": interrupted}


@router.websocket("/{project_id}/ws")
async def agent_websocket(project_id: str, websocket: WebSocket, project_path: str | None = Query(default=None)) -> None:
    root = settings.project_path(project_id=project_id, project_path=project_path)
    await manager.connect(str(root), websocket)
    try:
        while True:
            message = await websocket.receive_json()
            try:
                if message.get("type") == "user_message":
                    content = str(message.get("content", ""))
                    model_content = str(message.get("model_content", "")) if message.get("model_content") else content
                    preset_id = message.get("preset_id")
                    conversation_id = message.get("conversation_id")
                    enabled_tools = message.get("enabled_tools")
                    override_enabled_tools = "enabled_tools" in message
                    if enabled_tools is not None and not isinstance(enabled_tools, list):
                        enabled_tools = None
                        override_enabled_tools = False
                    store = ConversationStore(root)
                    runs = AgentRunStore(root)
                    conversation = store.get_or_create(str(conversation_id) if conversation_id else None)
                    memory = ConversationMemory(root)
                    memory_context = await memory.context_for(conversation)
                    conversation = store.append(conversation.id, "user", content, "user_message")
                    store.set_status(conversation.id, "running")
                    run_record = runs.start(
                        conversation.id,
                        content,
                        preset_id=str(preset_id) if preset_id else None,
                        enabled_tools=[str(item) for item in enabled_tools] if isinstance(enabled_tools, list) else None,
                    )
                    await websocket.send_json({"type": "conversation", "conversation_id": conversation.id})
                    await websocket.send_json(run_event(run_record))
                    await websocket.send_json({
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
                    })

                    async def on_text_delta(delta: str) -> None:
                        await websocket.send_json({"type": "stream", "content": delta})

                    async def publish_with_run(message: dict) -> None:
                        event_type = message.get("type")
                        if event_type == "agent_status":
                            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
                            phase = str(metadata.get("phase") or "running")
                            run = runs.update_phase(run_record.run_id, phase, str(message.get("content") or phase))
                            await websocket.send_json(run_event(run))
                        elif event_type in {"tool_call_start", "tool_call_end", "tool_call_error"}:
                            tool = message.get("tool") if isinstance(message.get("tool"), dict) else {}
                            name = str(tool.get("name") or "unknown")
                            if event_type != "tool_call_start":
                                runs.add_tool_event(
                                    run_record.run_id,
                                    name,
                                    "failed" if event_type == "tool_call_error" else "completed",
                                    int(tool["duration_ms"]) if isinstance(tool.get("duration_ms"), int) else None,
                                    str(tool.get("error")) if tool.get("error") else None,
                                )
                        await websocket.send_json(message)

                    agent = await create_agent_for_run(project_id, preset_id, project_path, publish_with_run)

                    try:
                        result = await agent.run(
                            model_content,
                            on_text_delta=on_text_delta,
                            history=memory_context.recent_messages,
                            memory_summary=memory_context.summary,
                            enabled_tools=[str(item) for item in enabled_tools] if isinstance(enabled_tools, list) else None,
                            override_enabled_tools=override_enabled_tools,
                        )
                    except Exception as exc:
                        store.set_status(conversation.id, "failed", str(exc))
                        await websocket.send_json(run_event(runs.finish(run_record.run_id, "failed", str(exc))))
                        await websocket.send_json({"type": "error", "content": str(exc)})
                        continue
                    await websocket.send_json({"type": "stream_end"})
                    conversation = store.append(conversation.id, "agent", result, "agent_final")
                    status = "interrupted" if result == INTERRUPTED_REPLY else "completed"
                    store.set_status(conversation.id, status)
                    await websocket.send_json(run_event(runs.finish(run_record.run_id, status)))
                    asyncio.create_task(
                        update_memory_background(
                            conversation.id,
                            project_id,
                            project_path,
                            str(preset_id) if preset_id else None,
                        )
                    )
                    final_event = {"type": "agent_final", "content": result, "conversation_id": conversation.id}
                    await websocket.send_json(final_event)
                    await manager.broadcast(
                        str(root),
                        final_event,
                        exclude=websocket,
                    )
                elif message.get("type") == "interrupt":
                    preset_id = message.get("preset_id")
                    agent = await get_agent(project_id, str(preset_id) if preset_id else None, project_path)
                    interrupted = agent.interrupt()
                    await websocket.send_json({
                        "type": "agent_status",
                        "content": "已请求中断当前回复" if interrupted else "当前没有正在运行的 Agent",
                        "metadata": {"phase": "interrupt_requested", "interrupted": interrupted},
                    })
            except Exception as exc:
                await websocket.send_json({"type": "error", "content": str(exc)})
    except WebSocketDisconnect:
        manager.disconnect(str(root), websocket)
