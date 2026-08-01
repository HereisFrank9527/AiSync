from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.projects.characters import (
    CharacterConflictError,
    archive_character,
    list_character_archives,
    list_characters,
    migrate_character_registry,
    normalize_character_ids,
    resolve_character_references,
    restore_character,
    save_character,
    validate_character_ids,
)
from app.projects.context import ProjectContext
from app.projects.foreshadows import FORESHADOW_PATH, confirm_foreshadow_verification
from app.projects.outline import (
    OUTLINE_INDEX_PATH,
    OUTLINE_MARKDOWN_PATH,
    refresh_outline_index,
    snapshot_outline_markdown,
)

router = APIRouter(prefix="/story", tags=["story"])


class OutlineItem(BaseModel):
    id: str | None = None
    index: int | None = None
    title: str = ""
    summary: str = ""
    status: str = "planned"
    character_ids: list[str] = Field(default_factory=list)


class OutlineSaveRequest(BaseModel):
    project_path: str | None = None
    title: str = "大纲"
    items: list[OutlineItem] = Field(default_factory=list)


class OutlineImportRequest(BaseModel):
    project_path: str | None = None


class OutlineSourceSaveRequest(BaseModel):
    project_path: str | None = None
    content: str


class OutlineCharacterLinksSaveRequest(BaseModel):
    project_path: str | None = None
    node_id: str
    character_ids: list[str] = Field(default_factory=list)


class WorldviewDocumentSaveRequest(BaseModel):
    project_path: str | None = None
    path: str
    content: str


class WorldviewDocumentRenameRequest(BaseModel):
    project_path: str | None = None
    old_path: str
    new_path: str


class WorldviewDocumentDeleteRequest(BaseModel):
    project_path: str | None = None
    path: str


class CharacterArchiveRequest(BaseModel):
    project_path: str | None = None
    slug: str
    reason: str = ""


class CharacterSaveRequest(BaseModel):
    project_path: str | None = None
    slug: str
    name: str
    role: str = ""
    summary: str = ""
    profile: str = ""
    aliases: list[str] = Field(default_factory=list)
    status: str = "active"
    faction: str = ""
    tags: list[str] = Field(default_factory=list)
    first_appearance: str = ""


class CharacterRestoreRequest(BaseModel):
    project_path: str | None = None
    archive_id: str


class CharacterResolveRequest(BaseModel):
    project_path: str | None = None
    names: list[str] = Field(default_factory=list)


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
    outline_id: str = ""
    character_ids: list[str] = Field(default_factory=list)


class ForeshadowItem(BaseModel):
    id: str | None = None
    title: str = ""
    summary: str = ""
    status: str = "planned"
    importance: str = "medium"
    plant_chapter: str = ""
    payoff_chapter: str = ""
    character_ids: list[str] = Field(default_factory=list)
    outline_ids: list[str] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    verification: dict[str, Any] | None = None


class ForeshadowSaveRequest(BaseModel):
    project_path: str | None = None
    items: list[ForeshadowItem] = Field(default_factory=list)


class ForeshadowVerificationRequest(BaseModel):
    project_path: str | None = None
    foreshadow_id: str
    note: str = ""


OUTLINE_STATUSES = {"planned", "draft", "revising", "done"}
FORESHADOW_STATUSES = {"planned", "planted", "developing", "paid_off", "abandoned"}
FORESHADOW_IMPORTANCE = {"minor", "medium", "major"}
OUTLINE_CHARACTER_LINKS_PATH = "plot/outline-meta.yaml"


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
        if item.status and item.status != "planned":
            lines.extend(["", f"> 状态：{item.status}"])
        if summary:
            lines.extend(["", summary])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def safe_outline_id(value: str, position: int) -> str:
    normalized = "".join(char if char.isalnum() or char in "-_" else "-" for char in value.strip())
    normalized = "-".join(part for part in normalized.split("-") if part)
    return normalized[:80] or f"outline-{position}"


