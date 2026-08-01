from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult
from app.vector.store import ProjectVectorStore

MODEL_RESULT_LIMIT = 3
MODEL_SNIPPET_CHARS = 120
UI_SNIPPET_CHARS = 220


class SearchProjectTool(BaseTool):
    name = "search_project"
    description = "按关键词或短语搜索项目文本文件。"
    category = "search"
    write_policy = "none"
    agent_boundary = "只检索和汇总项目内容，不修改任何文件。"

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(read=["**/*.md", "**/*.txt", "**/*.yaml", "**/*.yml", "**/*.json"])

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="list:search_results", description="搜索结果列表")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要搜索的关键词或短语。"},
                "limit": {"type": "integer", "description": "最多返回多少条匹配片段。", "default": 10},
                "collections": {
                    "type": "string",
                    "description": "可选的范围，逗号分隔：chapters, characters, world, plot, other。",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        query = str(params["query"]).strip()
        limit = int(params.get("limit", 10))
        collections = [
            item.strip()
            for item in str(params.get("collections") or "").split(",")
            if item.strip()
        ] or None
        matches = await ProjectVectorStore(context).query(query, collections=collections, top_k=limit)

        if not matches:
            return ToolResult(content=f"未找到匹配内容：{params['query']}", ui_hint={"type": "list:search_results", "data": []})

        ui_items: list[dict[str, Any]] = []
        for item in matches:
            snippet = self._snippet(str(item["content"]), UI_SNIPPET_CHARS)
            ui_items.append({
                "path": item["path"],
                "snippet": snippet,
                "score": item["score"],
                "collection": item["collection"],
            })
        return ToolResult(
            content=self._model_summary(query, matches),
            ui_hint={"type": "list:search_results", "data": ui_items},
            metadata={"result_count": len(matches), "model_result_count": min(len(matches), MODEL_RESULT_LIMIT)},
        )

    def _model_summary(self, query: str, matches: list[dict[str, Any]]) -> str:
        shown = min(len(matches), MODEL_RESULT_LIMIT)
        lines = [f"检索词：{query}", f"命中 {len(matches)} 个项目片段，以下仅给模型前 {shown} 条摘要："]
        for index, item in enumerate(matches[:MODEL_RESULT_LIMIT], start=1):
            snippet = self._snippet(str(item.get("content") or ""), MODEL_SNIPPET_CHARS)
            lines.append(f"{index}. {item.get('path')}（{item.get('score')}）: {snippet}")
        if len(matches) > MODEL_RESULT_LIMIT:
            lines.append("完整命中列表已放入 ui_hint，最终回复不要逐条复述所有检索结果。")
        return "\n".join(lines)

    def _snippet(self, content: str, limit: int) -> str:
        snippet = content.replace("\n", " ")
        if len(snippet) > limit:
            return f"{snippet[:limit].rstrip()}..."
        return snippet
