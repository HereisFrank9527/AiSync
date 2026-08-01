import asyncio
import json
import re

import pytest

from app.agent import MasterAgent
from app.change_approvals import resolve_change_set_decision
from app.change_sets import apply_change_set
from app.llm.types import ChatResponse
from app.projects.context import ProjectContext
from app.tools.chapter_draft import ChapterDraftTool, MAX_DRAFT_CHUNK_CHARS
from app.tools.factory import create_tool_registry
from app.tools.registry import ToolRegistry
from app.tools.write_chapter import WriteChapterTool


class NoopLLM:
    async def chat(self, request, on_text_delta=None):
        raise AssertionError("LLM should not be called")


class StagedChapterLLM:
    def __init__(self):
        self.calls = 0

    async def chat(self, request, on_text_delta=None):
        self.calls += 1
        payload = json.dumps(request.messages, ensure_ascii=False)
        draft_match = re.search(r"chapterdraft_[a-f0-9]{32}", payload)
        draft_id = draft_match.group(0) if draft_match else ""
        if self.calls == 1:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {
                        "id": "draft-begin",
                        "name": "chapter_draft",
                        "input": {"action": "begin", "path": "chapters/vol-01/ch-001.md"},
                    }
                ],
            )
        if self.calls == 2:
            assert draft_id
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {
                        "id": "draft-append-1",
                        "name": "chapter_draft",
                        "input": {
                            "action": "append",
                            "draft_id": draft_id,
                            "sequence": 1,
                            "content": "# 第一章\n\n第一段。",
                        },
                    }
                ],
            )
        if self.calls == 3:
            assert draft_id
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {
                        "id": "draft-append-2",
                        "name": "chapter_draft",
                        "input": {
                            "action": "append",
                            "draft_id": draft_id,
                            "sequence": 2,
                            "content": "\n\n第二段。\n",
                        },
                    }
                ],
            )
        if self.calls == 4:
            assert draft_id
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {
                        "id": "draft-finalize",
                        "name": "chapter_draft",
                        "input": {
                            "action": "finalize",
                            "draft_id": draft_id,
                            "foreshadow_actions": [],
                            "fact_records": [],
                        },
                    }
                ],
            )
        return ChatResponse(content=[], text="章节已完成")


@pytest.mark.asyncio
async def test_chapter_draft_appends_in_sequence_and_finalizes_as_change_set(tmp_path):
    context = ProjectContext(tmp_path)
    tool = ChapterDraftTool()

    started = await tool.execute(
        {"action": "begin", "path": "chapters/vol-01/ch-001.md"},
        context,
    )
    draft_id = started.metadata["draft_id"]

    first = await tool.execute(
        {
            "action": "append",
            "draft_id": draft_id,
            "sequence": 1,
            "content": "# 第一章\n\n门禁亮了起来。",
        },
        context,
    )
    second = await tool.execute(
        {
            "action": "append",
            "draft_id": draft_id,
            "sequence": 2,
            "content": "\n\n林铎握紧零号通行证。\n",
        },
        context,
    )

    assert first.metadata["next_sequence"] == 2
    assert second.metadata["next_sequence"] == 3
    assert second.metadata["draft_characters"] > first.metadata["draft_characters"]

    result = await tool.execute(
        {
            "action": "finalize",
            "draft_id": draft_id,
            "foreshadow_actions": [],
            "fact_records": [
                {
                    "category": "possession",
                    "subject": "林铎",
                    "predicate": "持有",
                    "value": "零号通行证",
                    "evidence": "林铎握紧零号通行证。",
                    "certainty": "confirmed",
                }
            ],
        },
        context,
    )

    assert result.ui_hint is not None
    assert result.ui_hint["type"] == "changeset:proposal"
    assert result.metadata["paths"] == [
        "chapters/vol-01/ch-001.md",
        "plot/facts/vol-01/ch-001.json",
    ]
    assert not await context.exists(f".aisync/chapter_drafts/{draft_id}.json")
    assert not await context.exists(f".aisync/chapter_drafts/{draft_id}.md")
    assert not await context.exists("chapters/vol-01/ch-001.md")

    await apply_change_set(context, result.metadata["changeset_id"])

    assert await context.read_text("chapters/vol-01/ch-001.md") == (
        "# 第一章\n\n门禁亮了起来。\n\n林铎握紧零号通行证。\n"
    )
    facts = await context.read_json("plot/facts/vol-01/ch-001.json")
    assert facts["facts"][0]["value"] == "零号通行证"


