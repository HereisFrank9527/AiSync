import asyncio

import pytest

from app.agent import MasterAgent
from app.change_approvals import resolve_change_set_decision
from app.change_sets import apply_change_set
from app.llm.types import ChatRequest, ChatResponse
from app.projects.context import ProjectContext
from app.projects.foreshadows import (
    apply_foreshadow_actions,
    confirm_foreshadow_verification,
    persist_foreshadow_verification,
    verify_foreshadow_actions,
)
from app.tools.registry import ToolRegistry
from app.tools.edit_chapter import EditChapterTool
from app.tools.write_chapter import WriteChapterTool


def test_foreshadow_actions_create_and_progress_records():
    records, applied = apply_foreshadow_actions(
        [],
        [
            {
                "action": "plant",
                "title": "地下设施的异常响应",
                "summary": "门禁在断电后仍识别出一段未知权限信号。",
                "payoff_chapter": "chapters/vol-01/ch-010.md",
                "evidence": "门禁屏幕短暂显示未知权限。",
                "tags": ["权限", "设施"],
            }
        ],
        "chapters/vol-01/ch-001.md",
    )

    assert len(records) == 1
    assert applied[0]["action"] == "plant"
    foreshadow_id = records[0]["id"]
    assert records[0]["status"] == "planted"
    assert records[0]["plant_chapter"] == "chapters/vol-01/ch-001.md"

    records, applied = apply_foreshadow_actions(
        records,
        [
            {
                "action": "payoff",
                "foreshadow_id": foreshadow_id,
                "evidence": "主角确认这段信号来自火种名册。",
            }
        ],
        "chapters/vol-01/ch-010.md",
    )

    assert applied[0]["status"] == "paid_off"
    assert records[0]["payoff_chapter"] == "chapters/vol-01/ch-010.md"
    assert "火种名册" in records[0]["notes"]


@pytest.mark.asyncio
async def test_verify_foreshadow_actions_marks_exact_evidence_verified(tmp_path):
    context = ProjectContext(tmp_path)
    chapter_path = "chapters/vol-01/ch-001.md"
    evidence = "门禁屏幕显示未知权限。"
    records, applied = apply_foreshadow_actions(
        [],
        [{"action": "plant", "title": "门禁异常", "summary": "门禁出现未知权限。", "evidence": evidence}],
        chapter_path,
    )
    await context.write_text(chapter_path, f"# 第一章\n{evidence}\n")
    await context.write_json("plot/foreshadows.json", {"items": records})

    verification = await verify_foreshadow_actions(context, applied)

    assert verification == [{
        "action": "plant",
        "foreshadow_id": applied[0]["foreshadow_id"],
        "chapter_path": chapter_path,
        "status": "verified",
        "evidence_match": True,
        "issues": [],
    }]


@pytest.mark.asyncio
async def test_verify_foreshadow_actions_marks_missing_evidence_for_review(tmp_path):
    context = ProjectContext(tmp_path)
    chapter_path = "chapters/vol-01/ch-001.md"
    records, applied = apply_foreshadow_actions(
        [],
        [{"action": "plant", "title": "门禁异常", "summary": "门禁出现未知权限。", "evidence": "屏幕显示未知权限。"}],
        chapter_path,
    )
    await context.write_text(chapter_path, "# 第一章\n门禁亮了一下。\n")
    await context.write_json("plot/foreshadows.json", {"items": records})

    verification = await verify_foreshadow_actions(context, applied)

    assert verification[0]["status"] == "review"
    assert verification[0]["evidence_match"] is False
    assert "正文中未找到足够匹配的证据" in verification[0]["issues"]


@pytest.mark.asyncio
async def test_persist_and_confirm_foreshadow_verification(tmp_path):
    context = ProjectContext(tmp_path)
    chapter_path = "chapters/vol-01/ch-001.md"
    records, applied = apply_foreshadow_actions(
        [],
        [{"action": "plant", "title": "门禁异常", "summary": "门禁出现未知权限。", "evidence": "缺失证据。"}],
        chapter_path,
    )
    await context.write_text(chapter_path, "# 第一章\n门禁亮了一下。\n")
    await context.write_json("plot/foreshadows.json", {"items": records})
    verification = await verify_foreshadow_actions(context, applied)

    await persist_foreshadow_verification(context, verification)
    stored = (await context.read_json("plot/foreshadows.json"))["items"][0]["verification"]
    assert stored["status"] == "review"
    assert stored["chapter_path"] == chapter_path
    assert stored["issues"]

    await confirm_foreshadow_verification(context, applied[0]["foreshadow_id"], "人工确认该证据可接受")
    confirmed = (await context.read_json("plot/foreshadows.json"))["items"][0]["verification"]
    assert confirmed["status"] == "confirmed"
    assert confirmed["note"] == "人工确认该证据可接受"


@pytest.mark.asyncio
async def test_write_chapter_proposes_joint_chapter_and_foreshadow_change(tmp_path):
    context = ProjectContext(tmp_path)
    result = await WriteChapterTool().execute(
        {
            "path": "chapters/vol-01/ch-001.md",
            "content": "# 第一章\n\n门禁亮了一下。\n",
            "foreshadow_actions": [
                {
                    "action": "plant",
                    "title": "门禁的未知权限",
                    "summary": "门禁在断电后仍识别出未知权限。",
                    "payoff_chapter": "chapters/vol-01/ch-010.md",
                    "evidence": "门禁屏幕显示未知权限。",
                }
            ],
        },
        context,
    )

    assert result.ui_hint is not None
    assert result.ui_hint["type"] == "changeset:proposal"
    assert result.metadata["paths"] == ["chapters/vol-01/ch-001.md", "plot/foreshadows.json"]
    assert not await context.exists("chapters/vol-01/ch-001.md")
    assert not await context.exists("plot/foreshadows.json")

    record = await apply_change_set(context, result.metadata["changeset_id"])
    assert record.status == "applied"
    assert await context.read_text("chapters/vol-01/ch-001.md") == "# 第一章\n\n门禁亮了一下。\n"
    data = await context.read_json("plot/foreshadows.json")
    assert data["items"][0]["title"] == "门禁的未知权限"


