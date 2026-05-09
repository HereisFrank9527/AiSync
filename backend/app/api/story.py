from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.projects.context import ProjectContext
from app.projects.outline import outline_items_from_markdown

router = APIRouter(prefix="/story", tags=["story"])


class OutlineItem(BaseModel):
    index: int | None = None
    title: str = ""
    summary: str = ""


class OutlineSaveRequest(BaseModel):
    project_path: str | None = None
    title: str = "大纲"
    items: list[OutlineItem] = Field(default_factory=list)


class WorldviewDocumentSaveRequest(BaseModel):
    project_path: str | None = None
    path: str
    content: str


class ChapterSaveRequest(BaseModel):
    project_path: str | None = None
    path: str
    content: str


class ChapterMetadataSaveRequest(BaseModel):
    project_path: str | None = None
    path: str
    status: str = "draft"
    summary: str = ""
    target_characters: int = 0
    revision: int = 0


def project_context(project_path: str | None) -> ProjectContext:
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path is required")
    return ProjectContext(settings.project_path(project_path=project_path))


def outline_to_markdown(title: str, items: list[OutlineItem]) -> str:
    lines = [f"# {title or '大纲'}", ""]
    for position, item in enumerate(items, start=1):
        index = item.index or position
        heading = item.title.strip() or f"节点 {index}"
        lines.append(f"## 第 {index} 章：{heading}")
        summary = item.summary.strip()
        if summary:
            lines.extend(["", summary])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def title_from_markdown(path: str, content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or path.rsplit("/", 1)[-1]
    return path.rsplit("/", 1)[-1].removesuffix(".md")


def text_length(content: str) -> int:
    return len("".join(line.strip() for line in content.splitlines() if not line.lstrip().startswith("#")))


def markdown_excerpt(content: str, limit: int = 160) -> str:
    lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    text = " ".join(lines)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def chapter_meta_paths(chapter_path: str) -> tuple[str, str]:
    directory, filename = chapter_path.rsplit("/", 1)
    slug = filename.removesuffix(".md")
    return f"{directory}/ch-meta.yaml", slug


async def read_chapter_metadata(context: ProjectContext, chapter_path: str) -> dict[str, Any]:
    metadata_path, slug = chapter_meta_paths(chapter_path)
    if not await context.exists(metadata_path):
        return {}
    try:
        data = await context.read_yaml(metadata_path) or {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    chapters = data.get("chapters")
    if isinstance(chapters, dict) and isinstance(chapters.get(slug), dict):
        return chapters[slug]
    legacy = data.get(slug)
    return legacy if isinstance(legacy, dict) else {}


def normalize_chapter_metadata(metadata: dict[str, Any], fallback_summary: str) -> dict[str, Any]:
    def int_value(value: Any) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

    return {
        "status": str(metadata.get("status") or "draft"),
        "summary": str(metadata.get("summary") or fallback_summary),
        "target_characters": int_value(metadata.get("target_characters")),
        "revision": int_value(metadata.get("revision")),
    }


async def write_chapter_metadata(
    context: ProjectContext,
    chapter_path: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    metadata_path, slug = chapter_meta_paths(chapter_path)
    data: dict[str, Any] = {}
    if await context.exists(metadata_path):
        try:
            loaded = await context.read_yaml(metadata_path) or {}
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    chapters = data.get("chapters")
    if not isinstance(chapters, dict):
        chapters = {}
    chapters[slug] = metadata
    data["chapters"] = chapters
    await context.write_yaml(metadata_path, data)
    return metadata


@router.get("/outline")
async def get_outline(project_path: str = Query(...)) -> dict[str, Any]:
    context = project_context(project_path)
    json_path = "plot/outline.json"
    md_path = "plot/outline.md"

    if await context.exists(json_path):
        data = await context.read_json(json_path)
        if isinstance(data, dict):
            return {
                "source": json_path,
                "format": "json",
                "title": data.get("title") or "大纲",
                "items": data.get("chapters") or data.get("items") or [],
                "raw": data,
            }
        if isinstance(data, list):
            return {"source": json_path, "format": "json", "title": "大纲", "items": data, "raw": data}

    if await context.exists(md_path):
        content = await context.read_text(md_path)
        return {
            "source": md_path,
            "format": "markdown",
            "title": "大纲",
            "items": outline_items_from_markdown(content),
            "content": content,
        }

    return {"source": None, "format": "empty", "title": "大纲", "items": [], "content": ""}


@router.put("/outline")
async def save_outline(request: OutlineSaveRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    normalized_items: list[dict[str, Any]] = []
    for position, item in enumerate(request.items, start=1):
        title = item.title.strip()
        summary = item.summary.strip()
        if not title and not summary:
            continue
        normalized_items.append({
            "index": item.index or position,
            "title": title or f"节点 {position}",
            "summary": summary,
        })

    data = {
        "title": request.title.strip() or "大纲",
        "items": normalized_items,
    }
    await context.write_json("plot/outline.json", data)
    await context.write_text(
        "plot/outline.md",
        outline_to_markdown(
            data["title"],
            [OutlineItem.model_validate(item) for item in normalized_items],
        ),
    )
    return {"source": "plot/outline.json", "format": "json", "title": data["title"], "items": normalized_items}


@router.get("/characters")
async def get_characters(project_path: str = Query(...)) -> dict[str, Any]:
    context = project_context(project_path)
    files = await context.list_files("characters")
    characters: list[dict[str, Any]] = []

    for path in files:
        if not path.endswith("profile.yaml"):
            continue
        try:
            metadata = await context.read_yaml(path) or {}
        except Exception:
            continue
        if not isinstance(metadata, dict):
            continue

        base_path = path.rsplit("/", 1)[0]
        profile_path = f"{base_path}/profile.md"
        profile = ""
        if await context.exists(profile_path):
            try:
                profile = await context.read_text(profile_path)
            except Exception:
                profile = ""

        characters.append({
            "slug": str(metadata.get("slug") or base_path.split("/")[-1]),
            "name": str(metadata.get("name") or metadata.get("slug") or base_path.split("/")[-1]),
            "role": str(metadata.get("role") or ""),
            "summary": str(metadata.get("summary") or ""),
            "profile": profile,
            "profile_path": profile_path,
            "metadata_path": path,
        })

    characters.sort(key=lambda item: item["name"])
    return {"source": "characters", "items": characters}


@router.get("/worldview")
async def get_worldview(project_path: str = Query(...)) -> dict[str, Any]:
    context = project_context(project_path)
    files = await context.list_files("world")
    documents: list[dict[str, Any]] = []

    for path in files:
        normalized_path = path.replace("\\", "/")
        if not normalized_path.endswith(".md"):
            continue
        try:
            content = await context.read_text(normalized_path)
        except Exception:
            continue
        documents.append({
            "path": normalized_path,
            "title": title_from_markdown(normalized_path, content),
            "content": content,
            "summary": content.strip().splitlines()[0] if content.strip() else "",
        })

    documents.sort(key=lambda item: item["path"])
    return {"source": "world", "items": documents}


@router.put("/worldview/document")
async def save_worldview_document(request: WorldviewDocumentSaveRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    path = request.path.strip().replace("\\", "/")
    if not path.startswith("world/") or not path.endswith(".md") or ".." in path:
        raise HTTPException(status_code=400, detail="path must be a markdown file under world/")

    await context.write_text(path, request.content)
    return {
        "path": path,
        "title": title_from_markdown(path, request.content),
        "content": request.content,
    }


@router.get("/chapters")
async def get_chapters(project_path: str = Query(...)) -> dict[str, Any]:
    context = project_context(project_path)
    files = await context.list_files("chapters")
    chapters: list[dict[str, Any]] = []

    for path in files:
        normalized_path = path.replace("\\", "/")
        if not normalized_path.endswith(".md"):
            continue
        try:
            content = await context.read_text(normalized_path)
        except Exception:
            content = ""
        fallback_summary = markdown_excerpt(content)
        metadata = normalize_chapter_metadata(
            await read_chapter_metadata(context, normalized_path),
            fallback_summary,
        )
        chapters.append({
            "path": normalized_path,
            "title": title_from_markdown(normalized_path, content),
            "content": content,
            "summary": metadata["summary"],
            "characters": text_length(content),
            "status": metadata["status"],
            "target_characters": metadata["target_characters"],
            "revision": metadata["revision"],
        })

    chapters.sort(key=lambda item: item["path"])
    return {
        "source": "chapters",
        "items": chapters,
        "total_characters": sum(int(item["characters"]) for item in chapters),
    }


@router.put("/chapters/document")
async def save_chapter_document(request: ChapterSaveRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    path = request.path.strip().replace("\\", "/")
    if not path.startswith("chapters/") or not path.endswith(".md") or ".." in path:
        raise HTTPException(status_code=400, detail="path must be a markdown file under chapters/")

    await context.write_text(path, request.content)
    return {
        "path": path,
        "title": title_from_markdown(path, request.content),
        "content": request.content,
        "summary": markdown_excerpt(request.content),
        "characters": text_length(request.content),
    }


@router.put("/chapters/metadata")
async def save_chapter_metadata(request: ChapterMetadataSaveRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    path = request.path.strip().replace("\\", "/")
    if not path.startswith("chapters/") or not path.endswith(".md") or ".." in path:
        raise HTTPException(status_code=400, detail="path must be a markdown file under chapters/")

    metadata = normalize_chapter_metadata(
        {
            "status": request.status.strip() or "draft",
            "summary": request.summary.strip(),
            "target_characters": request.target_characters,
            "revision": request.revision,
        },
        "",
    )
    await write_chapter_metadata(context, path, metadata)
    return {"path": path, **metadata}
