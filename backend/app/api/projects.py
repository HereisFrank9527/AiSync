from __future__ import annotations

from pathlib import Path
from typing import Any

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


class ProjectOverviewUpdateRequest(BaseModel):
    project_path: str | None = None
    name: str
    status: str | None = None
    synopsis: str | None = None
    goal: str | None = None
    target_chapters: int | None = None
    target_characters: int | None = None


def project_context(project_id: str | None = None, project_path: str | None = None) -> ProjectContext:
    return ProjectContext(settings.project_path(project_id=project_id, project_path=project_path))


def first_heading(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def text_length(content: str) -> int:
    return len("".join(line.strip() for line in content.splitlines() if not line.lstrip().startswith("#")))


async def read_project_metadata(context: ProjectContext) -> dict[str, Any]:
    if not await context.exists("project.yaml"):
        return {}
    try:
        data = await context.read_yaml("project.yaml") or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def project_info_from_metadata(metadata: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    nested = metadata.get("project")
    if not isinstance(nested, dict):
        nested = {}

    def int_value(value: Any) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

    target_chapters = nested.get("target_chapters") or metadata.get("target_chapters") or 0
    target_characters = nested.get("target_characters") or metadata.get("target_characters") or 0
    return {
        "name": str(nested.get("name") or metadata.get("name") or fallback_name),
        "status": str(nested.get("status") or metadata.get("status") or "planning"),
        "synopsis": str(nested.get("synopsis") or metadata.get("synopsis") or ""),
        "goal": str(nested.get("goal") or metadata.get("goal") or ""),
        "target_chapters": int_value(target_chapters),
        "target_characters": int_value(target_characters),
    }


def progress_ratio(done: int, target: int) -> float:
    if target <= 0:
        return 0
    return min(round(done / target, 4), 1)


async def build_project_overview(context: ProjectContext) -> dict[str, Any]:
    metadata = await read_project_metadata(context)
    project_info = project_info_from_metadata(metadata, context.root.name)
    files = await context.list_files()
    normalized_files = [path.replace("\\", "/") for path in files]
    chapter_files = sorted(
        path for path in normalized_files
        if path.startswith("chapters/") and path.endswith(".md")
    )
    character_files = [
        path for path in normalized_files
        if path.startswith("characters/") and path.endswith("profile.yaml")
    ]
    world_files = sorted(
        path for path in normalized_files
        if path.startswith("world/") and path.endswith(".md")
    )
    outline_items = 0
    completed_outline_items = 0
    foreshadow_items = 0
    paid_off_foreshadow_items = 0
    if await context.exists("plot/outline.json"):
        try:
            outline_data = await context.read_json("plot/outline.json")
            if isinstance(outline_data, dict):
                outline_entries = outline_data.get("items") or outline_data.get("chapters") or []
            elif isinstance(outline_data, list):
                outline_entries = outline_data
            else:
                outline_entries = []
            if isinstance(outline_entries, list):
                outline_items = len(outline_entries)
                completed_outline_items = sum(
                    1 for item in outline_entries
                    if isinstance(item, dict) and item.get("status") == "done"
                )
        except Exception:
            outline_items = 0
            completed_outline_items = 0
    if await context.exists("plot/foreshadows.json"):
        try:
            foreshadow_data = await context.read_json("plot/foreshadows.json")
            if isinstance(foreshadow_data, dict):
                foreshadow_entries = foreshadow_data.get("items") or []
            elif isinstance(foreshadow_data, list):
                foreshadow_entries = foreshadow_data
            else:
                foreshadow_entries = []
            if isinstance(foreshadow_entries, list):
                foreshadow_items = len(foreshadow_entries)
                paid_off_foreshadow_items = sum(
                    1 for item in foreshadow_entries
                    if isinstance(item, dict) and item.get("status") == "paid_off"
                )
        except Exception:
            foreshadow_items = 0
            paid_off_foreshadow_items = 0

    chapters: list[dict[str, Any]] = []
    total_chars = 0
    for path in chapter_files:
        try:
            content = await context.read_text(path)
        except Exception:
            content = ""
        count = text_length(content)
        total_chars += count
        chapters.append({
            "path": path,
            "title": first_heading(content, Path(path).stem),
            "characters": count,
        })

    return {
        **project_info,
        "path": str(context.root),
        "stats": {
            "completed_chapters": len(chapter_files),
            "total_characters": total_chars,
            "characters": len(character_files),
            "world_documents": len(world_files),
            "outline_items": outline_items,
            "completed_outline_items": completed_outline_items,
            "foreshadow_items": foreshadow_items,
            "paid_off_foreshadow_items": paid_off_foreshadow_items,
            "chapter_progress": progress_ratio(len(chapter_files), project_info["target_chapters"]),
            "character_progress": progress_ratio(total_chars, project_info["target_characters"]),
            "outline_progress": progress_ratio(completed_outline_items, outline_items),
            "foreshadow_progress": progress_ratio(paid_off_foreshadow_items, foreshadow_items),
        },
        "chapters": chapters,
        "world_documents": world_files,
    }


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


@router.get("/overview")
async def get_project_overview(project_path: str = Query(...)) -> dict[str, Any]:
    context = project_context(project_path=project_path)
    return await build_project_overview(context)


@router.put("/overview")
async def update_project_overview(request: ProjectOverviewUpdateRequest) -> dict[str, Any]:
    context = project_context(project_path=request.project_path)
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")
    metadata = await read_project_metadata(context)
    project_info = project_info_from_metadata(metadata, context.root.name)
    project_info.update({
        "name": name,
        "status": (request.status or "").strip() or "planning",
        "synopsis": (request.synopsis or "").strip(),
        "goal": (request.goal or "").strip(),
        "target_chapters": max(request.target_chapters or 0, 0),
        "target_characters": max(request.target_characters or 0, 0),
    })
    metadata["name"] = name
    metadata["project"] = project_info
    await context.write_yaml("project.yaml", metadata)
    return await build_project_overview(context)


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