@pytest.mark.asyncio
async def test_chapter_draft_skips_invalid_foreshadow_actions_without_losing_chapter(tmp_path):
    context = ProjectContext(tmp_path)
    tool = ChapterDraftTool()
    started = await tool.execute(
        {"action": "begin", "path": "chapters/vol-01/ch-002.md"},
        context,
    )
    draft_id = started.metadata["draft_id"]
    await tool.execute(
        {
            "action": "append",
            "draft_id": draft_id,
            "sequence": 1,
            "content": "# 第二章\n\n沈砚收起案卷。\n",
        },
        context,
    )

    result = await tool.execute(
        {
            "action": "finalize",
            "draft_id": draft_id,
            "foreshadow_actions": [
                {"action": "advance", "foreshadow_id": "missing-id", "evidence": "案卷仍在。"},
                {
                    "action": "plant",
                    "foreshadow_id": "existing-id",
                    "title": "错误组合",
                    "summary": "不应阻止正文提交。",
                },
            ],
            "fact_records": [],
        },
        context,
    )

    assert result.ui_hint is not None
    assert result.ui_hint["type"] == "changeset:proposal"
    assert result.metadata["paths"] == ["chapters/vol-01/ch-002.md"]
    assert result.metadata["foreshadow_actions"] == []
    assert len(result.metadata["warnings"]) == 2
    assert "正文不受影响" in result.content
    assert not await context.exists(f".aisync/chapter_drafts/{draft_id}.md")

    await apply_change_set(context, result.metadata["changeset_id"])
    assert await context.read_text("chapters/vol-01/ch-002.md") == "# 第二章\n\n沈砚收起案卷。\n"


@pytest.mark.asyncio
async def test_chapter_draft_rejects_wrong_sequence_and_oversized_chunk(tmp_path):
    context = ProjectContext(tmp_path)
    tool = ChapterDraftTool()
    started = await tool.execute(
        {"action": "begin", "path": "chapters/vol-01/ch-001.md"},
        context,
    )
    draft_id = started.metadata["draft_id"]

    with pytest.raises(ValueError, match="期望 sequence=1"):
        await tool.execute(
            {"action": "append", "draft_id": draft_id, "sequence": 2, "content": "错误顺序"},
            context,
        )

    with pytest.raises(ValueError, match="最多"):
        await tool.execute(
            {
                "action": "append",
                "draft_id": draft_id,
                "sequence": 1,
                "content": "长" * (MAX_DRAFT_CHUNK_CHARS + 1),
            },
            context,
        )


@pytest.mark.asyncio
async def test_chapter_draft_can_be_discarded_without_touching_chapter(tmp_path):
    context = ProjectContext(tmp_path)
    tool = ChapterDraftTool()
    started = await tool.execute(
        {"action": "begin", "path": "chapters/vol-01/ch-001.md"},
        context,
    )
    draft_id = started.metadata["draft_id"]
    await tool.execute(
        {"action": "append", "draft_id": draft_id, "sequence": 1, "content": "临时正文"},
        context,
    )

    result = await tool.execute({"action": "discard", "draft_id": draft_id}, context)

    assert result.metadata["draft_action"] == "discard"
    assert not await context.exists("chapters/vol-01/ch-001.md")
    assert not await context.exists(f".aisync/chapter_drafts/{draft_id}.md")


def test_agent_exposes_internal_chapter_draft_when_write_chapter_is_enabled(tmp_path):
    registry = create_tool_registry()
    agent = MasterAgent(
        llm_client=NoopLLM(),
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    schemas = agent._request_tool_schemas({"write_chapter"})
    names = {schema["name"] for schema in schemas}

    assert names == {"chapter_draft", "present_choices", "write_chapter"}


@pytest.mark.asyncio
async def test_agent_runs_staged_chapter_loop_without_showing_intermediate_results(tmp_path):
    context = ProjectContext(tmp_path)
    registry = ToolRegistry()
    registry.register(ChapterDraftTool())
    registry.register(WriteChapterTool())
    llm = StagedChapterLLM()
    proposal_ready = asyncio.Event()
    events: list[dict] = []

    async def publish(event: dict) -> None:
        events.append(event)
        if event.get("type") == "tool_result" and event.get("ui_hint", {}).get("type") == "changeset:proposal":
            proposal_ready.set()

    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        project=context,
        publisher=publish,
        enabled_tools=["write_chapter"],
    )
    task = asyncio.create_task(agent.run("写一章较长正文", max_iterations=8))
    await asyncio.wait_for(proposal_ready.wait(), timeout=3)

    proposal = next(event for event in events if event.get("type") == "tool_result")
    change_set_id = proposal["ui_hint"]["data"]["id"]
    await apply_change_set(context, change_set_id)
    assert resolve_change_set_decision(context.root, change_set_id, "applied")

    assert await asyncio.wait_for(task, timeout=3) == "章节已完成"
    assert llm.calls == 5
    assert await context.read_text("chapters/vol-01/ch-001.md") == "# 第一章\n\n第一段。\n\n第二段。\n"
    visible_results = [event for event in events if event.get("type") == "tool_result"]
    assert len(visible_results) == 1
    progress = [
        event.get("content")
        for event in events
        if event.get("type") == "agent_status" and event.get("metadata", {}).get("phase") == "chapter_drafting"
    ]
    assert progress[0] == "长章节草稿缓冲已建立"
    assert progress[1].startswith("长章节草稿已累计 ")
    assert progress[2].startswith("长章节草稿已累计 ")
