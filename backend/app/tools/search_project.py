from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult
from app.vector.store import ProjectVectorStore


class SearchProjectTool(BaseTool):
    name = "search_project"
    description = "按关键词或短语搜索项目文本文件。"

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

        rendered = []
        ui_items: list[dict[str, Any]] = []
        for item in matches:
            snippet = str(item["content"]).replace("\n", " ")
            if len(snippet) > 220:
                snippet = f"{snippet[:220].rstrip()}..."
            rendered.append(f"- {item['path']}（{item['score']}）: {snippet}")
            ui_items.append({
                "path": item["path"],
                "snippet": snippet,
                "score": item["score"],
                "collection": item["collection"],
            })
        return ToolResult(content="\n".join(rendered), ui_hint={"type": "list:search_results", "data": ui_items})
