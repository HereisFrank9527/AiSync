from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.agent import MasterAgent
from app.api.websocket import ConnectionManager
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


class AgentRunRequest(BaseModel):
    input: str
    preset_id: str | None = None
    project_path: str | None = None
    conversation_id: str | None = None


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
    else:
        llm_client = create_llm_client(settings)
        system_prompt = None

    agent = MasterAgent(
        llm_client=llm_client,
        tool_registry=create_tool_registry(),
        project=context,
        vector_store=ProjectVectorStore(context),
        publisher=publish,
        system_prompt=system_prompt,
    )
    active_agents[cache_key] = agent
    return agent


def conversation_store(project_id: str, project_path: str | None) -> ConversationStore:
    root = settings.project_path(project_id=project_id, project_path=project_path)
    return ConversationStore(root)


@router.post("/{project_id}/run")
async def run_agent(project_id: str, request: AgentRunRequest) -> dict[str, str]:
    try:
        store = conversation_store(project_id, request.project_path)
        conversation = store.get_or_create(request.conversation_id)
        store.append(conversation.id, "user", request.input, "user_message")
        agent = await get_agent(project_id, request.preset_id, request.project_path)
        result = await agent.run(request.input)
        store.append(conversation.id, "agent", result, "agent_final")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await manager.broadcast(
        str(settings.project_path(project_id=project_id, project_path=request.project_path)),
        {"type": "agent_final", "content": result, "conversation_id": conversation.id},
    )
    return {"content": result, "conversation_id": conversation.id}


@router.post("/{project_id}/interrupt")
async def interrupt_agent(project_id: str, project_path: str | None = None) -> dict[str, str]:
    agent = await get_agent(project_id, project_path=project_path)
    agent.interrupt()
    return {"status": "interrupt_requested"}


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
                    preset_id = message.get("preset_id")
                    conversation_id = message.get("conversation_id")
                    store = ConversationStore(root)
                    conversation = store.get_or_create(str(conversation_id) if conversation_id else None)
                    store.append(conversation.id, "user", content, "user_message")
                    await websocket.send_json({"type": "conversation", "conversation_id": conversation.id})
                    agent = await get_agent(project_id, preset_id, project_path)

                    async def on_text_delta(delta: str) -> None:
                        await websocket.send_json({"type": "stream", "content": delta})

                    result = await agent.run(content, on_text_delta=on_text_delta)
                    await websocket.send_json({"type": "stream_end"})
                    store.append(conversation.id, "agent", result, "agent_final")
                    await manager.broadcast(
                        str(root),
                        {"type": "agent_final", "content": result, "conversation_id": conversation.id},
                    )
                elif message.get("type") == "interrupt":
                    agent = await get_agent(project_id, project_path=project_path)
                    agent.interrupt()
            except Exception as exc:
                await websocket.send_json({"type": "error", "content": str(exc)})
    except WebSocketDisconnect:
        manager.disconnect(str(root), websocket)
