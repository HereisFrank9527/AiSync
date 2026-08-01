import io
import zipfile

import pytest
from fastapi import HTTPException

from app.api.projects import ProjectRenameRequest, build_project_overview, delete_project, export_project, import_project, is_safe_project_file, list_projects, normalize_project_relative_path, normalize_temp_path, rename_project, safe_zip_members
from app.api.story import (
    ChapterMetadataSaveRequest,
    ForeshadowItem,
    OutlineCharacterLinksSaveRequest,
    OutlineImportRequest,
    OutlineItem,
    OutlineSaveRequest,
    OutlineSourceSaveRequest,
    get_outline,
    import_outline_from_markdown,
    normalize_chapter_metadata,
    normalize_foreshadow_items,
    normalize_outline_items,
    normalize_worldview_path,
    read_chapter_metadata,
    save_outline,
    save_outline_character_links,
    save_outline_source,
    save_chapter_metadata,
    write_chapter_metadata,
)
from app.projects.context import ProjectContext
from app.projects.foreshadows import foreshadow_context_for_prompt
from app.projects.outline import chapter_outline_items_from_markdown


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
            "character_ids": [],
        },
        {
            "id": "custom-id",
            "index": 2,
            "title": "冲突",
            "summary": "",
            "status": "planned",
            "character_ids": [],
        },
    ]


def test_chapter_outline_import_ignores_freeform_sections():
    content = """# 大纲

## 卷二：三千年的浇铸
核心问题：协议是怎么被一代代铺出来的？

### A 线：历史回溯
- 战国末年她铸下青铜匣

第 7 章：涂瑶的名字
他通过噪声拼出第一个完整人名。

## 双线推进
这不是章节。

第 X 章：厄忍现身
厄忍揭示协议真相。
"""

    items = chapter_outline_items_from_markdown(content)

    assert [item["title"] for item in items] == ["涂瑶的名字", "厄忍现身"]
    assert items[0]["summary"] == "他通过噪声拼出第一个完整人名。"


def test_chapter_outline_import_ignores_chapter_prefixed_prose():
    content = """# 大纲

### 第一章 雨夜来客
正文。

第一章负责引出密信，第二章开始进入山门调查。

第 2 章：山门旧事
继续正文。
"""

    items = chapter_outline_items_from_markdown(content)

    assert [item["title"] for item in items] == ["雨夜来客", "山门旧事"]
    assert "第一章负责引出密信" in items[0]["summary"]


@pytest.mark.asyncio
async def test_import_outline_preserves_markdown_and_exposes_it_with_structured_data(tmp_path):
    context = ProjectContext(tmp_path)
    content = """# 自由格式大纲

## 核心问题

这段不是章节，但必须保留。

第 1 章：开端

主角抵达异界。
"""
    await context.write_text("plot/outline.md", content)

    imported = await import_outline_from_markdown(OutlineImportRequest(project_path=str(tmp_path)))
    loaded = await get_outline(project_path=str(tmp_path))

    assert await context.read_text("plot/outline.md") == content
    assert imported["raw_markdown_preserved"] is True
    assert imported["items"][0]["title"] == "开端"
    assert loaded["format"] == "hybrid"
    assert loaded["content"] == content
    assert loaded["content_source"] == "plot/outline.md"


@pytest.mark.asyncio
async def test_outline_source_save_snapshots_previous_markdown(tmp_path):
    context = ProjectContext(tmp_path)
    original = "# 原始大纲\n\n## 特殊结构\n\n不可丢失的说明。\n"
    await context.write_text("plot/outline.md", original)

    saved = await save_outline_source(
        OutlineSourceSaveRequest(
            project_path=str(tmp_path),
            content="# 结构化大纲\n\n第 1 章：开端\n\n主角登场\n",
        )
    )

    assert saved["snapshot_path"]
    assert await context.read_text(saved["snapshot_path"]) == original
    assert "第 1 章：开端" in await context.read_text("plot/outline.md")


