from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult, ToolWorkspaceView


class CreateCharacterTool(BaseTool):
    name = "create_character"
    description = "创建角色档案 Markdown 和 YAML 元数据文件。"
    workspace_view = ToolWorkspaceView(view_id="characters", label="角色管理")

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
            },
            "required": ["slug", "name", "role", "summary"],
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        slug = str(params["slug"]).strip().strip("/")
        name = str(params["name"]).strip()
        role = str(params["role"]).strip()
        summary = str(params["summary"]).strip()
        profile = str(params.get("profile") or summary).strip()

        if not slug or "/" in slug or ".." in slug:
            raise ValueError("Character slug must be a single safe directory name")
        if not name:
            raise ValueError("Character name is required")

        base_path = f"characters/{slug}"
        profile_path = f"{base_path}/profile.md"
        metadata_path = f"{base_path}/profile.yaml"

        if await context.exists(profile_path) or await context.exists(metadata_path):
            raise ValueError(f"Character already exists: {slug}")

        markdown = f"# {name}\n\n## 角色定位\n\n{role}\n\n## 简介\n\n{summary}\n\n## 详细档案\n\n{profile}\n"
        metadata = {
            "slug": slug,
            "name": name,
            "role": role,
            "summary": summary,
        }

        await context.write_text(profile_path, markdown)
        await context.write_yaml(metadata_path, metadata)
        return ToolResult(
            content=f"角色已创建：{name}（{slug}）",
            ui_hint={"type": "card:character", "data": {**metadata, "profile_path": profile_path}},
            metadata={"profile_path": profile_path, "metadata_path": metadata_path},
        )
