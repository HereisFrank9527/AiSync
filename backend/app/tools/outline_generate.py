from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.projects.outline import refresh_outline_index, snapshot_outline_markdown
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult, ToolWorkspaceView


class OutlineGenerateTool(BaseTool):
    name = "outline_generate"
    description = "新建大纲、向末尾/开头追加较大段正式大纲，或在用户明确要求时整体重写 plot/outline.md。"
    workspace_view = ToolWorkspaceView(view_id="outline", label="大纲整理")
    category = "generate"
    write_policy = "direct"
    agent_boundary = (
        "只用于新建、较大段续写或用户明确要求的整体重写。不得用于删除、清理、替换已有大纲区块；"
        "局部增删改必须先读取区块 ID，再改用 file_change_proposal 的大纲区块操作。"
    )

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
                    "description": "大纲创作要求、限制或方向。只用于指导生成，不会写入 plot/outline.md。",
                },
                "content": {
                    "type": "string",
                    "description": "要写入 plot/outline.md 的完整大纲 Markdown 内容；必须是正式大纲正文，不能是任务说明、清理要求或元说明。",
                },
            },
            "required": ["mode", "content"],
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
            "请优先读取世界观、角色、已有大纲和章节，并在 `content` 参数中提供正式 Markdown 大纲正文；"
            "不要把任务说明、清理要求或你的操作计划写入大纲文件。"
        )

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        mode = str(params.get("mode") or "append")
        content = str(params.get("content") or "").strip()

        if mode not in {"replace", "append", "prepend"}:
            raise ValueError("Mode must be replace, append, or prepend")

        if not content:
            raise ValueError("content is required and must be formal outline Markdown, not requirements or task notes")

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

        snapshot_path = await snapshot_outline_markdown(context, reason=f"agent-{mode}")
        await context.write_text(path, updated)
        outline_index = await refresh_outline_index(context)
        return ToolResult(
            content=f"大纲已更新：{path}",
            ui_hint={
                "type": "list:outline_chapters",
                "data": {
                    "path": path,
                    "content": updated,
                    "items": outline_index.get("items") or [],
                    "nodes": outline_index.get("nodes") or [],
                },
            },
            metadata={"path": path, "mode": mode, "snapshot_path": snapshot_path},
        )
