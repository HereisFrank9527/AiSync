from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolResult


class SearchProjectTool(BaseTool):
    name = "search_project"
    description = "Search project text files by a keyword or phrase."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword or phrase to search for."},
                "limit": {"type": "integer", "description": "Maximum number of matching files."},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        query = str(params["query"]).lower()
        limit = int(params.get("limit", 10))
        matches: list[dict[str, Any]] = []

        for file_path in await context.list_files():
            if len(matches) >= limit:
                break
            if not file_path.endswith((".md", ".txt", ".yaml", ".yml", ".json")):
                continue
            try:
                content = await context.read_text(file_path)
            except UnicodeDecodeError:
                continue
            index = content.lower().find(query)
            if index == -1:
                continue
            start = max(0, index - 80)
            end = min(len(content), index + len(query) + 80)
            matches.append({"path": file_path, "snippet": content[start:end].replace("\n", " ")})

        if not matches:
            return ToolResult(content=f"No matches found for: {params['query']}", ui_hint={"type": "list:search_results", "data": []})

        content = "\n".join(f"- {item['path']}: {item['snippet']}" for item in matches)
        return ToolResult(content=content, ui_hint={"type": "list:search_results", "data": matches})