@pytest.mark.asyncio
async def test_flat_outline_save_rejects_freeform_outline(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text("plot/outline.md", "# 原始大纲\n\n## 特殊结构\n\n不可丢失的说明。\n")

    with pytest.raises(HTTPException, match="自由格式大纲") as exc_info:
        await save_outline(
            OutlineSaveRequest(
                project_path=str(tmp_path),
                title="结构化大纲",
                items=[OutlineItem(title="开端", summary="主角登场")],
            )
        )
    assert exc_info.value.status_code == 409


def test_normalize_chapter_metadata_keeps_outline_id():
    metadata = normalize_chapter_metadata(
        {
            "status": "revising",
            "summary": "第二版",
            "target_characters": "3000",
            "revision": "2",
            "outline_id": "outline-2",
            "character_ids": ["char_1234567890abcdef1234", "bad-id"],
        },
        "fallback",
    )

    assert metadata["outline_id"] == "outline-2"
    assert metadata["target_characters"] == 3000
    assert metadata["revision"] == 2
    assert metadata["character_ids"] == ["char_1234567890abcdef1234"]


def test_normalize_foreshadow_items_keeps_character_ids():
    items = normalize_foreshadow_items([
        ForeshadowItem(
            title="旧日身份",
            character_ids=["char_1234567890abcdef1234", "bad-id"],
        )
    ])

    assert items[0]["character_ids"] == ["char_1234567890abcdef1234"]


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
async def test_project_init_creates_temp_workspace(tmp_path):
    context = ProjectContext(tmp_path)

    created = await context.init_structure()

    assert await context.exists("temp/inbox")
    assert await context.exists("temp/drafts")
    assert await context.exists("temp/exports")
    assert await context.exists("temp/notes")
    assert await context.exists("temp/.aisync-temp.json")
    assert "temp/.aisync-temp.json" in created
    metadata = await context.read_json("temp/.aisync-temp.json")
    assert metadata["version"] == 1
    assert metadata["items"] == []


def test_normalize_temp_path_limits_file_operations_to_temp():
    assert normalize_temp_path("temp/notes/a.md") == "temp/notes/a.md"
    assert normalize_temp_path("\\temp\\drafts\\b.txt") == "temp/drafts/b.txt"
    assert normalize_temp_path("temp/data/info.json") == "temp/data/info.json"

    with pytest.raises(Exception):
        normalize_temp_path("world/overview.md")

    with pytest.raises(Exception):
        normalize_temp_path("temp/../world/overview.md")

    with pytest.raises(Exception):
        normalize_temp_path("temp/.aisync-temp.json")

    with pytest.raises(Exception):
        normalize_temp_path("temp/scripts/run.py")

    with pytest.raises(Exception):
        normalize_temp_path("temp/bin/tool.exe")


def test_project_file_api_allows_only_safe_text_files():
    assert normalize_project_relative_path("world/overview.md") == "world/overview.md"
    assert normalize_project_relative_path("plot/outline.json") == "plot/outline.json"
    assert normalize_project_relative_path("temp/notes/free.txt") == "temp/notes/free.txt"
    assert is_safe_project_file("chapters/vol-01/ch-001.md")
    assert is_safe_project_file("temp/exports/table.csv")

    for path in [
        ".aisync/conversations/a.json",
        ".vectordb/chroma/data.json",
        "temp/.aisync-temp.json",
        "temp/scripts/run.py",
        "temp/bin/tool.exe",
        "assets/image.png",
        "world/.secret.md",
    ]:
        assert not is_safe_project_file(path)
        with pytest.raises(Exception):
            normalize_project_relative_path(path)


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
            "character_ids": ["char_1234567890abcdef1234"],
        },
    )

    metadata = await read_chapter_metadata(context, "chapters/vol-01/ch-001.md")

    assert metadata["outline_id"] == "outline-1"
    assert metadata["summary"] == "摘要"
    assert metadata["character_ids"] == ["char_1234567890abcdef1234"]


