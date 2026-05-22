from __future__ import annotations

from typing import Any

from app.core.prompt_packs import PromptPackStage
from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult, ToolWorkspaceView


class WriteChapterTool(BaseTool):
    name = "write_chapter"
    description = "写入或覆盖章节 Markdown 文件。"
    workspace_view = ToolWorkspaceView(view_id="chapters", label="章节管理")

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(
            read=["plot/foreshadows.json", "plot/outline.json", "chapters/**/ch-meta.yaml"],
            write=["chapters/**/*.md"],
        )

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="stream:editor", description="章节编辑器预览")

    def prompt_pack_stages(self) -> list[PromptPackStage]:
        return ["chapter_draft"]

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

    def build_prompt(self, params: dict[str, Any]) -> str:
        path = str(params.get("path") or "chapters/vol-01/ch-001.md")
        requirements = str(params.get("content") or "").strip()
        prompt_pack_block = self.prompt_pack_block()
        return self._build_prompt_text(path, requirements, prompt_pack_block)

    async def build_project_prompt(self, params: dict[str, Any], context: ProjectContext) -> str:
        path = str(params.get("path") or "chapters/vol-01/ch-001.md")
        requirements = str(params.get("content") or "").strip()
        prompt_pack_block = await self.project_prompt_pack_block(context)
        return self._build_prompt_text(path, requirements, prompt_pack_block)

    def _build_prompt_text(self, path: str, requirements: str, prompt_pack_block: str) -> str:
        prompt_pack_section = f"\n\n{prompt_pack_block}\n" if prompt_pack_block else "\n"
        return (
            "请根据当前项目设定撰写章节，并调用 `write_chapter` 工具写入章节文件。\n"
            f"目标章节路径：{path}\n"
            f"写作要求或草稿：{requirements or '按当前大纲、章节元数据和项目上下文创作。'}\n"
            f"{prompt_pack_section}"
            "请优先参考 plot/foreshadows.json：如果存在与目标章节、大纲节点或标签相关的伏笔，"
            "需要判断本章应埋设、推进还是回收；不要主动使用已废弃伏笔。"
        )

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
