from __future__ import annotations

from typing import Any

from app.projects.characters import archive_character, normalize_character_slug
from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult, ToolWorkspaceView


class CharacterManageTool(BaseTool):
    name = "character_manage"
    description = "管理已有角色档案。当前支持将角色归档到 temp/archive，避免不可恢复删除。"
    workspace_view = ToolWorkspaceView(view_id="characters", label="角色管理")
    category = "manage"
    write_policy = "direct"
    agent_boundary = "用于可恢复归档角色目录，不用于编辑角色正文；修改角色内容或清理旧表述应使用 file_change_proposal。"

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(
            read=["characters/{slug}/**"],
            write=["temp/archive/characters/{slug}-*/**"],
        )

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="card:character", description="角色管理结果")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "角色管理动作。当前只支持 archive。",
                    "enum": ["archive"],
                    "default": "archive",
                },
                "slug": {"type": "string", "description": "角色目录名，例如 lin-duo。"},
                "reason": {"type": "string", "description": "归档原因，例如旧名残留、重复角色或废弃设定。"},
            },
            "required": ["action", "slug"],
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        action = str(params.get("action") or "archive")
        slug = normalize_character_slug(str(params.get("slug") or ""))
        reason = str(params.get("reason") or "").strip()
        if action != "archive":
            raise ValueError("CharacterManageTool only supports archive")

        result = await archive_character(context, slug, reason)
        archive_path = str(result["archive_path"])
        return ToolResult(
            content=f"角色已归档：{slug} -> {archive_path}",
            ui_hint={
                "type": "card:character",
                "data": {
                    "slug": slug,
                    "name": slug,
                    "role": "已归档",
                    "summary": reason or f"角色档案已移动到 {archive_path}",
                    "profile_path": archive_path,
                },
            },
            metadata=result,
        )
