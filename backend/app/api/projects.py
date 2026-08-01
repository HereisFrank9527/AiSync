from __future__ import annotations

import asyncio
import io
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.config import settings
from app.projects.context import ProjectContext

router = APIRouter(prefix="/projects", tags=["projects"])

SAFE_PROJECT_FILE_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
BLOCKED_PROJECT_FILE_ROOTS = {".aisync", ".vectordb"}
RESERVED_PROJECT_FILE_PATHS = {"temp/.aisync-temp.json"}
EXPORT_EXCLUDED_ROOTS = {".vectordb", "__pycache__"}


class FileWriteRequest(BaseModel):
    content: str
    project_path: str | None = None


class ProjectCreateRequest(BaseModel):
    name: str
    project_path: str | None = None


class ProjectInitRequest(BaseModel):
    project_path: str | None = None


class ProjectRenameRequest(BaseModel):
    project_path: str
    name: str


class ProjectOverviewUpdateRequest(BaseModel):
    project_path: str | None = None
    name: str
    status: str | None = None
    synopsis: str | None = None
    goal: str | None = None
    target_chapters: int | None = None
    target_characters: int | None = None


class FileMoveRequest(BaseModel):
    project_path: str | None = None
    old_path: str
    new_path: str


def managed_projects_root() -> Path:
    root = Path(settings.projects_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def slugify_project_name(name: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", name.strip())
    value = value.strip(".-_")
    return value or "untitled"


def unique_project_dir(name: str) -> tuple[str, Path]:
    root = managed_projects_root()
    base = slugify_project_name(name)
    project_id = base
    index = 2
    while (root / project_id).exists():
        project_id = f"{base}-{index}"
        index += 1
    return project_id, root / project_id


def managed_project_path(project_path: str) -> Path:
    root = managed_projects_root()
    path = Path(project_path).expanduser().resolve()
    if path == root or root not in path.parents:
        raise HTTPException(status_code=400, detail="project is not in managed project library")
    if not path.exists() or not path.is_dir() or not (path / "project.yaml").exists():
        raise HTTPException(status_code=404, detail="project not found")
    return path


def project_summary_from_path(path: Path) -> dict[str, str]:
    metadata_path = path / "project.yaml"
    name = path.name
    if metadata_path.exists():
        try:
            import yaml

            metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
            if isinstance(metadata, dict):
                nested = metadata.get("project")
                if isinstance(nested, dict) and nested.get("name"):
                    name = str(nested["name"])
                elif metadata.get("name"):
                    name = str(metadata["name"])
        except Exception:
            name = path.name
    return {"id": path.name, "name": name, "path": str(path)}


def project_context(project_id: str | None = None, project_path: str | None = None) -> ProjectContext:
    return ProjectContext(settings.project_path(project_id=project_id, project_path=project_path))


def normalize_project_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip().lstrip("/")
    if not normalized or normalized == ".":
        raise HTTPException(status_code=400, detail="path is required")
    parts = normalized.split("/")
    if "\x00" in normalized or any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(status_code=400, detail="invalid path")
    if parts[0] in BLOCKED_PROJECT_FILE_ROOTS or any(part.startswith(".") for part in parts):
        raise HTTPException(status_code=400, detail="internal paths are not editable")
    if normalized in RESERVED_PROJECT_FILE_PATHS:
        raise HTTPException(status_code=400, detail="reserved project metadata file")
    if Path(normalized).suffix.lower() not in SAFE_PROJECT_FILE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported file type")
    return normalized


def normalize_temp_path(path: str) -> str:
    normalized = normalize_project_relative_path(path)
    if normalized == "temp" or not normalized.startswith("temp/"):
        raise HTTPException(status_code=400, detail="path must be under temp/")
    return normalized


def normalize_project_directory_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip().strip("/")
    parts = normalized.split("/")
    if (
        not normalized
        or any(part in {"", ".", ".."} for part in parts)
        or any(part.startswith(".") for part in parts)
        or parts[0] in BLOCKED_PROJECT_FILE_ROOTS
    ):
        raise HTTPException(status_code=400, detail="invalid project directory")
    return normalized


def is_safe_project_file(path: str) -> bool:
    normalized = path.replace("\\", "/").strip().lstrip("/")
    parts = normalized.split("/")
    if not normalized or normalized in RESERVED_PROJECT_FILE_PATHS:
        return False
    if parts[0] in BLOCKED_PROJECT_FILE_ROOTS or any(part.startswith(".") for part in parts):
        return False
    return Path(normalized).suffix.lower() in SAFE_PROJECT_FILE_EXTENSIONS


def safe_zip_members(zip_file: zipfile.ZipFile) -> tuple[list[tuple[zipfile.ZipInfo, str]], str | None]:
    raw_names = []
    for info in zip_file.infolist():
        if info.is_dir():
            continue
        normalized = info.filename.replace("\\", "/").strip()
        parts = normalized.split("/")
        if (
            not normalized
            or "\x00" in normalized
            or normalized.startswith("/")
            or Path(normalized).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise HTTPException(status_code=400, detail=f"unsafe zip member: {info.filename}")
        if not normalized:
            continue
        raw_names.append(normalized)
    if not raw_names:
        raise HTTPException(status_code=400, detail="zip archive has no files")

    strip_root: str | None = None
    if not any(name == "project.yaml" for name in raw_names):
        first_parts = [name.split("/", 1)[0] for name in raw_names if "/" in name]
        if first_parts and len(first_parts) == len(raw_names) and len(set(first_parts)) == 1:
            strip_root = first_parts[0]

    members: list[tuple[zipfile.ZipInfo, str]] = []
    for info in zip_file.infolist():
        if info.is_dir():
            continue
        normalized = info.filename.replace("\\", "/").strip()
        if strip_root and normalized.startswith(f"{strip_root}/"):
            normalized = normalized[len(strip_root) + 1:]
        parts = normalized.split("/")
        if (
            not normalized
            or "\x00" in normalized
            or normalized.startswith("/")
            or Path(normalized).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise HTTPException(status_code=400, detail=f"unsafe zip member: {info.filename}")
        members.append((info, normalized))
    return members, strip_root


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
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")
    if request.project_path:
        project_id = slugify_project_name(name)
        context = project_context(project_id=project_id, project_path=request.project_path)
    else:
        project_id, root = unique_project_dir(name)
        context = ProjectContext(root)
    await context.init_structure()
    await context.write_yaml("project.yaml", {"name": name, "project": {"name": name}})
    return {"id": project_id, "name": name, "path": str(context.root)}


@router.get("")
async def list_projects() -> list[dict[str, str]]:
    root = managed_projects_root()
    projects = [
        project_summary_from_path(path)
        for path in root.iterdir()
        if path.is_dir() and (path / "project.yaml").exists()
    ]
    return sorted(projects, key=lambda item: item["name"].casefold())


@router.put("/name")
async def rename_project(request: ProjectRenameRequest) -> dict[str, str]:
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")
    context = ProjectContext(Path(request.project_path).expanduser().resolve())
    metadata = await read_project_metadata(context)
    metadata["name"] = name
    project_info = project_info_from_metadata(metadata, context.root.name)
    project_info["name"] = name
    metadata["project"] = project_info
    await context.write_yaml("project.yaml", metadata)
    return project_summary_from_path(context.root)


@router.delete("")
async def delete_project(project_path: str = Query(...)) -> dict[str, str]:
    path = managed_project_path(project_path)
    project_id = path.name
    shutil.rmtree(path)
    return {"id": project_id, "path": str(path), "status": "deleted"}


@router.post("/import")
async def import_project(
    data: bytes = Body(..., media_type="application/zip"),
    name: str | None = Query(default=None),
) -> dict[str, str]:
    if not data:
        raise HTTPException(status_code=400, detail="zip archive is empty")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="invalid zip archive") from exc

    with archive:
        members, strip_root = safe_zip_members(archive)
        fallback_name = name or strip_root or "imported-project"
        project_id, target = unique_project_dir(fallback_name)
        target.mkdir(parents=True, exist_ok=False)
        try:
            for info, relative_path in members:
                output_path = (target / relative_path).resolve()
                if output_path != target and target not in output_path.parents:
                    raise HTTPException(status_code=400, detail=f"unsafe zip member: {info.filename}")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, output_path.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
            context = ProjectContext(target)
            await context.init_structure()
            if name:
                metadata = await read_project_metadata(context)
                metadata["name"] = name
                project_info = project_info_from_metadata(metadata, target.name)
                project_info["name"] = name
                metadata["project"] = project_info
                await context.write_yaml("project.yaml", metadata)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

    return {**project_summary_from_path(target), "id": project_id}


@router.get("/export")
async def export_project(project_path: str = Query(...)) -> Response:
    root = settings.project_path(project_path=project_path)
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail="project not found")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(part in EXPORT_EXCLUDED_ROOTS for part in relative.parts):
                continue
            archive.write(path, relative.as_posix())
    filename = f"{slugify_project_name(root.name)}.aisync.zip"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return Response(buffer.getvalue(), media_type="application/zip", headers=headers)


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
    files = [path.replace("\\", "/") for path in await context.list_files()]
    return {"files": sorted(path for path in files if is_safe_project_file(path))}


@router.get("/files/{file_path:path}")
async def read_project_file(file_path: str, project_path: str = Query(...)) -> dict[str, str]:
    context = project_context(project_path=project_path)
    normalized_path = normalize_project_relative_path(file_path)
    if not await context.exists(normalized_path):
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": normalized_path, "content": await context.read_text(normalized_path)}


@router.put("/files/{file_path:path}")
async def write_project_file(
    file_path: str,
    request: FileWriteRequest,
    project_path: str | None = Query(default=None),
) -> dict[str, str]:
    context = project_context(project_path=project_path or request.project_path)
    normalized_path = normalize_project_relative_path(file_path)
    await context.write_text(normalized_path, request.content)
    return {"path": normalized_path, "status": "written"}


@router.post("/files/move")
async def move_project_file(request: FileMoveRequest) -> dict[str, str]:
    context = project_context(project_path=request.project_path)
    old_path = normalize_temp_path(request.old_path)
    new_path = normalize_temp_path(request.new_path)
    if old_path == new_path:
        raise HTTPException(status_code=400, detail="new_path must be different from old_path")
    try:
        await context.move_file(old_path, new_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="source file not found") from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="target file already exists") from exc
    return {"old_path": old_path, "path": new_path, "status": "moved"}


@router.delete("/files/{file_path:path}")
async def delete_project_file(file_path: str, project_path: str = Query(...)) -> dict[str, str]:
    context = project_context(project_path=project_path)
    normalized_path = normalize_temp_path(file_path)
    try:
        await context.delete_file(normalized_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    return {"path": normalized_path, "status": "deleted"}


@router.delete("/directories/{directory_path:path}")
async def delete_project_directory(directory_path: str, project_path: str = Query(...)) -> dict[str, Any]:
    context = project_context(project_path=project_path)
    normalized_dir = normalize_project_directory_path(directory_path)
    if normalized_dir == "temp":
        raise HTTPException(status_code=400, detail="temp root is protected")
    directory = context.resolve_path(normalized_dir)
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")

    candidates: list[str] = []
    for raw_path in await context.list_files(normalized_dir):
        path = raw_path.replace("\\", "/")
        if path == "temp/.aisync-temp.json":
            continue
        if not is_safe_project_file(path):
            raise HTTPException(status_code=400, detail=f"directory contains unsupported file: {path}")
        candidates.append(normalize_project_relative_path(path))

    deleted: list[str] = []
    for normalized_path in candidates:
        try:
            await context.delete_file(normalized_path)
        except FileNotFoundError:
            continue
        deleted.append(normalized_path)
    await asyncio.to_thread(shutil.rmtree, directory)
    return {"path": normalized_dir, "status": "deleted", "files": deleted}


@router.get("/{project_id}/files")
async def list_project_files_by_id(project_id: str) -> dict[str, list[str]]:
    context = project_context(project_id=project_id)
    files = [path.replace("\\", "/") for path in await context.list_files()]
    return {"files": sorted(path for path in files if is_safe_project_file(path))}


@router.get("/{project_id}/files/{file_path:path}")
async def read_project_file_by_id(project_id: str, file_path: str) -> dict[str, str]:
    context = project_context(project_id=project_id)
    normalized_path = normalize_project_relative_path(file_path)
    if not await context.exists(normalized_path):
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": normalized_path, "content": await context.read_text(normalized_path)}


@router.put("/{project_id}/files/{file_path:path}")
async def write_project_file_by_id(project_id: str, file_path: str, request: FileWriteRequest) -> dict[str, str]:
    context = project_context(project_id=project_id)
    normalized_path = normalize_project_relative_path(file_path)
    await context.write_text(normalized_path, request.content)
    return {"path": normalized_path, "status": "written"}
