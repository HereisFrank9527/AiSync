from __future__ import annotations

import asyncio
import difflib
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.projects.context import ProjectContext

SAFE_FILE_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
BLOCKED_ROOTS = {".aisync", ".vectordb"}
RESERVED_PATHS = {"temp/.aisync-temp.json"}
CHANGE_SET_DIR = ".aisync/change_sets"


class ProposedFileChange(BaseModel):
    path: str
    operation: Literal["write", "delete"] = "write"
    new_content: str | None = None
    reason: str = ""
    source_operations: list[str] = Field(default_factory=list)
    outline_node_ids: list[str] = Field(default_factory=list)


class StoredFileChange(BaseModel):
    path: str
    operation: Literal["write", "delete"]
    old_hash: str | None = None
    old_content: str = ""
    new_content: str | None = None
    diff: str
    reason: str = ""
    source_operations: list[str] = Field(default_factory=list)
    outline_node_ids: list[str] = Field(default_factory=list)


class ChangeSetRecord(BaseModel):
    id: str
    title: str
    summary: str = ""
    status: Literal["pending", "applied", "discarded"] = "pending"
    created_at: str
    applied_at: str | None = None
    discarded_at: str | None = None
    project_path: str
    changes: list[StoredFileChange] = Field(default_factory=list)


def change_set_ui_data(record: ChangeSetRecord) -> dict[str, Any]:
    data = record.model_dump()
    data["changes"] = [
        {
            "path": change.path,
            "operation": change.operation,
            "old_hash": change.old_hash,
            "diff": change.diff,
            "reason": change.reason,
            "source_operations": list(change.source_operations),
            "outline_node_ids": list(change.outline_node_ids),
            "old_length": len(change.old_content),
            "new_length": len(change.new_content or ""),
        }
        for change in record.changes
    ]
    return data


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalize_editable_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip().lstrip("/")
    if not normalized or normalized == ".":
        raise ValueError("path is required")
    if "\x00" in normalized or ":" in normalized:
        raise ValueError(f"invalid path: {path}")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"invalid path: {path}")
    if parts[0] in BLOCKED_ROOTS or any(part.startswith(".") for part in parts):
        raise ValueError(f"internal paths are not editable: {path}")
    if normalized in RESERVED_PATHS:
        raise ValueError(f"reserved project metadata file: {path}")
    if Path(normalized).suffix.lower() not in SAFE_FILE_EXTENSIONS:
        raise ValueError(f"unsupported file type: {path}")
    return normalized


def change_set_path(change_set_id: str) -> str:
    if not change_set_id.startswith("changeset_") or not change_set_id.replace("changeset_", "", 1).isalnum():
        raise ValueError("invalid change set id")
    return f"{CHANGE_SET_DIR}/{change_set_id}.json"


def unified_diff(path: str, old_content: str, new_content: str) -> str:
    return "".join(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )


async def create_change_set(
    context: ProjectContext,
    *,
    title: str,
    summary: str = "",
    changes: list[ProposedFileChange],
) -> ChangeSetRecord:
    if not changes:
        raise ValueError("changes must not be empty")

    stored_changes: list[StoredFileChange] = []
    seen_paths: set[str] = set()
    for change in changes:
        normalized_path = normalize_editable_path(change.path)
        if normalized_path in seen_paths:
            raise ValueError(f"duplicate change path: {normalized_path}")
        seen_paths.add(normalized_path)

        exists = await context.exists(normalized_path)
        old_content = await context.read_text(normalized_path) if exists else ""
        old_hash = hash_text(old_content) if exists else None

        if change.operation == "delete":
            if not exists:
                raise ValueError(f"cannot delete missing file: {normalized_path}")
            new_content = None
            diff = unified_diff(normalized_path, old_content, "")
        else:
            if change.new_content is None:
                raise ValueError(f"new_content is required for write change: {normalized_path}")
            new_content = change.new_content
            diff = unified_diff(normalized_path, old_content, new_content)

        stored_changes.append(
            StoredFileChange(
                path=normalized_path,
                operation=change.operation,
                old_hash=old_hash,
                old_content=old_content,
                new_content=new_content,
                diff=diff,
                reason=change.reason,
                source_operations=list(change.source_operations),
                outline_node_ids=list(change.outline_node_ids),
            )
        )

    record = ChangeSetRecord(
        id=f"changeset_{uuid4().hex}",
        title=title.strip() or "待确认文件改动",
        summary=summary.strip(),
        created_at=now_iso(),
        project_path=str(context.root),
        changes=stored_changes,
    )
    await save_change_set(context, record)
    return record


