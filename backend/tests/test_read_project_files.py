import pytest

from app.projects.context import ProjectContext
from app.tools.read_project_files import MAX_LINES_PER_SELECTION, ReadProjectFilesTool


@pytest.mark.asyncio
async def test_read_project_files_inspect_reports_lines_and_markdown_headings(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text(
        "plot/outline.md",
        "# 总纲\n\n开场说明\n\n## 第一幕\n内容一\n\n### 转折\n内容二\n",
    )

    result = await ReadProjectFilesTool().execute(
        {"mode": "inspect", "paths": ["plot/outline.md"]},
        context,
    )

    assert result.metadata["mode"] == "inspect"
    assert result.metadata["files"][0]["line_count"] == 9
    assert result.metadata["files"][0]["headings"] == [
        {"line": 1, "level": 1, "title": "总纲"},
        {"line": 5, "level": 2, "title": "第一幕"},
        {"line": 8, "level": 3, "title": "转折"},
    ]
    assert "L5 ## 第一幕" in result.content
    outline_nodes = result.metadata["files"][0]["outline_nodes"]
    assert [(node["kind"], node["source_start_line"], node["source_end_line"]) for node in outline_nodes] == [
        ("markdown", 2, 4),
        ("section", 5, 7),
        ("section", 8, 9),
    ]
    assert outline_nodes[1]["id"] in result.content
    assert "大纲区块（局部修改时使用区块 ID 和行范围）" in result.content


@pytest.mark.asyncio
async def test_read_project_files_returns_only_selected_numbered_lines(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text(
        "chapters/vol-01/ch-001.md",
        "第一行\n第二行\n第三行\n第四行\n第五行\n第六行\n",
    )

    result = await ReadProjectFilesTool().execute(
        {
            "mode": "content",
            "selections": [
                {
                    "path": "chapters/vol-01/ch-001.md",
                    "start_line": 3,
                    "end_line": 5,
                }
            ],
        },
        context,
    )

    assert "     3 | 第三行" in result.content
    assert "     5 | 第五行" in result.content
    assert "第一行" not in result.content
    assert "第六行" not in result.content
    selection = result.metadata["selections"][0]
    assert selection["line_count"] == 6
    assert selection["returned_end_line"] == 5
    assert selection["truncated"] is False


@pytest.mark.asyncio
async def test_read_project_files_full_path_keeps_raw_content_compatibility(tmp_path):
    context = ProjectContext(tmp_path)
    content = "# 角色\n\n姓名：林铎\n"
    await context.write_text("characters/lin-duo/profile.md", content)

    result = await ReadProjectFilesTool().execute(
        {"paths": ["characters/lin-duo/profile.md"]},
        context,
    )

    assert content in result.content
    assert "     1 |" not in result.content
    assert result.metadata["mode"] == "content"


@pytest.mark.asyncio
async def test_read_project_files_rejects_invalid_or_oversized_ranges(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text("plot/outline.md", "一\n二\n")
    tool = ReadProjectFilesTool()

    with pytest.raises(ValueError, match="invalid"):
        await tool.execute(
            {
                "selections": [
                    {"path": "plot/outline.md", "start_line": 2, "end_line": 1}
                ]
            },
            context,
        )

    with pytest.raises(ValueError, match="最多"):
        await tool.execute(
            {
                "selections": [
                    {
                        "path": "plot/outline.md",
                        "start_line": 1,
                        "end_line": MAX_LINES_PER_SELECTION + 1,
                    }
                ]
            },
            context,
        )