def safe_item_id(prefix: str, value: str, position: int) -> str:
    normalized = "".join(char if char.isalnum() or char in "-_" else "-" for char in value.strip())
    normalized = "-".join(part for part in normalized.split("-") if part)
    return normalized[:80] or f"{prefix}-{position}"


def normalize_outline_status(value: Any) -> str:
    status = str(value or "planned").strip()
    return status if status in OUTLINE_STATUSES else "planned"


def normalize_outline_items(items: list[OutlineItem]) -> list[dict[str, Any]]:
    normalized_items: list[dict[str, Any]] = []
    for position, item in enumerate(items, start=1):
        title = item.title.strip()
        summary = item.summary.strip()
        if not title and not summary:
            continue
        normalized_items.append({
            "id": safe_outline_id(item.id or f"outline-{position}", position),
            "index": position,
            "title": title or f"节点 {position}",
            "summary": summary,
            "status": normalize_outline_status(item.status),
            "character_ids": normalize_character_ids(item.character_ids),
        })
    return normalized_items


def normalize_string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def normalize_worldview_path(path: str) -> str:
    normalized = PurePosixPath(path.strip().replace("\\", "/")).as_posix()
    parts = PurePosixPath(normalized).parts
    if (
        not normalized.startswith("world/")
        or not normalized.endswith(".md")
        or ".." in parts
        or len(parts) < 2
    ):
        raise HTTPException(status_code=400, detail="path must be a markdown file under world/")
    return normalized


def normalize_foreshadow_status(value: Any) -> str:
    status = str(value or "planned").strip()
    return status if status in FORESHADOW_STATUSES else "planned"


def normalize_foreshadow_importance(value: Any) -> str:
    importance = str(value or "medium").strip()
    return importance if importance in FORESHADOW_IMPORTANCE else "medium"


def normalize_foreshadow_items(items: list[ForeshadowItem]) -> list[dict[str, Any]]:
    normalized_items: list[dict[str, Any]] = []
    for position, item in enumerate(items, start=1):
        title = item.title.strip()
        summary = item.summary.strip()
        notes = item.notes.strip()
        if not title and not summary and not notes:
            continue
        normalized = {
            "id": safe_item_id("foreshadow", item.id or f"foreshadow-{position}", position),
            "title": title or f"伏笔 {position}",
            "summary": summary,
            "status": normalize_foreshadow_status(item.status),
            "importance": normalize_foreshadow_importance(item.importance),
            "plant_chapter": item.plant_chapter.strip(),
            "payoff_chapter": item.payoff_chapter.strip(),
            "character_ids": normalize_character_ids(item.character_ids),
            "outline_ids": normalize_string_list(item.outline_ids),
            "related_files": normalize_string_list(item.related_files),
            "tags": normalize_string_list(item.tags),
            "notes": notes,
        }
        if item.verification:
            normalized["verification"] = dict(item.verification)
        normalized_items.append(normalized)
    return normalized_items


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
        "outline_id": str(metadata.get("outline_id") or ""),
        "character_ids": normalize_character_ids(metadata.get("character_ids")),
    }


async def read_outline_character_links(context: ProjectContext) -> dict[str, list[str]]:
    if not await context.exists(OUTLINE_CHARACTER_LINKS_PATH):
        return {}
    try:
        data = await context.read_yaml(OUTLINE_CHARACTER_LINKS_PATH) or {}
    except Exception:
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
        return {}
    return {
        str(node_id): normalize_character_ids(value.get("character_ids") if isinstance(value, dict) else value)
        for node_id, value in data["nodes"].items()
        if str(node_id).strip()
    }


async def write_outline_character_links(context: ProjectContext, links: dict[str, list[str]]) -> None:
    data = {
        "schema_version": 1,
        "nodes": {
            node_id: {"character_ids": normalize_character_ids(character_ids)}
            for node_id, character_ids in sorted(links.items())
            if normalize_character_ids(character_ids)
        },
    }
    await context.write_yaml(OUTLINE_CHARACTER_LINKS_PATH, data)


