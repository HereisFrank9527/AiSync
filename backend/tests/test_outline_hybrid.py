import pytest

from app.projects.context import ProjectContext
from app.projects.outline import build_outline_index, refresh_outline_index


def test_hybrid_outline_preserves_sections_tables_and_chapter_nodes():
    content = """# 小说大纲

## 作品定位

| 项目 | 内容 |
| --- | --- |
| 类型 | 科幻 |

## 第一卷：启程

### 核心问题

主角是否愿意承担责任？

第 1 章：坐标之外

主角抵达异界。
"""

    data = build_outline_index(content)

    assert data["version"] == 3
    assert data["title"] == "小说大纲"
    assert [node["kind"] for node in data["nodes"]] == ["section", "volume", "section", "chapter"]
    assert "| 类型 | 科幻 |" in data["nodes"][0]["body"]
    assert data["nodes"][2]["parent_id"] == data["nodes"][1]["id"]
    assert data["items"][0]["title"] == "坐标之外"
    assert "status" not in data["nodes"][0]
    assert data["nodes"][3]["status"] == "planned"


def test_hybrid_outline_ignores_chapter_like_text_inside_code_fence():
    content = """# 大纲

```text
第 99 章：代码示例
```

第 1 章：正式章节

正文。
"""

    data = build_outline_index(content)

    assert [item["title"] for item in data["items"]] == ["正式章节"]


def test_hybrid_outline_does_not_treat_chapter_prefixed_prose_as_heading():
    content = """# 大纲

## 第一卷 风起

### 卷内节奏说明
第一章负责引出密信，第二章开始进入山门调查。

### 第二章 山门旧事

主角前往山门查证密信来源。
"""

    data = build_outline_index(content)

    assert [node["kind"] for node in data["nodes"]] == ["volume", "section", "chapter"]
    assert data["nodes"][1]["body"] == "第一章负责引出密信，第二章开始进入山门调查。"
    assert [item["title"] for item in data["items"]] == ["山门旧事"]


def test_hybrid_outline_keeps_previous_chapter_identity_and_status_after_rename():
    previous = {
        "nodes": [
            {
                "id": "stable-chapter-id",
                "kind": "chapter",
                "chapter_number": "1",
                "heading": "第 1 章：旧标题",
                "status": "done",
            }
        ]
    }

    data = build_outline_index("# 大纲\n\n第 1 章：新标题\n\n新版正文。\n", previous)

    assert data["items"][0]["id"] == "stable-chapter-id"
    assert data["items"][0]["status"] == "done"


@pytest.mark.asyncio
async def test_refresh_outline_index_writes_derived_json_without_changing_markdown(tmp_path):
    context = ProjectContext(tmp_path)
    content = "# 大纲\n\n## 特殊说明\n\n保留原文。\n\n第 1 章：开端\n\n正文。\n"
    await context.write_text("plot/outline.md", content)

    data = await refresh_outline_index(context)

    assert await context.read_text("plot/outline.md") == content
    stored = await context.read_json("plot/outline.json")
    assert stored["source_hash"] == data["source_hash"]
    assert stored["nodes"][0]["kind"] == "section"
    assert stored["items"][0]["title"] == "开端"
