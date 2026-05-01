from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolResult


class WriteChapterTool(BaseTool):
    name = "write_chapter"
    description = "Write or replace a chapter markdown file."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Chapter path relative to the project root."},
                "content": {"type": "string", "description": "Markdown chapter content."},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        path = str(params["path"])
        content = str(params["content"])
        if not path.startswith("chapters/") or not path.endswith(".md"):
            raise ValueError("Chapter path must be under chapters/ and end with .md")
        await context.write_text(path, content)
        return ToolResult(
            content=f"Chapter written to {path}",
            ui_hint={"type": "stream:editor", "data": {"path": path, "content": content}},
        )