def attach_outline_character_links(data: dict[str, Any], links: dict[str, list[str]]) -> dict[str, Any]:
    attached = dict(data)
    for key in ("items", "nodes", "chapters"):
        raw_items = data.get(key)
        if not isinstance(raw_items, list):
            continue
        attached[key] = [
            {
                **item,
                "character_ids": links.get(str(item.get("id") or ""), []),
            }
            if isinstance(item, dict)
            else item
            for item in raw_items
        ]
    return attached


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
    json_path = OUTLINE_INDEX_PATH
    md_path = OUTLINE_MARKDOWN_PATH

    if await context.exists(md_path):
        content = await context.read_text(md_path)
        data = attach_outline_character_links(
            await refresh_outline_index(context),
            await read_outline_character_links(context),
        )
        return {
            "source": json_path,
            "format": "hybrid",
            "title": data.get("title") or "大纲",
            "items": data.get("items") or [],
            "nodes": data.get("nodes") or [],
            "content": content,
            "content_source": md_path,
            "source_hash": data.get("source_hash"),
            "raw": data,
        }

    if await context.exists(json_path):
        data = await context.read_json(json_path)
        if isinstance(data, dict):
            data = attach_outline_character_links(data, await read_outline_character_links(context))
            return {
                "source": json_path,
                "format": "json",
                "title": data.get("title") or "大纲",
                "items": data.get("chapters") or data.get("items") or [],
                "nodes": data.get("nodes") or [],
                "content": "",
                "content_source": None,
                "raw": data,
            }
        if isinstance(data, list):
            return {
                "source": json_path,
                "format": "json",
                "title": "大纲",
                "items": data,
                "nodes": [],
                "content": "",
                "content_source": None,
                "raw": data,
            }

    return {"source": None, "format": "empty", "title": "大纲", "items": [], "content": ""}


