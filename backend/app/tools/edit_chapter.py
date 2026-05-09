from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult


class EditChapterTool(BaseTool):
    name = "edit_chapter"
    description = "编辑已有章节 Markdown 文件。"

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(read=["chapters/**/*.md"], write=["chapters/**/*.md"])

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="stream:editor", description="章节编辑器预览")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对于项目根目录的章节路径。"},
                "content": {"type": "string", "description": "要写入、追加或前置的 Markdown 内容。"},
                "mode": {
                    "type": "string",
                    "description": "如何应用到章节。",
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
            content=f"章节已更新：{path}",
            ui_hint={"type": "stream:editor", "data": {"path": path, "content": updated}},
            metadata={"path": path, "mode": mode},
        )
