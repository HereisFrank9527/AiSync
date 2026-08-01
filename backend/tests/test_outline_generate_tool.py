import asyncio

import pytest

from app.projects.context import ProjectContext
from app.tools.outline_generate import OutlineGenerateTool


def run(coro):
    return asyncio.run(coro)


def test_outline_generate_requires_formal_content_and_does_not_write_requirements(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        await context.write_text("plot/outline.md", "# 正式大纲\n\n旧正文\n")
        tool = OutlineGenerateTool()

        with pytest.raises(ValueError):
            await tool.execute(
                {
                    "mode": "prepend",
                    "target_chapter_count": 500,
                    "requirements": "清理 plot/outline.md：删除旧权限来源说明。",
                },
                context,
            )

        assert await context.read_text("plot/outline.md") == "# 正式大纲\n\n旧正文\n"

    run(scenario())


def test_outline_generate_writes_only_provided_outline_content(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        await context.write_text("plot/outline.md", "# 正式大纲\n\n旧正文\n")
        tool = OutlineGenerateTool()

        await tool.execute(
            {
                "mode": "prepend",
                "requirements": "清理要求不应写入正文。",
                "content": "## 第一卷\n\n### 第 1 章\n\n正式剧情节点。\n",
            },
            context,
        )

        updated = await context.read_text("plot/outline.md")
        assert "正式剧情节点" in updated
        assert "清理要求不应写入正文" not in updated
        assert "旧正文" in updated

        history_files = await context.list_files(".aisync/outline_history")
        assert len(history_files) == 1
        assert await context.read_text(history_files[0]) == "# 正式大纲\n\n旧正文\n"

    run(scenario())