@router.put("/outline")
async def save_outline(request: OutlineSaveRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    try:
        for item in request.items:
            item.character_ids = await validate_character_ids(context, item.character_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if await context.exists(OUTLINE_MARKDOWN_PATH):
        current_index = await refresh_outline_index(context)
        if any(str(node.get("kind") or "") != "chapter" for node in current_index.get("nodes") or []):
            raise HTTPException(
                status_code=409,
                detail="自由格式大纲不能使用扁平节点保存，请改用 Markdown 原文编辑。",
            )
    normalized_items = normalize_outline_items(request.items)
    snapshot_path = await snapshot_outline_markdown(context, reason="structured-save")

    await context.write_text(
        OUTLINE_MARKDOWN_PATH,
        outline_to_markdown(
            request.title.strip() or "大纲",
            [OutlineItem.model_validate(item) for item in normalized_items],
        ),
    )
    data = await refresh_outline_index(context)
    refreshed_items = data.get("items") or []
    links = await read_outline_character_links(context)
    for index, item in enumerate(normalized_items):
        if index >= len(refreshed_items) or not isinstance(refreshed_items[index], dict):
            continue
        node_id = str(refreshed_items[index].get("id") or "")
        if node_id:
            links[node_id] = normalize_character_ids(item.get("character_ids"))
    await write_outline_character_links(context, links)
    data = attach_outline_character_links(data, links)
    content = await context.read_text(OUTLINE_MARKDOWN_PATH)
    return {
        "source": OUTLINE_INDEX_PATH,
        "format": "hybrid",
        "title": data["title"],
        "items": data.get("items") or [],
        "nodes": data.get("nodes") or [],
        "content": content,
        "content_source": OUTLINE_MARKDOWN_PATH,
        "source_hash": data.get("source_hash"),
        "snapshot_path": snapshot_path,
    }


@router.post("/outline/import-markdown")
async def import_outline_from_markdown(request: OutlineImportRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    md_path = OUTLINE_MARKDOWN_PATH
    if not await context.exists(md_path):
        raise HTTPException(status_code=404, detail="plot/outline.md not found")
    content = await context.read_text(md_path)
    data = attach_outline_character_links(
        await refresh_outline_index(context),
        await read_outline_character_links(context),
    )
    return {
        "source": OUTLINE_INDEX_PATH,
        "format": "hybrid",
        "title": data["title"],
        "items": data.get("items") or [],
        "nodes": data.get("nodes") or [],
        "content": content,
        "content_source": md_path,
        "source_hash": data.get("source_hash"),
        "raw_markdown_preserved": True,
    }


@router.put("/outline/source")
async def save_outline_source(request: OutlineSourceSaveRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    content = request.content.rstrip() + "\n"
    if not content.strip():
        raise HTTPException(status_code=400, detail="大纲原文不能为空")
    snapshot_path = await snapshot_outline_markdown(context, reason="source-save")
    await context.write_text(OUTLINE_MARKDOWN_PATH, content)
    data = attach_outline_character_links(
        await refresh_outline_index(context),
        await read_outline_character_links(context),
    )
    return {
        "source": OUTLINE_INDEX_PATH,
        "format": "hybrid",
        "title": data["title"],
        "items": data.get("items") or [],
        "nodes": data.get("nodes") or [],
        "content": content,
        "content_source": OUTLINE_MARKDOWN_PATH,
        "source_hash": data.get("source_hash"),
        "snapshot_path": snapshot_path,
    }


@router.put("/outline/characters")
async def save_outline_character_links(request: OutlineCharacterLinksSaveRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    node_id = request.node_id.strip()
    if not node_id:
        raise HTTPException(status_code=400, detail="node_id is required")
    data = await refresh_outline_index(context)
    known_node_ids = {
        str(item.get("id") or "")
        for item in [*(data.get("items") or []), *(data.get("nodes") or [])]
        if isinstance(item, dict) and item.get("id")
    }
    if node_id not in known_node_ids:
        raise HTTPException(status_code=404, detail="outline node not found")
    try:
        character_ids = await validate_character_ids(context, request.character_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    links = await read_outline_character_links(context)
    if character_ids:
        links[node_id] = character_ids
    else:
        links.pop(node_id, None)
    await write_outline_character_links(context, links)
    return {"node_id": node_id, "character_ids": character_ids, "source": OUTLINE_CHARACTER_LINKS_PATH}


@router.get("/characters")
async def get_characters(project_path: str = Query(...)) -> dict[str, Any]:
    context = project_context(project_path)
    migration = await migrate_character_registry(context)
    characters, warnings = await list_characters(context)
    archives = await list_character_archives(context)
    return {
        "source": "characters",
        "items": characters,
        "archives": archives,
        "warnings": [*migration.get("warnings", []), *warnings],
        "migration": migration,
    }


@router.post("/characters/resolve")
async def resolve_characters(request: CharacterResolveRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    return await resolve_character_references(context, request.names)


@router.put("/characters")
async def save_character_endpoint(request: CharacterSaveRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    try:
        return await save_character(
            context,
            slug=request.slug,
            name=request.name,
            role=request.role,
            summary=request.summary,
            profile=request.profile,
            aliases=request.aliases,
            status=request.status,
            faction=request.faction,
            tags=request.tags,
            first_appearance=request.first_appearance,
        )
    except CharacterConflictError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "conflicts": exc.conflicts}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="character not found") from exc


@router.post("/characters/archive")
async def archive_character_endpoint(request: CharacterArchiveRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    try:
        return await archive_character(context, request.slug, request.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="character not found") from exc


@router.post("/characters/restore")
async def restore_character_endpoint(request: CharacterRestoreRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    try:
        return await restore_character(context, request.archive_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="character archive not found") from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"恢复目标已存在：{exc}") from exc


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
    path = normalize_worldview_path(request.path)

    await context.write_text(path, request.content)
    return {
        "path": path,
        "title": title_from_markdown(path, request.content),
        "content": request.content,
    }


@router.post("/worldview/document/rename")
async def rename_worldview_document(request: WorldviewDocumentRenameRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    old_path = normalize_worldview_path(request.old_path)
    new_path = normalize_worldview_path(request.new_path)
    if old_path == new_path:
        raise HTTPException(status_code=400, detail="new_path must be different from old_path")

    try:
        await context.move_file(old_path, new_path)
        content = await context.read_text(new_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="source worldview document not found") from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="target worldview document already exists") from exc

    return {
        "old_path": old_path,
        "path": new_path,
        "title": title_from_markdown(new_path, content),
        "content": content,
    }


@router.post("/worldview/document/delete")
async def delete_worldview_document(request: WorldviewDocumentDeleteRequest) -> dict[str, str]:
    context = project_context(request.project_path)
    path = normalize_worldview_path(request.path)
    try:
        await context.delete_file(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="worldview document not found") from exc
    return {"path": path, "status": "deleted"}


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
            "outline_id": metadata["outline_id"],
            "character_ids": metadata["character_ids"],
        })

    chapters.sort(key=lambda item: item["path"])
    return {
        "source": "chapters",
        "items": chapters,
        "total_characters": sum(int(item["characters"]) for item in chapters),
    }


@router.get("/foreshadows")
async def get_foreshadows(project_path: str = Query(...)) -> dict[str, Any]:
    context = project_context(project_path)
    path = "plot/foreshadows.json"
    if not await context.exists(path):
        return {"source": path, "items": [], "stats": {"total": 0, "paid_off": 0, "open": 0}}
    try:
        data = await context.read_json(path)
    except Exception:
        return {"source": path, "items": [], "stats": {"total": 0, "paid_off": 0, "open": 0}}

    raw_items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(raw_items, list):
        raw_items = []
    items = normalize_foreshadow_items([ForeshadowItem.model_validate(item) for item in raw_items if isinstance(item, dict)])
    paid_off = sum(1 for item in items if item["status"] == "paid_off")
    return {
        "source": path,
        "items": items,
        "stats": {
            "total": len(items),
            "paid_off": paid_off,
            "open": len(items) - paid_off,
        },
    }


@router.put("/foreshadows")
async def save_foreshadows(request: ForeshadowSaveRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    path = "plot/foreshadows.json"
    try:
        for item in request.items:
            item.character_ids = await validate_character_ids(context, item.character_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = normalize_foreshadow_items(request.items)
    data = {"items": items}
    await context.write_json(path, data)
    paid_off = sum(1 for item in items if item["status"] == "paid_off")
    return {
        "source": path,
        "items": items,
        "stats": {
            "total": len(items),
            "paid_off": paid_off,
            "open": len(items) - paid_off,
        },
    }


@router.post("/foreshadows/verification/confirm")
async def confirm_foreshadow_verification_endpoint(request: ForeshadowVerificationRequest) -> dict[str, Any]:
    context = project_context(request.project_path)
    try:
        items = await confirm_foreshadow_verification(context, request.foreshadow_id, request.note)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    paid_off = sum(1 for item in items if item["status"] == "paid_off")
    return {
        "source": FORESHADOW_PATH,
        "items": items,
        "stats": {
            "total": len(items),
            "paid_off": paid_off,
            "open": len(items) - paid_off,
        },
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

    try:
        character_ids = await validate_character_ids(context, request.character_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metadata = normalize_chapter_metadata(
        {
            "status": request.status.strip() or "draft",
            "summary": request.summary.strip(),
            "target_characters": request.target_characters,
            "revision": request.revision,
            "outline_id": request.outline_id.strip(),
            "character_ids": character_ids,
        },
        "",
    )
    await write_chapter_metadata(context, path, metadata)
    return {"path": path, **metadata}
