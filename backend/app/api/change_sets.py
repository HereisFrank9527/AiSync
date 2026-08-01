from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.change_sets import (
    apply_change_set,
    discard_change_set,
    list_change_sets,
    load_change_set,
    verify_change_set_application,
)
from app.change_approvals import has_change_set_waiter, resolve_change_set_decision
from app.core.config import settings
from app.projects.context import ProjectContext

router = APIRouter(prefix="/change-sets", tags=["change-sets"])


class ChangeSetActionRequest(BaseModel):
    project_id: str = "demo"
    project_path: str | None = None
    paths: list[str] | None = Field(default=None, description="Only apply selected paths. Omit to apply all.")


def project_context(project_id: str = "demo", project_path: str | None = None) -> ProjectContext:
    return ProjectContext(settings.project_path(project_id, project_path))


@router.get("")
async def list_project_change_sets(
    project_id: str = "demo",
    project_path: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    context = project_context(project_id, project_path)
    return [record.model_dump() for record in await list_change_sets(context)]


@router.get("/{change_set_id}")
async def get_project_change_set(
    change_set_id: str,
    project_id: str = "demo",
    project_path: str | None = Query(default=None),
) -> dict[str, Any]:
    context = project_context(project_id, project_path)
    try:
        record = await load_change_set(context, change_set_id)
        return {
            **record.model_dump(),
            "agent_waiting": has_change_set_waiter(context.root, change_set_id),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="change set not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{change_set_id}/apply")
async def apply_project_change_set(change_set_id: str, request: ChangeSetActionRequest) -> dict[str, Any]:
    context = project_context(request.project_id, request.project_path)
    try:
        record = await apply_change_set(context, change_set_id, paths=request.paths)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="change set not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resumed = False
    verification = None
    if record.status == "applied":
        verification = await verify_change_set_application(context, change_set_id)
        resumed = resolve_change_set_decision(context.root, change_set_id, "applied")
    return {**record.model_dump(), "agent_resumed": resumed, "file_verification": verification}


@router.post("/{change_set_id}/discard")
async def discard_project_change_set(change_set_id: str, request: ChangeSetActionRequest) -> dict[str, Any]:
    context = project_context(request.project_id, request.project_path)
    try:
        record = await discard_change_set(context, change_set_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="change set not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resumed = resolve_change_set_decision(context.root, change_set_id, "discarded")
    return {**record.model_dump(), "agent_resumed": resumed}


@router.post("/{change_set_id}/defer")
async def defer_project_change_set(change_set_id: str, request: ChangeSetActionRequest) -> dict[str, Any]:
    context = project_context(request.project_id, request.project_path)
    try:
        record = await load_change_set(context, change_set_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="change set not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record.status != "pending":
        raise HTTPException(status_code=400, detail=f"change set is already {record.status}")
    resumed = resolve_change_set_decision(context.root, change_set_id, "deferred")
    if not resumed:
        raise HTTPException(status_code=409, detail="当前没有等待该改动包确认的 Agent")
    return {**record.model_dump(), "agent_resumed": True, "deferred": True}
