from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolResult


class EditChapterTool(BaseTool):
    name = "edit_chapter"
    description = "Edit an existing chapter markdown file."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Chapter path relative to the project root."},
                "content": {"type": "string", "description": "Markdown content to write, append, or prepend."},
                "mode": {
                    "type": "string",
                    "description": "How to apply content to the chapter.",
                    "enum": ["replace", "append", "prepend"],
                    "default": "replace",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        path = str(params["path"])
        content = str(params["content"])
        mode = str(params.get("mode", "replace"))

        if not path.startswith("chapters/") or not path.endswith(".md"):
            raise ValueError("Chapter path must be under chapters/ and end with .md")
        if mode not in {"replace", "append", "prepend"}:
            raise ValueError("Mode must be replace, append, or prepend")
        if not await context.exists(path):
            raise ValueError(f"Chapter does not exist: {path}")

        current = await context.read_text(path)
        if mode == "append":
            updated = f"{current.rstrip()}\n\n{content.lstrip()}"
        elif mode == "prepend":
            updated = f"{content.rstrip()}\n\n{current.lstrip()}"
        else:
            updated = content

        await context.write_text(path, updated)
        return ToolResult(
            content=f"Chapter edited: {path}",
            ui_hint={"type": "stream:editor", "data": {"path": path, "content": updated}},
            metadata={"path": path, "mode": mode},
        )
