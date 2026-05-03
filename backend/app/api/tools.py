from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.agent import get_agent
from app.core.config import settings
from app.projects.context import ProjectContext
from app.tools.base import ToolResult
from app.tools.factory import create_tool_registry

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolInvokeRequest(BaseModel):
    project_id: str = "demo"
    project_path: str | None = None
    preset_id: str | None = None
    conversation_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ToolExecuteRequest(BaseModel):
    project_id: str = "demo"
    project_path: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


@router.get("")
async def list_tools() -> list[dict[str, Any]]:
    registry = create_tool_registry()
    return [tool.frontend_descriptor() for tool in registry.all()]


@router.post("/{name}/invoke")
async def invoke_tool(name: str, request: ToolInvokeRequest) -> dict[str, Any]:
    registry = create_tool_registry()
    try:
        tool = registry.get_tool(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    agent = await get_agent(request.project_id, request.preset_id, request.project_path)
    prompt = tool.build_prompt(request.params)
    result = await agent.run(prompt)
    return {"content": result, "ui_hint": None, "metadata": {"mode": "invoke"}}


@router.post("/{name}/execute")
async def execute_tool(name: str, request: ToolExecuteRequest) -> ToolResult:
    registry = create_tool_registry()
    try:
        tool = registry.get_tool(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    context = ProjectContext(settings.project_path(request.project_id, request.project_path))
    try:
        return await tool.execute(request.params, context)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
