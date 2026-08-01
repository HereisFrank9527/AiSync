import pytest

from app.change_sets import apply_change_set
from app.projects.context import ProjectContext
from app.projects.facts import (
    MAX_FACTS_PER_CHAPTER,
    chapter_fact_document,
    chapter_fact_path,
    normalize_fact_records,
)
from app.tools.edit_chapter import EditChapterTool
from app.tools.write_chapter import WriteChapterTool
from app.vector.store import ProjectVectorStore


CHAPTER_PATH = "chapters/vol-01/ch-001.md"
FACT_PATH = "plot/facts/vol-01/ch-001.json"


def fact_record(**overrides):
    record = {
        "category": "state",
        "subject": "门禁",
        "predicate": "能源状态",
        "value": "断电后短暂亮起",
        "evidence": "门禁亮了一下。",
        "certainty": "confirmed",
        "time": "第一章结尾",
        "tags": ["门禁", "零号通行证", "门禁"],
    }
    record.update(overrides)
    return record


def test_chapter_fact_path_mirrors_chapter_directory():
    assert chapter_fact_path(CHAPTER_PATH) == FACT_PATH
    assert chapter_fact_path("chapters/ch-002.md") == "plot/facts/ch-002.json"


@pytest.mark.parametrize(
    "path",
    [
        "world/overview.md",
        "chapters/vol-01/ch-001.txt",
        "chapters/../world/overview.md",
    ],
)
def test_chapter_fact_path_rejects_non_chapter_paths(path):
    with pytest.raises(ValueError, match="chapters"):
        chapter_fact_path(path)


def test_normalize_fact_records_is_deterministic_and_deduplicates():
    raw = fact_record(subject="  门禁  ", evidence="门禁\n亮了一下。")

    first = normalize_fact_records([raw, raw], CHAPTER_PATH)
    second = normalize_fact_records([raw], CHAPTER_PATH)

    assert first == second
    assert len(first) == 1
    assert first[0]["id"].startswith("fact-")
    assert first[0]["subject"] == "门禁"
    assert first[0]["evidence"] == "门禁 亮了一下。"
    assert first[0]["tags"] == ["门禁", "零号通行证"]
    assert first[0]["source_path"] == CHAPTER_PATH


def test_normalize_fact_records_rejects_too_many_items():
    records = [fact_record(value=f"状态 {index}") for index in range(MAX_FACTS_PER_CHAPTER + 1)]

    with pytest.raises(ValueError, match="最多记录"):
        normalize_fact_records(records, CHAPTER_PATH)


@pytest.mark.parametrize("missing", ["subject", "predicate", "value", "evidence"])
def test_normalize_fact_records_requires_core_fields(missing):
    record = fact_record()
    record[missing] = ""

    with pytest.raises(ValueError, match="requires subject"):
        normalize_fact_records([record], CHAPTER_PATH)


@pytest.mark.asyncio
async def test_write_chapter_proposes_chapter_and_fact_snapshot_together(tmp_path):
    context = ProjectContext(tmp_path)
    result = await WriteChapterTool().execute(
        {
            "path": CHAPTER_PATH,
            "content": "# 第一章\n\n门禁亮了一下。\n",
            "fact_records": [fact_record()],
        },
        context,
    )

    assert result.ui_hint is not None
    assert result.ui_hint["type"] == "changeset:proposal"
    assert result.metadata["paths"] == [CHAPTER_PATH, FACT_PATH]
    assert result.metadata["fact_records"][0]["subject"] == "门禁"
    assert not await context.exists(CHAPTER_PATH)
    assert not await context.exists(FACT_PATH)

    await apply_change_set(context, result.metadata["changeset_id"])

    assert await context.read_text(CHAPTER_PATH) == "# 第一章\n\n门禁亮了一下。\n"
    document = await context.read_json(FACT_PATH)
    assert document["chapter_path"] == CHAPTER_PATH
    assert document["facts"] == result.metadata["fact_records"]


@pytest.mark.asyncio
async def test_edit_chapter_explicit_empty_facts_clears_existing_snapshot(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text(CHAPTER_PATH, "# 第一章\n旧内容\n")
    existing = normalize_fact_records([fact_record()], CHAPTER_PATH)
    await context.write_json(FACT_PATH, chapter_fact_document(CHAPTER_PATH, existing))

    result = await EditChapterTool().execute(
        {
            "path": CHAPTER_PATH,
            "content": "# 第一章\n新内容\n",
            "mode": "replace",
            "fact_records": [],
        },
        context,
    )

    assert result.ui_hint is not None
    assert result.ui_hint["type"] == "changeset:proposal"
    assert result.metadata["fact_records"] == []
    assert await context.read_text(CHAPTER_PATH) == "# 第一章\n旧内容\n"

    await apply_change_set(context, result.metadata["changeset_id"])

    assert await context.read_text(CHAPTER_PATH) == "# 第一章\n新内容\n"
    assert (await context.read_json(FACT_PATH))["facts"] == []


@pytest.mark.asyncio
async def test_edit_chapter_without_fact_records_keeps_direct_write_and_old_snapshot(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text(CHAPTER_PATH, "# 第一章\n旧内容\n")
    existing = normalize_fact_records([fact_record()], CHAPTER_PATH)
    await context.write_json(FACT_PATH, chapter_fact_document(CHAPTER_PATH, existing))

    result = await EditChapterTool().execute(
        {
            "path": CHAPTER_PATH,
            "content": "# 第一章\n新内容\n",
            "mode": "replace",
        },
        context,
    )

    assert result.ui_hint is not None
    assert result.ui_hint["type"] == "stream:editor"
    assert await context.read_text(CHAPTER_PATH) == "# 第一章\n新内容\n"
    assert (await context.read_json(FACT_PATH))["facts"] == existing


@pytest.mark.asyncio
async def test_fact_snapshot_is_available_to_project_vector_search(tmp_path):
    context = ProjectContext(tmp_path)
    facts = normalize_fact_records([fact_record()], CHAPTER_PATH)
    await context.write_json(FACT_PATH, chapter_fact_document(CHAPTER_PATH, facts))

    results = await ProjectVectorStore(context).query_exact_terms(["零号通行证"], top_k=5)

    assert results
    assert results[0]["path"] == FACT_PATH
    assert results[0]["collection"] == "plot"
