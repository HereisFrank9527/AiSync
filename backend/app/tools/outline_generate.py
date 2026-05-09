from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.projects.outline import outline_items_from_markdown
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult, ToolWorkspaceView


class OutlineGenerateTool(BaseTool):
    name = "outline_generate"
    description = "创建、续写或重写 plot/outline.md 下的故事大纲。"
    workspace_view = ToolWorkspaceView(view_id="outline", label="大纲整理")

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(
            read=["world/**/*.md", "characters/**/*.yaml", "characters/**/*.md", "plot/outline.md", "chapters/**/*.md"],
            write=["plot/outline.md"],
            generate=["plot/outline.json"],
        )

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="list:outline_chapters", description="大纲章节列表")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "如何更新大纲。",
                    "enum": ["replace", "append", "prepend"],
                    "default": "append",
                },
                "target_chapter_count": {
                    "type": "integer",
                    "description": "目标章节数或大纲节点数。",
                },
                "requirements": {
                    "type": "string",
                    "description": "大纲创作要求、限制或方向。",
                },
                "content": {
                    "type": "string",
                    "description": "大纲 Markdown 内容。AI 调用时可留空，改写 requirements。",
                },
            },
            "required": ["mode"],
            "additionalProperties": False,
        }

    def build_prompt(self, params: dict[str, Any]) -> str:
        mode = str(params.get("mode") or "append")
        count = params.get("target_chapter_count")
        requirements = str(params.get("requirements") or "").strip()
        return (
            "请生成或续写长篇小说大纲，并调用 `outline_generate` 工具写入项目文件。\n"
            f"更新模式：{mode}\n"
            f"目标章节/节点数：{count or '由你判断'}\n"
            f"创作要求：{requirements or '按当前项目设定推进'}\n"
            "请优先读取世界观、角色、已有大纲和章节，输出 Markdown 大纲。"
        )

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        mode = str(params.get("mode") or "append")
        content = str(params.get("content") or "").strip()
        requirements = str(params.get("requirements") or "").strip()
        count = params.get("target_chapter_count")

        if mode not in {"replace", "append", "prepend"}:
            raise ValueError("Mode must be replace, append, or prepend")

        if not content:
            title = f"## 大纲更新{f'（目标 {count} 节点）' if count else ''}"
            body = requirements or "请在 AI 生成模式下提供大纲内容。"
            content = f"{title}\n\n{body}\n"

        path = "plot/outline.md"
        if await context.exists(path):
            current = await context.read_text(path)
        else:
            current = "# 大纲\n\n"

        if mode == "replace":
            updated = content
        elif mode == "prepend":
            updated = f"{content.rstrip()}\n\n{current.lstrip()}"
        else:
            updated = f"{current.rstrip()}\n\n{content.lstrip()}"

        await context.write_text(path, updated)
        return ToolResult(
            content=f"大纲已更新：{path}",
            ui_hint={
                "type": "list:outline_chapters",
                "data": {"path": path, "content": updated, "items": outline_items_from_markdown(updated)},
            },
            metadata={"path": path, "mode": mode},
        )
