from __future__ import annotations

from typing import Any

from app.projects.characters import CharacterConflictError, save_character
from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult, ToolWorkspaceView


class CreateCharacterTool(BaseTool):
    name = "create_character"
    description = "创建角色档案 Markdown 和 YAML 元数据文件。"
    workspace_view = ToolWorkspaceView(view_id="characters", label="角色管理")
    category = "generate"
    write_policy = "direct"
    agent_boundary = "用于新建角色档案；修改、删除或清理既有角色文件内容时优先使用 file_change_proposal，废弃角色使用 character_manage 归档。"

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(generate=["characters/{slug}/profile.md", "characters/{slug}/profile.yaml"])

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="card:character", description="角色档案卡片")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "角色目录名，例如 protagonist 或 lin-qing。"},
                "name": {"type": "string", "description": "角色显示名称。"},
                "role": {"type": "string", "description": "叙事定位，例如主角、盟友或反派。"},
                "summary": {"type": "string", "description": "角色简述。"},
                "profile": {"type": "string", "description": "详细角色档案 Markdown。"},
                "aliases": {"type": "array", "items": {"type": "string"}, "description": "别名、旧名或称号。"},
                "status": {
                    "type": "string",
                    "enum": ["active", "inactive", "missing", "deceased", "retired", "unknown"],
                    "description": "角色当前状态。",
                    "default": "active",
                },
                "faction": {"type": "string", "description": "所属阵营或组织。"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "角色标签。"},
                "first_appearance": {"type": "string", "description": "首次出场章节或大纲节点。"},
            },
            "required": ["slug", "name", "role", "summary"],
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        slug = str(params["slug"])
        name = str(params["name"]).strip()
        role = str(params["role"]).strip()
        summary = str(params["summary"]).strip()
        profile = str(params.get("profile") or summary).strip()

        markdown = profile if profile.lstrip().startswith("#") else f"# {name}\n\n{profile or summary}\n"
        try:
            record = await save_character(
                context,
                slug=slug,
                name=name,
                role=role,
                summary=summary,
                profile=markdown,
                aliases=params.get("aliases") if isinstance(params.get("aliases"), list) else [],
                status=str(params.get("status") or "active"),
                faction=str(params.get("faction") or ""),
                tags=params.get("tags") if isinstance(params.get("tags"), list) else [],
                first_appearance=str(params.get("first_appearance") or ""),
                create=True,
            )
        except FileExistsError as exc:
            raise ValueError(f"角色标识已存在：{slug}") from exc
        except CharacterConflictError as exc:
            raise ValueError(str(exc)) from exc
        return ToolResult(
            content=f"角色已创建：{name}（{slug}）",
            ui_hint={"type": "card:character", "data": record},
            metadata={"profile_path": record["profile_path"], "metadata_path": record["metadata_path"]},
        )
