from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from app.projects.context import ProjectContext

CHARACTER_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")
CHARACTER_ARCHIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+-\d{14}$")
CHARACTER_ID_RE = re.compile(r"^char_[0-9a-f]{20}$")
CHARACTER_STATUSES = {"active", "inactive", "missing", "deceased", "retired", "unknown"}
CHARACTER_SCHEMA_VERSION = 3
CHARACTER_INDEX_PATH = "characters/index.yaml"
CHARACTER_MIGRATION_REPORT_PATH = ".aisync/character_migration.json"
CHARACTER_MANAGED_FIELDS = {
    "schema_version",
    "character_id",
    "slug",
    "name",
    "role",
    "summary",
    "aliases",
    "status",
    "faction",
    "tags",
    "first_appearance",
}


class CharacterConflictError(ValueError):
    def __init__(self, conflicts: list[dict[str, str]]) -> None:
        self.conflicts = conflicts
        names = "、".join(item["name"] for item in conflicts)
        super().__init__(f"角色姓名或别名与已有角色重复：{names}")


def normalize_character_slug(slug: str) -> str:
    value = slug.strip().strip("/").replace("\\", "/")
    if not value or "/" in value or ".." in value or not CHARACTER_SLUG_RE.fullmatch(value):
        raise ValueError("角色标识只能包含英文字母、数字、连字符和下划线")
    return value


def normalize_character_archive_id(archive_id: str) -> str:
    value = archive_id.strip().strip("/").replace("\\", "/")
    if "/" in value or not CHARACTER_ARCHIVE_ID_RE.fullmatch(value):
        raise ValueError("无效的角色归档标识")
    return value


def normalize_character_status(value: Any) -> str:
    status = str(value or "active").strip().lower()
    return status if status in CHARACTER_STATUSES else "unknown"


def normalize_character_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return normalized


def normalize_character_identity(value: str) -> str:
    return re.sub(r"[\s·•._-]+", "", value).casefold()


def normalize_character_schema_version(value: Any) -> int:
    try:
        version = int(value or 1)
    except (TypeError, ValueError):
        return 1
    return version if version > 0 else 1


def normalize_character_id(value: Any) -> str:
    character_id = str(value or "").strip().lower()
    return character_id if CHARACTER_ID_RE.fullmatch(character_id) else ""


