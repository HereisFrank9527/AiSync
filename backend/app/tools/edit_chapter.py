from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult


class EditChapterTool(BaseTool):
    name = "edit_chapter"
    description = "编辑已有章节 Markdown 文件。"

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(
            read=["chapters/**/*.md", "plot/foreshadows.json", "plot/outline.json", "chapters/**/ch-meta.yaml"],
            write=["chapters/**/*.md"],
        )

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

    def build_prompt(self, params: dict[str, Any]) -> str:
        path = str(params.get("path") or "")
        mode = str(params.get("mode") or "replace")
        content = str(params.get("content") or "").strip()
        return (
            "请根据当前项目设定编辑章节，并调用 `edit_chapter` 工具写回章节文件。\n"
            f"目标章节路径：{path or '请从用户要求判断'}\n"
            f"应用方式：{mode}\n"
            f"编辑要求或草稿：{content or '按当前章节内容、项目上下文和用户要求修改。'}\n"
            "请检查 plot/foreshadows.json：如果目标章节是某个伏笔的埋设/回收章节，或关联同一大纲节点，"
            "修改时应保持伏笔状态一致；不要主动使用已废弃伏笔。"
        )

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
