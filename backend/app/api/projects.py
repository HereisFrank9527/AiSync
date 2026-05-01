from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.projects.context import ProjectContext

router = APIRouter(prefix="/projects", tags=["projects"])


class FileWriteRequest(BaseModel):
    content: str


class ProjectCreateRequest(BaseModel):
    name: str


@router.post("")
async def create_project(request: ProjectCreateRequest) -> dict[str, str]:
    project_id = request.name.strip().replace(" ", "-")
    if not project_id:
        raise HTTPException(status_code=400, detail="Project name is required")
    context = ProjectContext(Path(settings.projects_root) / project_id)
    await context.write_yaml("project.yaml", {"name": request.name})
    return {"id": project_id, "name": request.name}


@router.get("/{project_id}/files/{file_path:path}")
async def read_project_file(project_id: str, file_path: str) -> dict[str, str]:
    context = ProjectContext(Path(settings.projects_root) / project_id)
    if not await context.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": file_path, "content": await context.read_text(file_path)}


@router.put("/{project_id}/files/{file_path:path}")
async def write_project_file(project_id: str, file_path: str, request: FileWriteRequest) -> dict[str, str]:
    context = ProjectContext(Path(settings.projects_root) / project_id)
    await context.write_text(file_path, request.content)
    return {"path": file_path, "status": "written"}


@router.get("/{project_id}/files")
async def list_project_files(project_id: str) -> dict[str, list[str]]:
    context = ProjectContext(Path(settings.projects_root) / project_id)
    return {"files": await context.list_files()}
