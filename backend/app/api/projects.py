from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.config import settings
from app.projects.context import ProjectContext

router = APIRouter(prefix="/projects", tags=["projects"])


class FileWriteRequest(BaseModel):
    content: str
    project_path: str | None = None


class ProjectCreateRequest(BaseModel):
    name: str
    project_path: str | None = None


class ProjectInitRequest(BaseModel):
    project_path: str | None = None


def project_context(project_id: str | None = None, project_path: str | None = None) -> ProjectContext:
    return ProjectContext(settings.project_path(project_id=project_id, project_path=project_path))


@router.post("")
async def create_project(request: ProjectCreateRequest) -> dict[str, str]:
    project_id = request.name.strip().replace(" ", "-")
    if not project_id:
        raise HTTPException(status_code=400, detail="Project name is required")
    context = project_context(project_id=project_id, project_path=request.project_path)
    await context.write_yaml("project.yaml", {"name": request.name})
    return {"id": project_id, "name": request.name, "path": str(context.root)}


@router.post("/init")
async def init_project(request: ProjectInitRequest) -> dict:
    context = project_context(project_id=request.project_path, project_path=request.project_path)
    created = await context.init_structure()
    return {"status": "initialized", "created": created}


@router.get("/files")
async def list_project_files(project_path: str = Query(...)) -> dict[str, list[str]]:
    context = project_context(project_path=project_path)
    return {"files": await context.list_files()}


@router.get("/files/{file_path:path}")
async def read_project_file(file_path: str, project_path: str = Query(...)) -> dict[str, str]:
    context = project_context(project_path=project_path)
    if not await context.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": file_path, "content": await context.read_text(file_path)}


@router.put("/files/{file_path:path}")
async def write_project_file(
    file_path: str,
    request: FileWriteRequest,
    project_path: str | None = Query(default=None),
) -> dict[str, str]:
    context = project_context(project_path=project_path or request.project_path)
    await context.write_text(file_path, request.content)
    return {"path": file_path, "status": "written"}


@router.get("/{project_id}/files")
async def list_project_files_by_id(project_id: str) -> dict[str, list[str]]:
    context = project_context(project_id=project_id)
    return {"files": await context.list_files()}


@router.get("/{project_id}/files/{file_path:path}")
async def read_project_file_by_id(project_id: str, file_path: str) -> dict[str, str]:
    context = project_context(project_id=project_id)
    if not await context.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": file_path, "content": await context.read_text(file_path)}


@router.put("/{project_id}/files/{file_path:path}")
async def write_project_file_by_id(project_id: str, file_path: str, request: FileWriteRequest) -> dict[str, str]:
    context = project_context(project_id=project_id)
    await context.write_text(file_path, request.content)
    return {"path": file_path, "status": "written"}
