import asyncio

import app.tools.search_project as search_project_module
from app.projects.context import ProjectContext
from app.tools.search_project import SearchProjectTool


class FakeVectorStore:
    def __init__(self, context):
        self.context = context

    async def query(self, text, collections=None, top_k=10):
        return [
            {
                "path": f"world/item-{index}.md",
                "collection": "world",
                "content": f"第 {index} 条设定。" + ("很长的内容" * 80),
                "score": round(0.9 - index * 0.01, 4),
            }
            for index in range(5)
        ]


def test_search_project_keeps_ui_results_but_compacts_model_content(tmp_path, monkeypatch):
    monkeypatch.setattr(search_project_module, "ProjectVectorStore", FakeVectorStore)
    tool = SearchProjectTool()

    result = asyncio.run(tool.execute({"query": "方舟", "limit": 5}, ProjectContext(tmp_path)))

    assert result.metadata["result_count"] == 5
    assert result.metadata["model_result_count"] == 3
    assert result.ui_hint is not None
    assert result.ui_hint["type"] == "list:search_results"
    assert len(result.ui_hint["data"]) == 5
    assert "命中 5 个项目片段" in result.content
    assert "world/item-0.md" in result.content
    assert "world/item-3.md" not in result.content
    assert "完整命中列表已放入 ui_hint" in result.content
