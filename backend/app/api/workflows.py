from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.config import settings
from app.projects.context import ProjectContext
from app.workflows.chapter_batch import ChapterBatchCreate, build_chapter_batch_workflow
from app.workflows.executor import WorkflowExecutor
from app.workflows.runs import (
    WorkflowRunCreate,
    WorkflowRunRecord,
    WorkflowRunStore,
    WorkflowRunUpdate,
    WorkflowStepRecord,
    WorkflowStepUpdate,
)
from app.workflows.templates import workflow_template, workflow_templates

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowConfirmRequest(BaseModel):
    note: str = ""


class WorkflowFromTemplateRequest(BaseModel):
    title: str | None = None
    input_summary: str | None = None


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


@router.get("/templates")
async def list_workflow_templates() -> list[dict]:
    return workflow_templates()


@router.post("/templates/{template_id}", status_code=201)
async def create_workflow_from_template(
    template_id: str,
    body: WorkflowFromTemplateRequest,
    project_path: str = Query(...),
) -> WorkflowRunRecord:
    template = workflow_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Workflow template not found")
    data = WorkflowRunCreate(
        workflow_type=template["workflow_type"],
        title=(body.title or template["name"]),
        input_summary=(body.input_summary or template["input_summary"]),
        steps=template["steps"],
        metadata={"template_id": template_id, "source": "workflow_template", "version": 1},
    )
    return workflow_store(project_path).create(data)


@router.post("", status_code=201)
async def create_workflow(body: WorkflowRunCreate, project_path: str = Query(...)) -> WorkflowRunRecord:
    return workflow_store(project_path).create(body)


@router.post("/chapter-batches", status_code=201)
async def create_chapter_batch(
    body: ChapterBatchCreate,
    project_path: str = Query(...),
) -> WorkflowRunRecord:
    return workflow_store(project_path).create(build_chapter_batch_workflow(body))


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


@router.post("/{run_id}/steps", status_code=201)
async def add_workflow_step(
    run_id: str,
    body: WorkflowStepRecord,
    project_path: str = Query(...),
) -> WorkflowRunRecord:
    try:
        return workflow_store(project_path).add_step(run_id, body)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{run_id}/steps/{step_id}", status_code=204)
async def delete_workflow_step(
    run_id: str,
    step_id: str,
    project_path: str = Query(...),
) -> None:
    try:
        workflow_store(project_path).delete_step(run_id, step_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{run_id}/steps/{step_id}/reset")
async def reset_workflow_step(
    run_id: str,
    step_id: str,
    project_path: str = Query(...),
) -> WorkflowRunRecord:
    try:
        return workflow_store(project_path).reset_step(run_id, step_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{run_id}/steps/{step_id}/skip")
async def skip_workflow_step(
    run_id: str,
    step_id: str,
    project_path: str = Query(...),
) -> WorkflowRunRecord:
    try:
        return workflow_store(project_path).skip_step(run_id, step_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{run_id}", status_code=204)
async def delete_workflow(run_id: str, project_path: str = Query(...)) -> None:
    try:
        deleted = workflow_store(project_path).delete(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow run not found")


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
