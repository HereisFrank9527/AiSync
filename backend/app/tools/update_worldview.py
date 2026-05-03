from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolResult


class UpdateWorldviewTool(BaseTool):
    name = "update_worldview"
    description = "Create or update a worldbuilding markdown file under the world directory."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Worldbuilding file path under world/, such as world/overview.md.",
                    "default": "world/overview.md",
                },
                "content": {"type": "string", "description": "Worldbuilding markdown content."},
                "mode": {
                    "type": "string",
                    "description": "How to apply content to the worldview file.",
                    "enum": ["replace", "append", "prepend"],
                    "default": "append",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        path = str(params.get("path") or "world/overview.md")
        content = str(params["content"])
        mode = str(params.get("mode", "append"))

        if not path.startswith("world/") or not path.endswith(".md"):
            raise ValueError("Worldview path must be under world/ and end with .md")
        if mode not in {"replace", "append", "prepend"}:
            raise ValueError("Mode must be replace, append, or prepend")

        exists = await context.exists(path)
        if not exists or mode == "replace":
            updated = content
        else:
            current = await context.read_text(path)
            if mode == "append":
                updated = f"{current.rstrip()}\n\n{content.lstrip()}"
            else:
                updated = f"{content.rstrip()}\n\n{current.lstrip()}"

        await context.write_text(path, updated)
        return ToolResult(
            content=f"Worldview updated: {path}",
            ui_hint={"type": "document:worldview", "data": {"path": path, "content": updated}},
            metadata={"path": path, "mode": mode},
        )
