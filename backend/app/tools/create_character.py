from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolResult


class CreateCharacterTool(BaseTool):
    name = "create_character"
    description = "Create a character profile markdown and YAML metadata file."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Character directory name, such as protagonist or lin-qing."},
                "name": {"type": "string", "description": "Character display name."},
                "role": {"type": "string", "description": "Narrative role, such as protagonist, ally, or antagonist."},
                "summary": {"type": "string", "description": "Short character summary."},
                "profile": {"type": "string", "description": "Detailed markdown profile."},
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
            content=f"Character created: {name} ({slug})",
            ui_hint={"type": "card:character", "data": {**metadata, "profile_path": profile_path}},
            metadata={"profile_path": profile_path, "metadata_path": metadata_path},
        )