def normalize_character_ids(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        character_id = normalize_character_id(value)
        if not character_id or character_id in seen:
            continue
        seen.add(character_id)
        normalized.append(character_id)
    return normalized


def new_character_id() -> str:
    return f"char_{uuid.uuid4().hex[:20]}"


def legacy_character_id(base_path: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, f"aisync:{base_path}").hex[:20]
    return f"char_{value}"


def profile_name(profile: str, fallback: str) -> str:
    for line in profile.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            name = stripped.lstrip("#").strip()
            if name:
                return name
    return fallback


def character_record(metadata: dict[str, Any], base_path: str, profile: str) -> dict[str, Any]:
    slug = str(metadata.get("slug") or base_path.split("/")[-1])
    return {
        "schema_version": normalize_character_schema_version(metadata.get("schema_version")),
        "character_id": normalize_character_id(metadata.get("character_id")),
        "slug": slug,
        "name": str(metadata.get("name") or slug),
        "role": str(metadata.get("role") or ""),
        "summary": str(metadata.get("summary") or ""),
        "aliases": normalize_character_list(metadata.get("aliases")),
        "status": normalize_character_status(metadata.get("status")),
        "faction": str(metadata.get("faction") or ""),
        "tags": normalize_character_list(metadata.get("tags")),
        "first_appearance": str(metadata.get("first_appearance") or ""),
        "profile": profile,
        "profile_path": f"{base_path}/profile.md",
        "metadata_path": f"{base_path}/profile.yaml",
    }


def character_base_paths(files: list[str]) -> list[str]:
    bases: set[str] = set()
    for path in files:
        normalized = path.replace("\\", "/")
        if not normalized.endswith(("/profile.yaml", "/profile.md")):
            continue
        base_path = normalized.rsplit("/", 1)[0]
        parts = PurePosixPath(base_path).parts
        is_active = len(parts) == 2 and parts[0] == "characters" and CHARACTER_SLUG_RE.fullmatch(parts[1])
        is_archive = (
            len(parts) == 4
            and parts[:3] == ("temp", "archive", "characters")
            and CHARACTER_ARCHIVE_ID_RE.fullmatch(parts[3])
        )
        if is_active or is_archive:
            bases.add(base_path)
    return sorted(bases)


async def refresh_character_index(context: ProjectContext) -> dict[str, Any]:
    characters, _ = await list_characters(context)
    archives = await list_character_archives(context)
    data = {
        "schema_version": 1,
        "characters": [
            {
                "character_id": item["character_id"],
                "slug": item["slug"],
                "name": item["name"],
                "aliases": item["aliases"],
                "status": item["status"],
                "archived": False,
            }
            for item in characters
            if item["character_id"]
        ] + [
            {
                "character_id": item["character_id"],
                "slug": item["slug"],
                "name": item["name"],
                "aliases": item.get("aliases") or [],
                "status": "archived",
                "archived": True,
                "archive_id": item["archive_id"],
            }
            for item in archives
            if item.get("character_id")
        ],
    }
    existing: Any = None
    if await context.exists(CHARACTER_INDEX_PATH):
        try:
            existing = await context.read_yaml(CHARACTER_INDEX_PATH)
        except Exception:
            existing = None
    if existing != data:
        await context.write_yaml(CHARACTER_INDEX_PATH, data)
    return data


async def migrate_character_registry(context: ProjectContext) -> dict[str, Any]:
    files = [
        *await context.list_files("characters"),
        *await context.list_files("temp/archive/characters"),
    ]
    bases = character_base_paths(files)
    prepared: list[tuple[str, dict[str, Any], bool, str | None]] = []
    warnings: list[dict[str, str]] = []
    seen_ids: dict[str, tuple[str, str]] = {}
    created_metadata = 0

    for base_path in bases:
        base_name = base_path.rsplit("/", 1)[-1]
        slug = base_name if base_path.startswith("characters/") else base_name.rsplit("-", 1)[0]
        metadata_path = f"{base_path}/profile.yaml"
        profile_path = f"{base_path}/profile.md"
        metadata_exists = await context.exists(metadata_path)
        original_content: str | None = None
        metadata: dict[str, Any]
        if metadata_exists:
            try:
                original_content = await context.read_text(metadata_path)
                loaded = await context.read_yaml(metadata_path) or {}
            except Exception as exc:
                warnings.append({"path": metadata_path, "message": f"迁移跳过：YAML 读取失败：{exc}"})
                continue
            if not isinstance(loaded, dict):
                warnings.append({"path": metadata_path, "message": "迁移跳过：角色元数据必须是对象"})
                continue
            metadata = dict(loaded)
        else:
            metadata = {}
            created_metadata += 1

        profile = ""
        if await context.exists(profile_path):
            try:
                profile = await context.read_text(profile_path)
            except Exception as exc:
                warnings.append({"path": profile_path, "message": f"Markdown 读取失败：{exc}"})

        existing_id = normalize_character_id(metadata.get("character_id"))
        character_id = existing_id
        duplicate = seen_ids.get(character_id) if character_id else None
        if not character_id or (duplicate and duplicate[1] != slug):
            character_id = legacy_character_id(base_path)
            if character_id in seen_ids:
                character_id = new_character_id()
            if existing_id in seen_ids:
                warnings.append({
                    "path": metadata_path,
                    "message": f"character_id 与 {seen_ids[existing_id][0]} 重复，已重新分配",
                })
        seen_ids[character_id] = (metadata_path, slug)

        migrated = dict(metadata)
        migrated.update({
            "schema_version": CHARACTER_SCHEMA_VERSION,
            "character_id": character_id,
            "slug": str(metadata.get("slug") or slug),
            "name": str(metadata.get("name") or profile_name(profile, slug)),
        })
        if not metadata_exists:
            migrated.update({
                "role": "",
                "summary": "",
                "aliases": [],
                "status": "active",
                "faction": "",
                "tags": [],
                "first_appearance": "",
            })
        if migrated != metadata:
            prepared.append((metadata_path, migrated, metadata_exists, original_content))

    snapshot_path: str | None = None
    if prepared:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot_path = f".aisync/migration_backups/characters-{timestamp}.json"
        await context.write_json(snapshot_path, {
            "type": "character_registry_migration",
            "schema_version": CHARACTER_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": [
                {
                    "path": path,
                    "existed": existed,
                    "content": content,
                }
                for path, _, existed, content in prepared
            ],
        })
        for path, metadata, _, _ in prepared:
            await context.write_yaml(path, metadata)

    await refresh_character_index(context)

    last_run: dict[str, Any] | None = None
    if prepared:
        last_run = {
            "status": "migrated",
            "schema_version": CHARACTER_SCHEMA_VERSION,
            "changed": len(prepared),
            "created_metadata": created_metadata,
            "snapshot_path": snapshot_path,
            "warnings": warnings,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        await context.write_json(CHARACTER_MIGRATION_REPORT_PATH, last_run)
    elif await context.exists(CHARACTER_MIGRATION_REPORT_PATH):
        try:
            loaded_report = await context.read_json(CHARACTER_MIGRATION_REPORT_PATH)
            if isinstance(loaded_report, dict):
                last_run = loaded_report
        except Exception:
            last_run = None

    return {
        "status": "migrated" if prepared else "current",
        "schema_version": CHARACTER_SCHEMA_VERSION,
        "changed": len(prepared),
        "created_metadata": created_metadata if prepared else 0,
        "snapshot_path": snapshot_path,
        "warnings": warnings,
        "last_run": last_run,
    }


async def resolve_character_references(context: ProjectContext, names: list[str]) -> dict[str, Any]:
    await migrate_character_registry(context)
    characters, _ = await list_characters(context)
    archives = await list_character_archives(context)
    candidates = [
        {**item, "archived": False}
        for item in characters
    ] + [
        {**item, "archived": True, "status": "archived"}
        for item in archives
    ]
    lookup: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        values = [item.get("name"), *(item.get("aliases") or [])]
        for value in values:
            key = normalize_character_identity(str(value or ""))
            if not key:
                continue
            bucket = lookup.setdefault(key, [])
            if not any(existing.get("character_id") == item.get("character_id") for existing in bucket):
                bucket.append(item)

    resolved: list[dict[str, Any]] = []
    unresolved: list[str] = []
    ambiguous: list[dict[str, Any]] = []
    for raw_name in normalize_character_list(names):
        matches = lookup.get(normalize_character_identity(raw_name), [])
        if len(matches) == 1:
            item = matches[0]
            resolved.append({
                "input": raw_name,
                "character_id": item.get("character_id"),
                "name": item.get("name"),
                "slug": item.get("slug"),
                "archived": bool(item.get("archived")),
            })
        elif not matches:
            unresolved.append(raw_name)
        else:
            ambiguous.append({
                "input": raw_name,
                "candidates": [
                    {
                        "character_id": item.get("character_id"),
                        "name": item.get("name"),
                        "slug": item.get("slug"),
                        "archived": bool(item.get("archived")),
                    }
                    for item in matches
                ],
            })
    return {"resolved": resolved, "unresolved": unresolved, "ambiguous": ambiguous}


async def validate_character_ids(context: ProjectContext, values: Any) -> list[str]:
    character_ids = normalize_character_ids(values)
    if not character_ids:
        return []
    await migrate_character_registry(context)
    characters, _ = await list_characters(context)
    archives = await list_character_archives(context)
    known_ids = {
        str(item.get("character_id") or "")
        for item in [*characters, *archives]
        if item.get("character_id")
    }
    unknown = [character_id for character_id in character_ids if character_id not in known_ids]
    if unknown:
        raise ValueError(f"未知人物 ID：{', '.join(unknown)}")
    return character_ids


async def list_characters(context: ProjectContext) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    files = await context.list_files("characters")
    characters: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for base_path in character_base_paths(files):
        normalized_path = f"{base_path}/profile.yaml"
        if not await context.exists(normalized_path):
            continue
        try:
            metadata = await context.read_yaml(normalized_path) or {}
        except Exception as exc:
            warnings.append({"path": normalized_path, "message": f"YAML 读取失败：{exc}"})
            continue
        if not isinstance(metadata, dict):
            warnings.append({"path": normalized_path, "message": "角色元数据必须是对象"})
            continue
        raw_schema_version = metadata.get("schema_version")
        if raw_schema_version not in (None, ""):
            try:
                schema_version = int(raw_schema_version)
            except (TypeError, ValueError):
                schema_version = 0
            if schema_version <= 0:
                warnings.append(
                    {
                        "path": normalized_path,
                        "message": "schema_version 无效，已按版本 1 兼容读取",
                    }
                )
        profile_path = f"{base_path}/profile.md"
        profile = ""
        if await context.exists(profile_path):
            try:
                profile = await context.read_text(profile_path)
            except Exception as exc:
                warnings.append({"path": profile_path, "message": f"Markdown 读取失败：{exc}"})
        characters.append(character_record(metadata, base_path, profile))
    characters.sort(key=lambda item: (item["name"].casefold(), item["slug"]))
    return characters, warnings


async def find_character_conflicts(
    context: ProjectContext,
    *,
    name: str,
    aliases: list[str],
    exclude_slug: str | None = None,
) -> list[dict[str, str]]:
    candidate_values = {normalize_character_identity(value) for value in [name, *aliases] if value.strip()}
    conflicts: list[dict[str, str]] = []
    characters, _ = await list_characters(context)
    for item in characters:
        if exclude_slug and item["slug"] == exclude_slug:
            continue
        existing_values = {
            normalize_character_identity(value)
            for value in [item["name"], *item["aliases"]]
            if str(value).strip()
        }
        matched = sorted(value for value in candidate_values & existing_values if value)
        if matched:
            conflicts.append({"slug": item["slug"], "name": item["name"], "matched": matched[0]})
    return conflicts


async def save_character(
    context: ProjectContext,
    *,
    slug: str,
    name: str,
    role: str = "",
    summary: str = "",
    profile: str = "",
    aliases: list[str] | None = None,
    status: str = "active",
    faction: str = "",
    tags: list[str] | None = None,
    first_appearance: str = "",
    create: bool = False,
) -> dict[str, Any]:
    safe_slug = normalize_character_slug(slug)
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("角色姓名不能为空")
    clean_aliases = normalize_character_list(aliases or [])
    clean_tags = normalize_character_list(tags or [])
    base_path = f"characters/{safe_slug}"
    metadata_path = f"{base_path}/profile.yaml"
    profile_path = f"{base_path}/profile.md"
    exists = await context.exists(metadata_path) or await context.exists(profile_path)
    if create and exists:
        raise FileExistsError(safe_slug)
    if not create and not exists:
        raise FileNotFoundError(safe_slug)

    conflicts = await find_character_conflicts(
        context,
        name=clean_name,
        aliases=clean_aliases,
        exclude_slug=None if create else safe_slug,
    )
    if conflicts:
        raise CharacterConflictError(conflicts)

    existing: dict[str, Any] = {}
    if await context.exists(metadata_path):
        loaded = await context.read_yaml(metadata_path) or {}
        if isinstance(loaded, dict):
            existing = dict(loaded)
    metadata = {
        key: value
        for key, value in existing.items()
        if key not in CHARACTER_MANAGED_FIELDS
    }
    metadata.update(
        {
            "schema_version": CHARACTER_SCHEMA_VERSION,
            "character_id": normalize_character_id(existing.get("character_id")) or new_character_id(),
            "slug": safe_slug,
            "name": clean_name,
            "role": role.strip(),
            "summary": summary.strip(),
            "aliases": clean_aliases,
            "status": normalize_character_status(status),
            "faction": faction.strip(),
            "tags": clean_tags,
            "first_appearance": first_appearance.strip(),
        }
    )
    clean_profile = profile.rstrip() + "\n" if profile.strip() else f"# {clean_name}\n"
    await context.write_yaml(metadata_path, metadata)
    await context.write_text(profile_path, clean_profile)
    await refresh_character_index(context)
    return character_record(metadata, base_path, clean_profile)


def archive_suffix() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


async def archive_character(context: ProjectContext, slug: str, reason: str = "") -> dict[str, Any]:
    await migrate_character_registry(context)
    safe_slug = normalize_character_slug(slug)
    source_dir = f"characters/{safe_slug}"
    files = [
        path.replace("\\", "/")
        for path in await context.list_files(source_dir)
        if path.replace("\\", "/").startswith(f"{source_dir}/")
    ]
    if not files:
        raise FileNotFoundError(source_dir)

    character_id = ""
    metadata_path = f"{source_dir}/profile.yaml"
    if await context.exists(metadata_path):
        try:
            metadata = await context.read_yaml(metadata_path) or {}
            if isinstance(metadata, dict):
                character_id = normalize_character_id(metadata.get("character_id"))
        except Exception:
            character_id = ""

    target_dir = f"temp/archive/characters/{safe_slug}-{archive_suffix()}"
    moved: list[dict[str, str]] = []
    for source in sorted(files):
        relative = PurePosixPath(source).relative_to(source_dir)
        target = f"{target_dir}/{relative.as_posix()}"
        await context.move_file(source, target)
        moved.append({"from": source, "to": target})

    manifest = {
        "type": "character_archive",
        "character_id": character_id,
        "slug": safe_slug,
        "reason": reason.strip(),
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "files": moved,
    }
    await context.write_json(f"{target_dir}/archive.json", manifest)
    await migrate_character_registry(context)
    return {
        "archive_id": target_dir.rsplit("/", 1)[-1],
        "character_id": character_id,
        "slug": safe_slug,
        "status": "archived",
        "archive_path": target_dir,
        "files": moved,
    }


async def list_character_archives(context: ProjectContext) -> list[dict[str, Any]]:
    files = await context.list_files("temp/archive/characters")
    archives: list[dict[str, Any]] = []
    for manifest_path in sorted(files, reverse=True):
        normalized_path = manifest_path.replace("\\", "/")
        if not normalized_path.endswith("/archive.json"):
            continue
        try:
            manifest = await context.read_json(normalized_path)
        except Exception:
            continue
        if not isinstance(manifest, dict) or manifest.get("type") != "character_archive":
            continue
        archive_dir = normalized_path.rsplit("/", 1)[0]
        metadata: dict[str, Any] = {}
        metadata_path = f"{archive_dir}/profile.yaml"
        if await context.exists(metadata_path):
            try:
                loaded = await context.read_yaml(metadata_path) or {}
                if isinstance(loaded, dict):
                    metadata = loaded
            except Exception:
                metadata = {}
        slug = str(manifest.get("slug") or archive_dir.rsplit("/", 1)[-1].rsplit("-", 1)[0])
        archives.append(
            {
                "archive_id": archive_dir.rsplit("/", 1)[-1],
                "character_id": normalize_character_id(metadata.get("character_id") or manifest.get("character_id")),
                "slug": slug,
                "name": str(metadata.get("name") or slug),
                "role": str(metadata.get("role") or ""),
                "aliases": normalize_character_list(metadata.get("aliases")),
                "reason": str(manifest.get("reason") or ""),
                "archived_at": str(manifest.get("archived_at") or ""),
                "archive_path": archive_dir,
            }
        )
    return archives


async def restore_character(context: ProjectContext, archive_id: str) -> dict[str, Any]:
    safe_archive_id = normalize_character_archive_id(archive_id)
    archive_dir = f"temp/archive/characters/{safe_archive_id}"
    manifest_path = f"{archive_dir}/archive.json"
    if not await context.exists(manifest_path):
        raise FileNotFoundError(safe_archive_id)
    manifest = await context.read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("type") != "character_archive":
        raise ValueError("角色归档清单无效")
    slug = normalize_character_slug(str(manifest.get("slug") or ""))
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("角色归档中没有可恢复文件")

    moves: list[tuple[str, str]] = []
    for item in raw_files:
        if not isinstance(item, dict):
            raise ValueError("角色归档文件清单无效")
        source = str(item.get("to") or "").replace("\\", "/")
        target = str(item.get("from") or "").replace("\\", "/")
        if not source.startswith(f"{archive_dir}/") or not target.startswith(f"characters/{slug}/"):
            raise ValueError("角色归档路径越界")
        if not await context.exists(source):
            raise FileNotFoundError(source)
        if await context.exists(target):
            raise FileExistsError(target)
        moves.append((source, target))

    for source, target in moves:
        await context.move_file(source, target)
    await context.delete_file(manifest_path)
    await migrate_character_registry(context)
    return {
        "archive_id": safe_archive_id,
        "slug": slug,
        "status": "restored",
        "restored_files": [target for _, target in moves],
    }
