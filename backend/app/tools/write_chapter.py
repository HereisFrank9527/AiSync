from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult, ToolWorkspaceView


class WriteChapterTool(BaseTool):
    name = "write_chapter"
    description = "写入或覆盖章节 Markdown 文件。"
    workspace_view = ToolWorkspaceView(view_id="chapters", label="章节管理")

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(write=["chapters/**/*.md"])

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="stream:editor", description="章节编辑器预览")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对于项目根目录的章节路径。"},
                "content": {"type": "string", "description": "章节 Markdown 内容。"},
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
            content=f"章节已写入：{path}",
            ui_hint={"type": "stream:editor", "data": {"path": path, "content": content}},
        )
