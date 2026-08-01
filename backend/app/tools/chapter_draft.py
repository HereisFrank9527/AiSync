from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.change_sets import change_set_ui_data
from app.projects.context import ProjectContext
from app.projects.facts import fact_records_schema
from app.tools.base import BaseTool, ToolFileAccess, ToolResult
from app.tools.chapter_change import create_chapter_change_set

DRAFT_ROOT = ".aisync/chapter_drafts"
DRAFT_ID_RE = re.compile(r"^chapterdraft_[a-f0-9]{32}$")
MAX_DRAFT_CHUNK_CHARS = 5_000
MAX_DRAFT_TOTAL_CHARS = 200_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_chapter_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip().lstrip("/")
    if not normalized.startswith("chapters/") or not normalized.endswith(".md"):
        raise ValueError("Chapter path must be under chapters/ and end with .md")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise ValueError("invalid chapter path")
    return normalized


def _draft_paths(draft_id: str) -> tuple[str, str]:
    if not DRAFT_ID_RE.fullmatch(draft_id):
        raise ValueError("invalid chapter draft id")
    return f"{DRAFT_ROOT}/{draft_id}.json", f"{DRAFT_ROOT}/{draft_id}.md"


async def _load_draft(context: ProjectContext, draft_id: str) -> tuple[dict[str, Any], str, str]:
    metadata_path, content_path = _draft_paths(draft_id)
    if not await context.exists(metadata_path) or not await context.exists(content_path):
        raise ValueError(f"章节草稿不存在或已提交：{draft_id}")
    metadata = await context.read_json(metadata_path)
    if not isinstance(metadata, dict):
        raise ValueError("章节草稿元数据无效")
    content = await context.read_text(content_path)
    return metadata, content, content_path


async def _delete_draft(context: ProjectContext, draft_id: str) -> None:
    metadata_path, content_path = _draft_paths(draft_id)
    for path in (metadata_path, content_path):
        if await context.exists(path):
            await context.delete_file(path)


