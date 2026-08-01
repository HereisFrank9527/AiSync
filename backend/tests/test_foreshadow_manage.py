import asyncio
import json

from app.projects.context import ProjectContext
from app.tools.foreshadow_manage import ForeshadowManageTool


def run(coro):
    return asyncio.run(coro)


def write_ledger(tmp_path, items):
    path = tmp_path / "plot" / "foreshadows.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return path


def test_foreshadow_manage_is_read_only_and_reports_empty_ledger(tmp_path):
    tool = ForeshadowManageTool()
    context = ProjectContext(tmp_path)

    result = run(tool.execute({"intent": "梳理未回收伏笔"}, context))

    assert tool.write_policy == "none"
    assert tool.file_access().write == []
    assert "没有结构化伏笔记录" in result.content
    assert result.ui_hint["type"] == "list:foreshadows"
    assert result.ui_hint["data"]["items"] == []
    assert not (tmp_path / "plot" / "foreshadows.json").exists()


def test_foreshadow_manage_returns_active_items_without_writing(tmp_path):
    tool = ForeshadowManageTool()
    ledger = write_ledger(
        tmp_path,
        [
            {
                "id": "foreshadow-key",
                "title": "地下门后的冷光",
                "summary": "主角在第一章发现门后仍有能源波动。",
                "status": "planted",
                "importance": "major",
                "plant_chapter": "chapters/vol-01/chapter-001.md",
                "tags": ["能源", "地下设施"],
            },
            {
                "id": "foreshadow-done",
                "title": "已经回收的旧线索",
                "summary": "这条线索已经完成。",
                "status": "paid_off",
                "importance": "medium",
                "payoff_chapter": "chapters/vol-01/chapter-003.md",
            },
        ],
    )
    before = ledger.read_text(encoding="utf-8")

    result = run(tool.execute({"intent": "梳理未回收伏笔"}, ProjectContext(tmp_path)))

    assert "地下门后的冷光" in result.content
    assert "已经回收的旧线索" not in result.content
    assert result.metadata["active_count"] == 1
    assert result.ui_hint["data"]["items"][0]["id"] == "foreshadow-key"
    assert ledger.read_text(encoding="utf-8") == before


def test_foreshadow_manage_matches_chapter_and_explains_reason(tmp_path):
    write_ledger(
        tmp_path,
        [
            {
                "id": "foreshadow-key",
                "title": "地下门后的冷光",
                "summary": "主角在第一章发现门后仍有能源波动。",
                "status": "planted",
                "importance": "major",
                "plant_chapter": "chapters/vol-01/chapter-001.md",
                "related_files": ["chapters/vol-01/chapter-002.md"],
            },
            {
                "id": "foreshadow-other",
                "title": "远处的钟声",
                "summary": "城市废墟深处传来钟声。",
                "status": "developing",
                "importance": "minor",
            },
        ],
    )

    result = run(
        ForeshadowManageTool().execute(
            {"intent": "检查 chapters/vol-01/chapter-002.md 相关伏笔"},
            ProjectContext(tmp_path),
        )
    )

    item = result.ui_hint["data"]["items"][0]
    assert item["id"] == "foreshadow-key"
    assert "相关文件包含目标章节" in item["reasons"]
    assert item["action"] in {"推进", "参考"}
    assert result.metadata["mode"] == "matched"


def test_foreshadow_manage_limits_results(tmp_path):
    write_ledger(
        tmp_path,
        [
            {
                "id": f"foreshadow-{index}",
                "title": f"线索 {index}",
                "summary": "尚未回收。",
                "status": "planned",
                "importance": "medium",
            }
            for index in range(5)
        ],
    )

    result = run(
        ForeshadowManageTool().execute(
            {"intent": "未回收伏笔", "limit": 2},
            ProjectContext(tmp_path),
        )
    )

    assert len(result.ui_hint["data"]["items"]) == 2
    assert result.metadata["active_count"] == 5
