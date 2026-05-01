from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.agent import MasterAgent
from app.api.websocket import ConnectionManager
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


async def get_agent(project_id: str, preset_id: str | None = None) -> MasterAgent:
    preset = preset_store.get(preset_id) if preset_id else None
    preset_version = preset.updated_at if preset else "default"
    cache_key = f"{project_id}:{preset_id or 'default'}:{preset_version}"
    if project_id in active_agents:
        existing = active_agents[project_id]
        if getattr(existing, "_preset_key", None) == cache_key:
            return existing
        del active_agents[project_id]

    context = ProjectContext(Path(settings.projects_root) / project_id)

    async def publish(message: dict) -> None:
        await manager.broadcast(project_id, message)

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
    agent._preset_key = cache_key  # type: ignore[attr-defined]
    active_agents[project_id] = agent
    return agent


@router.post("/{project_id}/run")
async def run_agent(project_id: str, request: AgentRunRequest) -> dict[str, str]:
    try:
        agent = await get_agent(project_id, request.preset_id)
        result = await agent.run(request.input)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await manager.broadcast(project_id, {"type": "agent_final", "content": result})
    return {"content": result}


@router.post("/{project_id}/interrupt")
async def interrupt_agent(project_id: str) -> dict[str, str]:
    agent = await get_agent(project_id)
    agent.interrupt()
    return {"status": "interrupt_requested"}


@router.websocket("/{project_id}/ws")
async def agent_websocket(project_id: str, websocket: WebSocket) -> None:
    await manager.connect(project_id, websocket)
    try:
        while True:
            message = await websocket.receive_json()
            try:
                if message.get("type") == "user_message":
                    preset_id = message.get("preset_id")
                    agent = await get_agent(project_id, preset_id)
                    result = await agent.run(str(message.get("content", "")))
                    await manager.broadcast(project_id, {"type": "agent_final", "content": result})
                elif message.get("type") == "interrupt":
                    agent = await get_agent(project_id)
                    agent.interrupt()
            except Exception as exc:
                await websocket.send_json({"type": "error", "content": str(exc)})
    except WebSocketDisconnect:
        manager.disconnect(project_id, websocket)