class ChapterDraftTool(BaseTool):
    name = "chapter_draft"
    description = (
        "分块生成长章节的内部草稿缓冲工具。依次 begin、append、finalize；"
        "最终提交只引用 draft_id，不在一次工具参数中重复整章正文。"
    )
    category = "generate"
    write_policy = "workspace_only"
    has_frontend_ui = False
    agent_internal = True
    agent_boundary = (
        "仅用于长章节完整写作或整体重写。每轮只调用一次；append 单块不超过 5000 字符，"
        "必须按 sequence 顺序追加；局部修改仍使用 edit_chapter 或 file_change_proposal。"
    )

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(
            read=[f"{DRAFT_ROOT}/*.md", f"{DRAFT_ROOT}/*.json", "plot/foreshadows.json"],
            write=[
                f"{DRAFT_ROOT}/*.md",
                f"{DRAFT_ROOT}/*.json",
                "chapters/**/*.md",
                "plot/facts/**/*.json",
                "plot/foreshadows.json",
            ],
        )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["begin", "append", "finalize", "discard"],
                    "description": "begin 创建缓冲；append 追加正文；finalize 生成待确认改动包；discard 丢弃缓冲。",
                },
                "path": {
                    "type": "string",
                    "description": "begin 时必填，目标章节路径 chapters/**/*.md。",
                },
                "draft_id": {
                    "type": "string",
                    "description": "append、finalize、discard 时使用 begin 返回的草稿 ID。",
                },
                "sequence": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "append 时必填，必须等于工具返回的 next_sequence。",
                },
                "content": {
                    "type": "string",
                    "maxLength": MAX_DRAFT_CHUNK_CHARS,
                    "description": "append 的下一段正文，紧接上一段，不重复，最多 5000 字符。",
                },
                "foreshadow_actions": {
                    "type": "array",
                    "description": (
                        "finalize 时提交整章伏笔动作，没有时传空数组。"
                        "plant 是新建伏笔，禁止填写 foreshadow_id，且必须填写 title 和 summary；"
                        "advance/payoff 只能操作已存在的伏笔，必须填写现有 foreshadow_id。"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["plant", "advance", "payoff", "none"]},
                            "foreshadow_id": {
                                "type": "string",
                                "description": "仅 advance/payoff 填写；plant 禁止填写。",
                            },
                            "title": {"type": "string", "description": "plant 必填。"},
                            "summary": {"type": "string", "description": "plant 必填。"},
                            "payoff_chapter": {"type": "string"},
                            "evidence": {"type": "string"},
                            "importance": {"type": "string", "enum": ["minor", "medium", "major"]},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["action"],
                        "additionalProperties": False,
                    },
                },
                "fact_records": fact_records_schema(),
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        action = str(params.get("action") or "").strip().lower()
        if action == "begin":
            return await self._begin(params, context)
        if action == "append":
            return await self._append(params, context)
        if action == "finalize":
            return await self._finalize(params, context)
        if action == "discard":
            return await self._discard(params, context)
        raise ValueError("action must be begin, append, finalize, or discard")

    async def _begin(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        path = _validate_chapter_path(str(params.get("path") or ""))
        draft_id = f"chapterdraft_{uuid4().hex}"
        metadata_path, content_path = _draft_paths(draft_id)
        metadata = {
            "version": 1,
            "draft_id": draft_id,
            "chapter_path": path,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "next_sequence": 1,
            "chunks": 0,
            "characters": 0,
        }
        await context.write_json(metadata_path, metadata)
        await context.write_text(content_path, "")
        return ToolResult(
            content=(
                f"长章节草稿缓冲已创建：{draft_id}，目标 {path}。"
                "请从 sequence=1 开始，每轮只调用一次 append，单块建议 3000～4000 字符；"
                "正文完成后调用 finalize，提交伏笔和长期事实。"
            ),
            metadata={
                "draft_id": draft_id,
                "chapter_path": path,
                "next_sequence": 1,
                "draft_characters": 0,
                "draft_action": "begin",
            },
        )

    async def _append(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        draft_id = str(params.get("draft_id") or "")
        sequence = int(params.get("sequence") or 0)
        content = str(params.get("content") or "")
        if not content:
            raise ValueError("append content is required")
        if len(content) > MAX_DRAFT_CHUNK_CHARS:
            raise ValueError(f"单个章节草稿分块最多 {MAX_DRAFT_CHUNK_CHARS} 字符")
        metadata, current, content_path = await _load_draft(context, draft_id)
        expected = int(metadata.get("next_sequence") or 1)
        if sequence != expected:
            raise ValueError(f"草稿分块顺序错误：期望 sequence={expected}，收到 {sequence}")
        updated = current + content
        if len(updated) > MAX_DRAFT_TOTAL_CHARS:
            raise ValueError(f"单章草稿最多 {MAX_DRAFT_TOTAL_CHARS} 字符")
        await context.write_text(content_path, updated)
        metadata.update(
            {
                "updated_at": _now_iso(),
                "next_sequence": expected + 1,
                "chunks": int(metadata.get("chunks") or 0) + 1,
                "characters": len(updated),
            }
        )
        metadata_path, _ = _draft_paths(draft_id)
        await context.write_json(metadata_path, metadata)
        tail = " ".join(updated[-240:].split())
        return ToolResult(
            content=(
                f"章节草稿已追加第 {sequence} 块，累计 {len(updated)} 字符。"
                f"下一块使用 sequence={expected + 1}；若正文已完成则调用 finalize。"
                f"\n当前结尾：{tail}"
            ),
            metadata={
                "draft_id": draft_id,
                "chapter_path": metadata.get("chapter_path"),
                "next_sequence": expected + 1,
                "draft_chunks": metadata["chunks"],
                "draft_characters": len(updated),
                "draft_action": "append",
            },
        )

    async def _finalize(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        draft_id = str(params.get("draft_id") or "")
        metadata, content, _ = await _load_draft(context, draft_id)
        if not content.strip():
            raise ValueError("章节草稿为空，不能提交")
        raw_actions = params.get("foreshadow_actions") or []
        if not isinstance(raw_actions, list):
            raise ValueError("foreshadow_actions must be a list")
        actions = [item for item in raw_actions if isinstance(item, dict)]
        raw_facts = params.get("fact_records") if "fact_records" in params else None
        if raw_facts is not None and not isinstance(raw_facts, list):
            raise ValueError("fact_records must be a list")
        chapter_path = _validate_chapter_path(str(metadata.get("chapter_path") or ""))
        proposal = await create_chapter_change_set(
            context,
            path=chapter_path,
            content=content,
            actions=actions,
            fact_records=raw_facts,
            title=f"提交长章节草稿并更新结构化记录：{chapter_path}",
            force_proposal=True,
        )
        if proposal is None:
            raise RuntimeError("未能生成章节改动包")
        record = proposal.record
        applied_actions = proposal.foreshadow_actions
        facts = proposal.fact_records
        warnings = proposal.warnings
        await _delete_draft(context, draft_id)
        ui_data = change_set_ui_data(record)
        ui_data["foreshadow_actions"] = applied_actions
        ui_data["fact_records"] = facts
        ui_data["warnings"] = warnings
        warning_text = f"另有 {len(warnings)} 条无效伏笔动作已跳过，正文不受影响。" if warnings else ""
        return ToolResult(
            content=(
                f"长章节草稿已汇总为待确认改动包：{record.id}。"
                f"正文 {len(content)} 字符，长期事实 {len(facts)} 条，伏笔动作 {len(applied_actions)} 条。"
                f"{warning_text}"
            ),
            ui_hint={"type": "changeset:proposal", "data": ui_data},
            metadata={
                "changeset_id": record.id,
                "draft_id": draft_id,
                "draft_action": "finalize",
                "chapter_path": chapter_path,
                "draft_characters": len(content),
                "foreshadow_actions": applied_actions,
                "fact_records": facts,
                "warnings": warnings,
                "paths": [change.path for change in record.changes],
            },
        )

    async def _discard(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        draft_id = str(params.get("draft_id") or "")
        metadata, content, _ = await _load_draft(context, draft_id)
        await _delete_draft(context, draft_id)
        return ToolResult(
            content=f"已丢弃章节草稿 {draft_id}，未修改正式章节。",
            metadata={
                "draft_id": draft_id,
                "draft_action": "discard",
                "chapter_path": metadata.get("chapter_path"),
                "draft_characters": len(content),
            },
        )
