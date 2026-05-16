import pytest

from app.api.projects import build_project_overview
from app.api.story import (
    OutlineItem,
    normalize_chapter_metadata,
    normalize_outline_items,
    normalize_worldview_path,
    read_chapter_metadata,
    write_chapter_metadata,
)
from app.projects.context import ProjectContext
from app.projects.foreshadows import foreshadow_context_for_prompt


def test_normalize_outline_items_adds_ids_and_statuses():
    items = normalize_outline_items([
        OutlineItem(title="开端", summary="主角登场", status="done"),
        OutlineItem(id="custom-id", title="冲突", status="invalid"),
    ])

    assert items == [
        {
            "id": "outline-1",
            "index": 1,
            "title": "开端",
            "summary": "主角登场",
            "status": "done",
        },
        {
            "id": "custom-id",
            "index": 2,
            "title": "冲突",
            "summary": "",
            "status": "planned",
        },
    ]


def test_normalize_chapter_metadata_keeps_outline_id():
    metadata = normalize_chapter_metadata(
        {
            "status": "revising",
            "summary": "第二版",
            "target_characters": "3000",
            "revision": "2",
            "outline_id": "outline-2",
        },
        "fallback",
    )

    assert metadata["outline_id"] == "outline-2"
    assert metadata["target_characters"] == 3000
    assert metadata["revision"] == 2


def test_normalize_worldview_path_accepts_only_world_markdown():
    assert normalize_worldview_path("world\\geography.md") == "world/geography.md"

    with pytest.raises(Exception):
        normalize_worldview_path("chapters/geography.md")

    with pytest.raises(Exception):
        normalize_worldview_path("world/../secrets.md")


@pytest.mark.asyncio
async def test_project_context_move_and_delete_file(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text("world/old.md", "# 旧文档\n")

    await context.move_file("world/old.md", "world/new.md")

    assert not await context.exists("world/old.md")
    assert await context.read_text("world/new.md") == "# 旧文档\n"

    await context.delete_file("world/new.md")

    assert not await context.exists("world/new.md")


@pytest.mark.asyncio
async def test_chapter_metadata_roundtrip_outline_id(tmp_path):
    context = ProjectContext(tmp_path)
    await write_chapter_metadata(
        context,
        "chapters/vol-01/ch-001.md",
        {
            "status": "draft",
            "summary": "摘要",
            "target_characters": 1200,
            "revision": 1,
            "outline_id": "outline-1",
        },
    )

    metadata = await read_chapter_metadata(context, "chapters/vol-01/ch-001.md")

    assert metadata["outline_id"] == "outline-1"
    assert metadata["summary"] == "摘要"


@pytest.mark.asyncio
async def test_project_overview_counts_completed_outline_items(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_yaml("project.yaml", {"name": "测试小说"})
    await context.write_json(
        "plot/outline.json",
        {
            "title": "大纲",
            "items": [
                {"id": "outline-1", "title": "开端", "status": "done"},
                {"id": "outline-2", "title": "发展", "status": "draft"},
            ],
        },
    )

    overview = await build_project_overview(context)

    assert overview["stats"]["outline_items"] == 2
    assert overview["stats"]["completed_outline_items"] == 1
    assert overview["stats"]["outline_progress"] == 0.5


@pytest.mark.asyncio
async def test_foreshadow_context_matches_chapter_path(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_json(
        "plot/foreshadows.json",
        {
            "items": [
                {
                    "id": "f1",
                    "title": "灰塔梦境",
                    "summary": "梦境最终指向方舟节点。",
                    "status": "planted",
                    "importance": "major",
                    "payoff_chapter": "chapters/vol-01/ch-003.md",
                }
            ],
        },
    )

    content = await foreshadow_context_for_prompt(context, "续写 chapters/vol-01/ch-003.md")

    assert "灰塔梦境" in content
    assert "回收：chapters/vol-01/ch-003.md" in content
    assert "建议：优先回收" in content
    assert "命中：目标章节是回收章节" in content


@pytest.mark.asyncio
async def test_foreshadow_context_uses_chapter_outline_metadata(tmp_path):
    context = ProjectContext(tmp_path)
    await write_chapter_metadata(
        context,
        "chapters/vol-01/ch-004.md",
        {
            "status": "draft",
            "summary": "",
            "target_characters": 0,
            "revision": 0,
            "outline_id": "outline-4",
        },
    )
    await context.write_json(
        "plot/foreshadows.json",
        {
            "items": [
                {
                    "id": "f2",
                    "title": "密钥残响",
                    "summary": "同一大纲节点下需要推进的主线伏笔。",
                    "status": "developing",
                    "importance": "major",
                    "outline_ids": ["outline-4"],
                }
            ],
        },
    )

    content = await foreshadow_context_for_prompt(context, "写 chapters/vol-01/ch-004.md")

    assert "密钥残响" in content
    assert "大纲：outline-4" in content
    assert "命中：关联同一大纲节点" in content


@pytest.mark.asyncio
async def test_foreshadow_context_falls_back_to_open_major_items(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_json(
        "plot/foreshadows.json",
        {
            "items": [
                {
                    "id": "f3",
                    "title": "未回收主线伏笔",
                    "summary": "没有明确命中时也应给出关键未回收伏笔。",
                    "status": "planned",
                    "importance": "major",
                }
            ],
        },
    )

    content = await foreshadow_context_for_prompt(context, "帮我写一章")

    assert "未回收主线伏笔" in content
