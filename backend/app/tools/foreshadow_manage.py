from __future__ import annotations

import re
from typing import Any

from app.projects.context import ProjectContext
from app.projects.foreshadows import (
    FORESHADOW_PATH,
    extract_chapter_paths,
    format_foreshadow_context,
    foreshadows_with_explanations,
    load_foreshadows,
    outline_ids_for_chapters,
)
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult, ToolWorkspaceView


ACTIVE_STATUSES = {"planned", "planted", "developing"}
MAX_LIMIT = 20


def _is_active_request(intent: str) -> bool:
    return any(token in intent for token in ("未回收", "待回收", "未完成", "推进中", "梳理", "规划"))


def _sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    importance_order = {"major": 0, "medium": 1, "minor": 2}
    return sorted(
        items,
        key=lambda item: (
            importance_order.get(str(item.get("importance") or "medium"), 1),
            str(item.get("title") or ""),
        ),
    )


def _ui_item(item: dict[str, Any]) -> dict[str, Any]:
    match = item.get("_match") if isinstance(item.get("_match"), dict) else {}
    return {
        "id": item.get("id", ""),
        "title": item.get("title", ""),
        "summary": item.get("summary", ""),
        "status": item.get("status", "planned"),
        "importance": item.get("importance", "medium"),
        "plant_chapter": item.get("plant_chapter", ""),
        "payoff_chapter": item.get("payoff_chapter", ""),
        "character_ids": item.get("character_ids", []),
        "outline_ids": item.get("outline_ids", []),
        "related_files": item.get("related_files", []),
        "tags": item.get("tags", []),
        "action": match.get("action", "参考"),
        "reasons": match.get("reasons", []),
        "score": match.get("score", 0),
    }


class ForeshadowManageTool(BaseTool):
    name = "foreshadow_manage"
    description = "读取结构化伏笔账本，梳理未回收伏笔、关联章节和建议动作。"
    workspace_view = ToolWorkspaceView(view_id="foreshadows", label="伏笔管理")
    category = "manage"
    write_policy = "none"
    agent_boundary = "只读取并梳理伏笔，不创建、修改或删除伏笔；实际变更必须通过章节改动包或 file_change_proposal。"

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(
            read=[FORESHADOW_PATH, "**/ch-meta.yaml"],
            write=[],
        )

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="list:foreshadows", description="伏笔梳理结果")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": "梳理目标，例如未回收伏笔、某一章节或某个大纲节点相关的伏笔。",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回多少条，范围 1 到 20。",
                    "minimum": 1,
                    "maximum": MAX_LIMIT,
                    "default": 8,
                },
            },
            "required": ["intent"],
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        intent = str(params.get("intent") or "").strip()
        try:
            limit = max(1, min(int(params.get("limit", 8)), MAX_LIMIT))
        except (TypeError, ValueError):
            limit = 8

        items = await load_foreshadows(context)
        if not items:
            empty_data = {"items": [], "intent": intent, "path": FORESHADOW_PATH, "mode": "empty"}
            return ToolResult(
                content=(
                    "当前项目没有结构化伏笔记录。\n"
                    "如需建立伏笔，请在写章节时声明 plant 动作，或在伏笔管理面板中新增记录。"
                ),
                ui_hint={"type": "list:foreshadows", "data": empty_data},
                metadata={"path": FORESHADOW_PATH, "result_count": 0, "mode": "empty"},
            )

        chapter_paths = set(extract_chapter_paths(intent))
        outline_ids = set(re.findall(r"outline-[A-Za-z0-9_-]+", intent, re.I))
        outline_ids.update(await outline_ids_for_chapters(context, sorted(chapter_paths)))
        explained = foreshadows_with_explanations(items, intent, chapter_paths, outline_ids)

        active_request = _is_active_request(intent)
        targeted = [item for item in explained if item["_match"]["matched"]]
        active = [item for item in explained if item.get("status") in ACTIVE_STATUSES]
        if targeted and not active_request:
            selected = targeted
            mode = "matched"
            heading = "与当前意图相关的伏笔"
        elif active_request or not intent:
            selected = _sort_items(active)
            mode = "active"
            heading = "尚未回收的伏笔"
        else:
            selected = _sort_items(active)
            mode = "active_fallback"
            heading = "当前没有精确命中，以下是尚未回收的伏笔"

        selected = selected[:limit]
        if not selected:
            content = f"{heading}：当前没有记录。"
        else:
            content = f"{heading}（显示 {len(selected)} 条，共 {len(active)} 条未回收）：\n{format_foreshadow_context(selected, limit)}"

        ui_items = [_ui_item(item) for item in selected]
        data = {
            "items": ui_items,
            "intent": intent,
            "path": FORESHADOW_PATH,
            "mode": mode,
            "active_count": len(active),
            "total_count": len(items),
        }
        return ToolResult(
            content=content,
            ui_hint={"type": "list:foreshadows", "data": data},
            metadata={
                "path": FORESHADOW_PATH,
                "result_count": len(selected),
                "active_count": len(active),
                "total_count": len(items),
                "mode": mode,
            },
        )