@pytest.mark.asyncio
async def test_write_chapter_skips_only_invalid_foreshadow_actions(tmp_path):
    context = ProjectContext(tmp_path)
    result = await WriteChapterTool().execute(
        {
            "path": "chapters/vol-01/ch-002.md",
            "content": "# 第二章\n\n沈砚发现一张烧焦的名册。\n",
            "foreshadow_actions": [
                {"action": "advance", "foreshadow_id": "missing-id", "evidence": "名册烧焦。"},
                {
                    "action": "plant",
                    "title": "烧焦的名册",
                    "summary": "名册边缘残留无法辨认的姓名。",
                    "evidence": "沈砚发现一张烧焦的名册。",
                },
            ],
        },
        context,
    )

    assert result.ui_hint is not None
    assert result.metadata["paths"] == ["chapters/vol-01/ch-002.md", "plot/foreshadows.json"]
    assert len(result.metadata["foreshadow_actions"]) == 1
    assert result.metadata["foreshadow_actions"][0]["title"] == "烧焦的名册"
    assert len(result.metadata["warnings"]) == 1

    await apply_change_set(context, result.metadata["changeset_id"])
    stored = await context.read_json("plot/foreshadows.json")
    assert [item["title"] for item in stored["items"]] == ["烧焦的名册"]


@pytest.mark.asyncio
async def test_write_chapter_without_foreshadow_actions_keeps_direct_write(tmp_path):
    context = ProjectContext(tmp_path)
    result = await WriteChapterTool().execute(
        {"path": "chapters/vol-01/ch-001.md", "content": "# 第一章\n"},
        context,
    )

    assert result.ui_hint is not None
    assert result.ui_hint["type"] == "stream:editor"
    assert await context.read_text("chapters/vol-01/ch-001.md") == "# 第一章\n"


@pytest.mark.asyncio
async def test_edit_chapter_proposes_joint_change_when_foreshadow_changes(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text("chapters/vol-01/ch-001.md", "# 第一章\n旧内容\n")
    result = await EditChapterTool().execute(
        {
            "path": "chapters/vol-01/ch-001.md",
            "content": "# 第一章\n新内容\n",
            "mode": "replace",
            "foreshadow_actions": [
                {
                    "action": "plant",
                    "title": "异常信号",
                    "summary": "终端出现短暂的未知信号。",
                    "evidence": "终端屏幕闪过未知信号。",
                }
            ],
        },
        context,
    )

    assert result.ui_hint is not None
    assert result.ui_hint["type"] == "changeset:proposal"
    assert await context.read_text("chapters/vol-01/ch-001.md") == "# 第一章\n旧内容\n"
    await apply_change_set(context, result.metadata["changeset_id"])
    assert await context.read_text("chapters/vol-01/ch-001.md") == "# 第一章\n新内容\n"


class WriteChapterLLM:
    def __init__(self):
        self.calls = 0

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        if self.calls == 1 and request.tools:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {
                        "id": "call-write-1",
                        "name": "write_chapter",
                        "input": {
                            "path": "chapters/vol-01/ch-001.md",
                            "content": "# 第一章\n\n门禁亮了一下。\n",
                            "foreshadow_actions": [
                                {
                                    "action": "plant",
                                    "title": "门禁异常",
                                    "summary": "门禁在断电后仍识别出未知权限。",
                                    "evidence": "屏幕显示未知权限。",
                                }
                            ],
                        },
                    }
                ],
            )
        return ChatResponse(content=[], text="已完成")


@pytest.mark.asyncio
async def test_agent_waits_for_write_chapter_foreshadow_changeset(tmp_path):
    context = ProjectContext(tmp_path)
    registry = ToolRegistry()
    registry.register(WriteChapterTool())
    proposal_ready = asyncio.Event()
    events: list[dict] = []

    async def publish(event: dict) -> None:
        events.append(event)
        if event.get("type") == "tool_result" and event.get("ui_hint", {}).get("type") == "changeset:proposal":
            proposal_ready.set()

    agent = MasterAgent(
        llm_client=WriteChapterLLM(),
        tool_registry=registry,
        project=context,
        publisher=publish,
    )
    task = asyncio.create_task(agent.run("写第一章并埋下门禁伏笔"))
    await asyncio.wait_for(proposal_ready.wait(), timeout=2)
    assert not task.done()

    proposal = next(event for event in events if event.get("ui_hint", {}).get("type") == "changeset:proposal")
    change_set_id = proposal["ui_hint"]["data"]["id"]
    await apply_change_set(context, change_set_id)
    assert resolve_change_set_decision(context.root, change_set_id, "applied")

    assert await asyncio.wait_for(task, timeout=2) == "已完成"
    assert await context.exists("chapters/vol-01/ch-001.md")
    assert await context.exists("plot/foreshadows.json")
    update = next(event for event in events if event.get("type") == "changeset_update")
    assert update["metadata"]["foreshadow_verification"][0]["status"] == "review"
