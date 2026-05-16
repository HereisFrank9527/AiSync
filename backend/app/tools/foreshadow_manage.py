from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult, ToolWorkspaceView


class ForeshadowManageTool(BaseTool):
    name = "foreshadow_manage"
    description = "管理小说伏笔、回收计划和关联章节。"
    workspace_view = ToolWorkspaceView(view_id="foreshadows", label="伏笔管理")

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(
            read=["plot/foreshadows.json", "plot/outline.json", "chapters/**/*.md"],
            write=["plot/foreshadows.json"],
        )

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="list:foreshadows", description="伏笔列表")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": "要处理的伏笔管理意图，例如梳理未回收伏笔、补充伏笔摘要或规划回收。",
                },
            },
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        intent = str(params.get("intent") or "").strip()
        return ToolResult(
            content="伏笔管理工作区已就绪。请在侧边栏打开“伏笔管理”维护结构化伏笔。",
            ui_hint={
                "type": "list:foreshadows",
                "data": {"intent": intent, "path": "plot/foreshadows.json"},
            },
            metadata={"path": "plot/foreshadows.json"},
        )
