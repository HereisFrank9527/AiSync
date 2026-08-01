from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult, ToolWorkspaceView


class UpdateWorldviewTool(BaseTool):
    name = "update_worldview"
    description = "在 world 目录下创建或更新世界观 Markdown 文件。"
    workspace_view = ToolWorkspaceView(view_id="worldview", label="世界观整理")
    category = "edit"
    write_policy = "direct"
    agent_boundary = "用于创建或更新 world 目录下的世界观文档；删除旧设定段落、跨文件清理或补丁式替换应使用 file_change_proposal。"

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(read=["world/**/*.md"], write=["world/**/*.md"], generate=["world/**/*.md"])

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="document:worldview", description="世界观文档预览")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "world/ 下的世界观文件路径，例如 world/overview.md。",
                    "default": "world/overview.md",
                },
                "content": {"type": "string", "description": "世界观 Markdown 内容。"},
                "mode": {
                    "type": "string",
                    "description": "如何应用到世界观文件。",
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
            content=f"世界观已更新：{path}",
            ui_hint={"type": "document:worldview", "data": {"path": path, "content": updated}},
            metadata={"path": path, "mode": mode},
        )