async def save_change_set(context: ProjectContext, record: ChangeSetRecord) -> None:
    await context.write_json(change_set_path(record.id), record.model_dump())


async def load_change_set(context: ProjectContext, change_set_id: str) -> ChangeSetRecord:
    path = change_set_path(change_set_id)
    if not await context.exists(path):
        raise FileNotFoundError(change_set_id)
    return ChangeSetRecord.model_validate(await context.read_json(path))


async def apply_change_set(
    context: ProjectContext,
    change_set_id: str,
    *,
    paths: list[str] | None = None,
) -> ChangeSetRecord:
    record = await load_change_set(context, change_set_id)
    if record.status != "pending":
        raise ValueError(f"change set is already {record.status}")

    selected_paths = {normalize_editable_path(path) for path in paths} if paths else None
    changes = [change for change in record.changes if selected_paths is None or change.path in selected_paths]
    if not changes:
        raise ValueError("no matching changes to apply")

    outline_change = next((change for change in changes if change.path == "plot/outline.md"), None)

    for change in changes:
        exists = await context.exists(change.path)
        current = await context.read_text(change.path) if exists else ""
        current_hash = hash_text(current) if exists else None
        if current_hash != change.old_hash:
            raise RuntimeError(f"file changed after proposal: {change.path}")

    if outline_change is not None:
        from app.projects.outline import snapshot_outline_markdown

        await snapshot_outline_markdown(context, reason="changeset-apply")

    for change in changes:
        if change.operation == "delete":
            await context.delete_file(change.path)
        else:
            await context.write_text(change.path, change.new_content or "")

    if outline_change is not None and outline_change.operation != "delete":
        from app.projects.outline import refresh_outline_index

        await refresh_outline_index(context)

    if selected_paths is None or len(changes) == len(record.changes):
        record.status = "applied"
        record.applied_at = now_iso()
    await save_change_set(context, record)
    return record


async def verify_change_set_application(
    context: ProjectContext,
    change_set_id: str,
) -> dict[str, Any]:
    record = await load_change_set(context, change_set_id)
    files: list[dict[str, Any]] = []
    issues: list[str] = []
    for change in record.changes:
        exists = await context.exists(change.path)
        if change.operation == "delete":
            verified = not exists
            issue = "" if verified else "文件仍然存在"
        elif not exists:
            verified = False
            issue = "文件不存在"
        else:
            content = await context.read_text(change.path)
            verified = hash_text(content) == hash_text(change.new_content or "")
            issue = "" if verified else "文件内容与改动包不一致"
        files.append({"path": change.path, "operation": change.operation, "verified": verified, "issue": issue})
        if issue:
            issues.append(f"{change.path}: {issue}")
    verified_count = sum(1 for item in files if item["verified"])
    return {
        "status": "verified" if record.status == "applied" and not issues else "review",
        "change_set_status": record.status,
        "verified": verified_count,
        "total": len(files),
        "issues": issues,
        "files": files,
    }


async def discard_change_set(context: ProjectContext, change_set_id: str) -> ChangeSetRecord:
    record = await load_change_set(context, change_set_id)
    if record.status == "applied":
        raise ValueError("applied change set cannot be discarded")
    record.status = "discarded"
    record.discarded_at = now_iso()
    await save_change_set(context, record)
    return record


async def list_change_sets(context: ProjectContext) -> list[ChangeSetRecord]:
    files = await context.list_files(CHANGE_SET_DIR)
    records: list[ChangeSetRecord] = []
    for path in files:
        if not path.endswith(".json"):
            continue
        try:
            records.append(ChangeSetRecord.model_validate(await context.read_json(path)))
        except Exception:
            continue
    return sorted(records, key=lambda item: item.created_at, reverse=True)


async def remove_all_change_sets(context: ProjectContext) -> None:
    root = context.resolve_path(CHANGE_SET_DIR)
    if not root.exists():
        return

    def remove() -> None:
        for path in root.glob("*.json"):
            path.unlink()

    await asyncio.to_thread(remove)
