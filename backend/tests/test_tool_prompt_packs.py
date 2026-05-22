from app.core import prompt_pack_rendering
from app.core.prompt_packs import PromptPackCreate, PromptPackStore
from app.projects.context import ProjectContext
from app.tools.edit_chapter import EditChapterTool
from app.tools.write_chapter import WriteChapterTool


def test_write_chapter_prompt_includes_chapter_draft_prompt_pack(tmp_path, monkeypatch):
    store = PromptPackStore(tmp_path / "prompt_packs.json")
    store.create(
        PromptPackCreate(
            name="章节草稿规则",
            category="writing",
            stages=["chapter_draft"],
            content="场景推进要清楚。",
        )
    )
    store.create(
        PromptPackCreate(
            name="润色规则",
            category="revision",
            stages=["revision"],
            content="只改语言，不改事实。",
        )
    )
    monkeypatch.setattr(prompt_pack_rendering, "prompt_pack_store", store)

    prompt = WriteChapterTool().build_prompt({"path": "chapters/vol-01/ch-001.md"})

    assert "提示词包：章节草稿规则" in prompt
    assert "场景推进要清楚。" in prompt
    assert "润色规则" not in prompt


def test_edit_chapter_prompt_includes_revision_prompt_pack(tmp_path, monkeypatch):
    store = PromptPackStore(tmp_path / "prompt_packs.json")
    store.create(
        PromptPackCreate(
            name="章节草稿规则",
            category="writing",
            stages=["chapter_draft"],
            content="场景推进要清楚。",
        )
    )
    store.create(
        PromptPackCreate(
            name="润色规则",
            category="revision",
            stages=["revision"],
            content="只改语言，不改事实。",
        )
    )
    monkeypatch.setattr(prompt_pack_rendering, "prompt_pack_store", store)

    prompt = EditChapterTool().build_prompt({"path": "chapters/vol-01/ch-001.md", "mode": "replace"})

    assert "提示词包：润色规则" in prompt
    assert "只改语言，不改事实。" in prompt
    assert "章节草稿规则" not in prompt


def test_tool_prompt_pack_metadata_uses_stage(tmp_path, monkeypatch):
    store = PromptPackStore(tmp_path / "prompt_packs.json")
    pack = store.create(
        PromptPackCreate(
            name="章节草稿规则",
            category="writing",
            stages=["chapter_draft"],
            content="场景推进要清楚。",
        )
    )
    monkeypatch.setattr(prompt_pack_rendering, "prompt_pack_store", store)

    metadata = WriteChapterTool().prompt_pack_metadata()

    assert metadata == {
        "stages": ["chapter_draft"],
        "count": 1,
        "ids": [pack.id],
        "names": ["章节草稿规则"],
        "categories": ["writing"],
    }


async def test_project_prompt_pack_settings_filter_tool_prompt(tmp_path, monkeypatch):
    store = PromptPackStore(tmp_path / "prompt_packs.json")
    selected = store.create(
        PromptPackCreate(
            name="本项目文风",
            category="style",
            stages=["chapter_draft"],
            content="使用本项目的冷峻文风。",
        )
    )
    store.create(
        PromptPackCreate(
            name="其他项目文风",
            category="style",
            stages=["chapter_draft"],
            content="使用其他项目的轻松文风。",
        )
    )
    monkeypatch.setattr(prompt_pack_rendering, "prompt_pack_store", store)
    context = ProjectContext(tmp_path / "novel")
    await prompt_pack_rendering.save_project_prompt_pack_settings(context, "project", [selected.id])

    prompt = await WriteChapterTool().build_project_prompt({}, context)
    metadata = await WriteChapterTool().project_prompt_pack_metadata(context)

    assert "本项目文风" in prompt
    assert "其他项目文风" not in prompt
    assert metadata is not None
    assert metadata["names"] == ["本项目文风"]


async def test_global_project_prompt_pack_settings_keep_existing_behavior(tmp_path, monkeypatch):
    store = PromptPackStore(tmp_path / "prompt_packs.json")
    store.create(
        PromptPackCreate(
            name="全局章节规则",
            category="writing",
            stages=["chapter_draft"],
            content="按全局章节规则写。",
        )
    )
    monkeypatch.setattr(prompt_pack_rendering, "prompt_pack_store", store)
    context = ProjectContext(tmp_path / "novel")
    await prompt_pack_rendering.save_project_prompt_pack_settings(context, "global", [])

    prompt = await WriteChapterTool().build_project_prompt({}, context)

    assert "全局章节规则" in prompt