@pytest.mark.asyncio
async def test_outline_character_links_use_sidecar_without_rewriting_markdown(tmp_path):
    context = ProjectContext(tmp_path)
    character_id = "char_1234567890abcdef1234"
    await context.write_yaml(
        "characters/lin-duo/profile.yaml",
        {"schema_version": 3, "character_id": character_id, "slug": "lin-duo", "name": "林铎"},
    )
    content = "# 大纲\n\n第 1 章：开端\n\n林铎抵达灰烬平原。\n"
    await context.write_text("plot/outline.md", content)

    saved = await save_outline_character_links(
        OutlineCharacterLinksSaveRequest(
            project_path=str(tmp_path),
            node_id="outline-1",
            character_ids=[character_id],
        )
    )
    loaded = await get_outline(project_path=str(tmp_path))

    assert saved["character_ids"] == [character_id]
    assert await context.read_text("plot/outline.md") == content
    assert loaded["items"][0]["character_ids"] == [character_id]
    assert loaded["nodes"][0]["character_ids"] == [character_id]
    sidecar = await context.read_yaml("plot/outline-meta.yaml")
    assert sidecar["nodes"]["outline-1"]["character_ids"] == [character_id]


@pytest.mark.asyncio
async def test_chapter_metadata_endpoint_rejects_unknown_character_id(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text("chapters/vol-01/ch-001.md", "# 第一章\n")

    with pytest.raises(HTTPException, match="未知人物 ID") as exc_info:
        await save_chapter_metadata(
            ChapterMetadataSaveRequest(
                project_path=str(tmp_path),
                path="chapters/vol-01/ch-001.md",
                character_ids=["char_1234567890abcdef1234"],
            )
        )

    assert exc_info.value.status_code == 400


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
async def test_foreshadow_context_does_not_inject_unrelated_major_items(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_json(
        "plot/foreshadows.json",
        {
            "items": [
                {
                    "id": "f3",
                    "title": "未回收主线伏笔",
                    "summary": "仅在相关时注入的关键未回收伏笔。",
                    "status": "planned",
                    "importance": "major",
                }
            ],
        },
    )

    content = await foreshadow_context_for_prompt(context, "帮我写一章")

    assert content == ""


@pytest.mark.asyncio
async def test_managed_project_import_export_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.projects.settings.projects_root", str(tmp_path / "library"))
    source = ProjectContext(tmp_path / "source")
    await source.init_structure()
    await source.write_yaml("project.yaml", {"name": "导入测试"})
    await source.write_text("chapters/vol-01/ch-001.md", "# 第一章\n正文\n")

    response = await export_project(str(source.root))
    imported = await import_project(response.body, name="导入副本")
    projects = await list_projects()

    assert imported["name"] == "导入副本"
    assert imported["path"].startswith(str(tmp_path / "library"))
    assert any(project["path"] == imported["path"] for project in projects)
    imported_context = ProjectContext(imported["path"])
    assert await imported_context.read_text("chapters/vol-01/ch-001.md") == "# 第一章\n正文\n"


def test_import_zip_rejects_path_traversal():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../evil.md", "bad")

    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
        with pytest.raises(Exception):
            safe_zip_members(archive)


@pytest.mark.asyncio
async def test_managed_project_rename_and_delete_are_library_scoped(tmp_path, monkeypatch):
    library = tmp_path / "library"
    monkeypatch.setattr("app.api.projects.settings.projects_root", str(library))
    context = ProjectContext(library / "demo")
    await context.init_structure()
    await context.write_yaml("project.yaml", {"name": "旧名"})

    renamed = await rename_project(ProjectRenameRequest(project_path=str(context.root), name="新名"))
    assert renamed["name"] == "新名"

    external = ProjectContext(tmp_path / "external")
    await external.init_structure()
    with pytest.raises(Exception):
        await delete_project(str(external.root))

    deleted = await delete_project(str(context.root))
    assert deleted["status"] == "deleted"
    assert not context.root.exists()
