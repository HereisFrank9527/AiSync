from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
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


class ToolSettingUpdate(BaseModel):
    project_id: str = "demo"
    project_path: str | None = None
    default_preset_id: str | None = None


class ToolRunRecord(BaseModel):
    run_id: str
    tool_name: str
    mode: Literal["execute", "invoke"]
    status: Literal["completed", "failed"]
    started_at: str
    finished_at: str
    file_access: dict[str, list[str]]
    params: dict[str, Any] = Field(default_factory=dict)
    result: ToolResult | None = None
    error: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_context(project_id: str = "demo", project_path: str | None = None) -> ProjectContext:
    return ProjectContext(settings.project_path(project_id, project_path))


async def save_tool_run(context: ProjectContext, record: ToolRunRecord) -> None:
    await context.write_json(f".aisync/tool_runs/{record.run_id}.json", record.model_dump())


async def load_tool_runs(context: ProjectContext) -> list[dict[str, Any]]:
    files = await context.list_files(".aisync/tool_runs")
    runs: list[dict[str, Any]] = []
    for path in files:
        if not path.endswith(".json"):
            continue
        try:
            runs.append(await context.read_json(path))
        except Exception:
            continue
    return sorted(runs, key=lambda item: str(item.get("started_at", "")), reverse=True)


async def load_tool_settings(context: ProjectContext) -> dict[str, Any]:
    path = ".aisync/tool_settings.json"
    if not await context.exists(path):
        return {"tools": {}}
    try:
        data = await context.read_json(path)
    except Exception:
        return {"tools": {}}
    if not isinstance(data, dict):
        return {"tools": {}}
    tools = data.get("tools")
    if not isinstance(tools, dict):
        data["tools"] = {}
    return data


async def save_tool_settings(context: ProjectContext, settings_data: dict[str, Any]) -> None:
    await context.write_json(".aisync/tool_settings.json", settings_data)


async def configured_default_preset_id(context: ProjectContext, tool_name: str, code_default: str | None) -> str | None:
    settings_data = await load_tool_settings(context)
    entry = settings_data.get("tools", {}).get(tool_name)
    if isinstance(entry, dict) and "default_preset_id" in entry:
        value = entry.get("default_preset_id")
        return str(value) if value else None
    return code_default


async def descriptors_with_settings(context: ProjectContext) -> list[dict[str, Any]]:
    registry = create_tool_registry()
    settings_data = await load_tool_settings(context)
    configured = settings_data.get("tools", {})
    descriptors: list[dict[str, Any]] = []
    for descriptor in registry.get_all_descriptors():
        entry = configured.get(descriptor["name"]) if isinstance(configured, dict) else None
        if isinstance(entry, dict) and "default_preset_id" in entry:
            value = entry.get("default_preset_id")
            descriptor["default_preset_id"] = str(value) if value else None
        descriptors.append(descriptor)
    return descriptors


@router.get("")
async def list_tools(project_id: str = "demo", project_path: str | None = None) -> list[dict[str, Any]]:
    context = project_context(project_id, project_path)
    return await descriptors_with_settings(context)


@router.put("/{name}/settings")
async def update_tool_settings(name: str, request: ToolSettingUpdate) -> dict[str, Any]:
    registry = create_tool_registry()
    try:
        registry.get_tool(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    context = project_context(request.project_id, request.project_path)
    settings_data = await load_tool_settings(context)
    tools = settings_data.setdefault("tools", {})
    if not isinstance(tools, dict):
        tools = {}
        settings_data["tools"] = tools
    tools[name] = {"default_preset_id": request.default_preset_id}
    await save_tool_settings(context, settings_data)
    return {"name": name, "default_preset_id": request.default_preset_id}


@router.get("/runs")
async def list_runs(
    project_id: str = "demo",
    project_path: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    context = project_context(project_id, project_path)
    return (await load_tool_runs(context))[:limit]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, project_id: str = "demo", project_path: str | None = None) -> dict[str, Any]:
    context = project_context(project_id, project_path)
    path = f".aisync/tool_runs/{run_id}.json"
    if not await context.exists(path):
        raise HTTPException(status_code=404, detail="Tool run not found")
    return await context.read_json(path)


@router.post("/{name}/invoke")
async def invoke_tool(name: str, request: ToolInvokeRequest) -> ToolRunRecord:
    registry = create_tool_registry()
    try:
        tool = registry.get_tool(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    context = project_context(request.project_id, request.project_path)
    started_at = now_iso()
    run_id = f"toolrun_{uuid4().hex}"
    try:
        configured_preset_id = await configured_default_preset_id(context, name, tool.default_preset_id)
        effective_preset_id = request.preset_id or configured_preset_id
        agent = await get_agent(request.project_id, effective_preset_id, request.project_path)
        result = await tool.invoke(request.params, context, agent.llm)
        if result is None:
            prompt = tool.build_prompt(request.params)
            content = await agent.run(prompt)
            result = ToolResult(content=content, metadata={"mode": "invoke"})
        record = ToolRunRecord(
            run_id=run_id,
            tool_name=name,
            mode="invoke",
            status="completed",
            started_at=started_at,
            finished_at=now_iso(),
            file_access=tool.file_access().model_dump(),
            params=request.params,
            result=result,
        )
        await save_tool_run(context, record)
        return record
    except Exception as exc:
        record = ToolRunRecord(
            run_id=run_id,
            tool_name=name,
            mode="invoke",
            status="failed",
            started_at=started_at,
            finished_at=now_iso(),
            file_access=tool.file_access().model_dump(),
            params=request.params,
            error=str(exc),
        )
        await save_tool_run(context, record)
        raise HTTPException(status_code=400, detail=record.model_dump()) from exc


@router.post("/{name}/execute")
async def execute_tool(name: str, request: ToolExecuteRequest) -> ToolRunRecord:
    registry = create_tool_registry()
    try:
        tool = registry.get_tool(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    context = project_context(request.project_id, request.project_path)
    started_at = now_iso()
    run_id = f"toolrun_{uuid4().hex}"
    try:
        result = await tool.execute(request.params, context)
        record = ToolRunRecord(
            run_id=run_id,
            tool_name=name,
            mode="execute",
            status="completed",
            started_at=started_at,
            finished_at=now_iso(),
            file_access=tool.file_access().model_dump(),
            params=request.params,
            result=result,
        )
        await save_tool_run(context, record)
        return record
    except Exception as exc:
        record = ToolRunRecord(
            run_id=run_id,
            tool_name=name,
            mode="execute",
            status="failed",
            started_at=started_at,
            finished_at=now_iso(),
            file_access=tool.file_access().model_dump(),
            params=request.params,
            error=str(exc),
        )
        await save_tool_run(context, record)
        raise HTTPException(status_code=400, detail=record.model_dump()) from exc
