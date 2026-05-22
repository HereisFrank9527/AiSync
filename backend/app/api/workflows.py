from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.config import settings
from app.projects.context import ProjectContext
from app.workflows.executor import WorkflowExecutor
from app.workflows.runs import (
    WorkflowRunCreate,
    WorkflowRunRecord,
    WorkflowRunStore,
    WorkflowRunUpdate,
    WorkflowStepUpdate,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowConfirmRequest(BaseModel):
    note: str = ""


def workflow_store(project_path: str) -> WorkflowRunStore:
    return WorkflowRunStore(settings.project_path(project_path=project_path))


def workflow_executor(project_path: str) -> WorkflowExecutor:
    root = settings.project_path(project_path=project_path)
    return WorkflowExecutor(ProjectContext(root), WorkflowRunStore(root))


@router.get("")
async def list_workflows(
    project_path: str = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[WorkflowRunRecord]:
    return workflow_store(project_path).list(limit=limit)


@router.post("", status_code=201)
async def create_workflow(body: WorkflowRunCreate, project_path: str = Query(...)) -> WorkflowRunRecord:
    return workflow_store(project_path).create(body)


@router.get("/{run_id}")
async def get_workflow(run_id: str, project_path: str = Query(...)) -> WorkflowRunRecord:
    try:
        return workflow_store(project_path).load(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc


@router.put("/{run_id}")
async def update_workflow(run_id: str, body: WorkflowRunUpdate, project_path: str = Query(...)) -> WorkflowRunRecord:
    try:
        return workflow_store(project_path).update(run_id, body)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{run_id}/steps/{step_id}")
async def update_workflow_step(
    run_id: str,
    step_id: str,
    body: WorkflowStepUpdate,
    project_path: str = Query(...),
) -> WorkflowRunRecord:
    try:
        return workflow_store(project_path).update_step(run_id, step_id, body)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{run_id}/run-next")
async def run_next_workflow_step(run_id: str, project_path: str = Query(...)) -> WorkflowRunRecord:
    try:
        return await workflow_executor(project_path).run_next(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{run_id}/confirm")
async def confirm_workflow_step(
    run_id: str,
    body: WorkflowConfirmRequest,
    project_path: str = Query(...),
) -> WorkflowRunRecord:
    try:
        return await workflow_executor(project_path).confirm_current_step(run_id, body.note)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
