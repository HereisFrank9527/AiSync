import asyncio

import pytest

from app.change_sets import (
    ProposedFileChange,
    apply_change_set,
    create_change_set,
    discard_change_set,
    hash_text,
    load_change_set,
    verify_change_set_application,
)
from app.change_approvals import has_change_set_waiter, wait_for_change_set_decision
from app.api.change_sets import ChangeSetActionRequest, apply_project_change_set, defer_project_change_set
from app.conversations.store import ConversationStore
from app.projects.context import ProjectContext
from app.projects.outline import refresh_outline_index
from app.tools.file_change_proposal import FileChangeProposalTool
from app.tools.read_project_files import ReadProjectFilesTool


def run(coro):
    return asyncio.run(coro)


def test_change_set_proposes_diff_without_writing(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        await context.write_text("world/overview.md", "# Old\n\n旧设定\n")

        record = await create_change_set(
            context,
            title="更新世界观",
            changes=[
                ProposedFileChange(
                    path="world/overview.md",
                    new_content="# New\n\n新设定\n",
                    reason="替换旧设定",
                )
            ],
        )

        assert record.status == "pending"
        assert record.changes[0].path == "world/overview.md"
        assert "-旧设定" in record.changes[0].diff
        assert "+新设定" in record.changes[0].diff
        assert await context.read_text("world/overview.md") == "# Old\n\n旧设定\n"

    run(scenario())


def test_change_set_applies_after_hash_check(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        await context.write_text("characters/lin-duo/profile.md", "old\n")
        record = await create_change_set(
            context,
            title="更新角色",
            changes=[ProposedFileChange(path="characters/lin-duo/profile.md", new_content="new\n")],
        )

        applied = await apply_change_set(context, record.id)

        assert applied.status == "applied"
        assert await context.read_text("characters/lin-duo/profile.md") == "new\n"

    run(scenario())


def test_change_set_application_verification_detects_later_drift(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        await context.write_text("notes.md", "old\n")
        record = await create_change_set(
            context,
            title="更新并核验",
            changes=[ProposedFileChange(path="notes.md", new_content="new\n")],
        )
        await apply_change_set(context, record.id)

        verified = await verify_change_set_application(context, record.id)
        assert verified["status"] == "verified"
        assert verified["verified"] == 1

        await context.write_text("notes.md", "changed again\n")
        drifted = await verify_change_set_application(context, record.id)
        assert drifted["status"] == "review"
        assert drifted["files"][0]["issue"] == "文件内容与改动包不一致"

    run(scenario())


def test_read_project_files_returns_exact_content_and_rejects_escape(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        await context.write_text("world/overview.md", "# 世界观\n\n完整设定。\n")
        await context.write_text("characters/lin/profile.yaml", "name: 林铎\n")
        tool = ReadProjectFilesTool()

        result = await tool.execute(
            {"paths": ["world/overview.md", "characters/lin/profile.yaml"]},
            context,
        )
        assert "# 世界观\n\n完整设定。" in result.content
        assert "name: 林铎" in result.content
        assert result.metadata["read_count"] == 2

        with pytest.raises(ValueError):
            await tool.execute({"paths": ["../outside.md"]}, context)

    run(scenario())


def test_change_set_rejects_stale_apply(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        await context.write_text("plot/outline.md", "old\n")
        record = await create_change_set(
            context,
            title="更新大纲",
            changes=[ProposedFileChange(path="plot/outline.md", new_content="new\n")],
        )
        await context.write_text("plot/outline.md", "changed elsewhere\n")

        with pytest.raises(RuntimeError):
            await apply_change_set(context, record.id)

        assert await context.read_text("plot/outline.md") == "changed elsewhere\n"

    run(scenario())


def test_change_set_rejects_internal_paths(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        with pytest.raises(ValueError):
            await create_change_set(
                context,
                title="坏路径",
                changes=[ProposedFileChange(path=".aisync/config.json", new_content="{}")],
            )

    run(scenario())


def test_change_set_can_be_discarded(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        record = await create_change_set(
            context,
            title="临时改动",
            changes=[ProposedFileChange(path="notes.md", new_content="draft\n")],
        )

        discarded = await discard_change_set(context, record.id)

        assert discarded.status == "discarded"
        assert not await context.exists("notes.md")

    run(scenario())


def test_file_change_proposal_tool_returns_ui_hint(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        tool = FileChangeProposalTool()
        result = await tool.execute(
            {
                "title": "更新设定",
                "changes": [
                    {
                        "path": "world/overview.md",
                        "new_content": "# 世界观\n",
                        "reason": "新增基础文件",
                    }
                ],
            },
            context,
        )

        assert result.ui_hint is not None
        assert result.ui_hint["type"] == "changeset:proposal"
        assert result.metadata["change_count"] == 1
        assert not await context.exists("world/overview.md")

    run(scenario())


def test_file_change_proposal_applies_sequential_local_patches_as_one_file_change(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        path = "world/overview.md"
        original = "alpha beta gamma\nremove me\n"
        await context.write_text(path, original)
        result = await FileChangeProposalTool().execute(
            {
                "title": "局部整理世界观",
                "changes": [
                    {"path": path, "operation": "replace_text", "old_text": "alpha", "new_text": "ALPHA"},
                    {"path": path, "operation": "replace_text", "old_text": " beta", "new_text": " BETA"},
                    {"path": path, "operation": "replace_text", "old_text": "remove me\n", "new_text": ""},
                    {"path": path, "operation": "prepend_text", "new_text": "# 世界观\n"},
                    {"path": path, "operation": "append_text", "new_text": "结尾\n"},
                ],
            },
            context,
        )

        assert result.metadata["change_count"] == 1
        assert result.metadata["operation_counts"] == {
            "replace_text": 3,
            "prepend_text": 1,
            "append_text": 1,
        }
        assert result.ui_hint["data"]["changes"][0]["source_operations"] == [
            "replace_text",
            "replace_text",
            "replace_text",
            "prepend_text",
            "append_text",
        ]
        assert await context.read_text(path) == original

        await apply_change_set(context, result.metadata["changeset_id"])
        assert await context.read_text(path) == "# 世界观\nALPHA BETA gamma\n结尾\n"

    run(scenario())


def test_file_change_proposal_replaces_outline_nodes_and_refreshes_index(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        original = (
            "# 总纲\n\n"
            "## 作品定位\n"
            "旧定位。\n\n"
            "## 世界背景\n"
            "保留内容。\n\n"
            "### 第1章：开端\n"
            "旧章节。\n"
        )
        await context.write_text("plot/outline.md", original)
        outline = await refresh_outline_index(context)
        nodes = {node["heading"]: node for node in outline["nodes"]}

        result = await FileChangeProposalTool().execute(
            {
                "title": "局部整理大纲",
                "changes": [
                    {
                        "path": "plot/outline.md",
                        "operation": "replace_outline_node",
                        "node_id": nodes["作品定位"]["id"],
                        "new_text": "## 作品定位\n\n新定位。\n\n",
                    },
                    {
                        "path": "plot/outline.md",
                        "operation": "replace_outline_node",
                        "node_id": nodes["第1章：开端"]["id"],
                        "new_text": "",
                    },
                ],
            },
            context,
        )

        assert await context.read_text("plot/outline.md") == original
        assert result.metadata["operation_counts"] == {"replace_outline_node": 2}
        assert result.metadata["outline_node_ids"]["plot/outline.md"] == [
            nodes["作品定位"]["id"],
            nodes["第1章：开端"]["id"],
        ]

        await apply_change_set(context, result.metadata["changeset_id"])

        updated = await context.read_text("plot/outline.md")
        assert updated == (
            "# 总纲\n\n"
            "## 作品定位\n\n"
            "新定位。\n\n"
            "## 世界背景\n"
            "保留内容。\n\n"
        )
        refreshed = await context.read_json("plot/outline.json")
        assert [node["heading"] for node in refreshed["nodes"]] == ["作品定位", "世界背景"]
        history_files = await context.list_files(".aisync/outline_history")
        assert len(history_files) == 1
        assert await context.read_text(history_files[0]) == original

    run(scenario())


def test_file_change_proposal_inserts_outline_nodes_at_shared_boundary(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        original = (
            "# 总纲\n\n"
            "## 第一幕\n"
            "第一幕正文。\n\n"
            "## 第三幕\n"
            "第三幕正文。\n"
        )
        await context.write_text("plot/outline.md", original)
        outline = await refresh_outline_index(context)
        nodes = {node["heading"]: node for node in outline["nodes"]}

        result = await FileChangeProposalTool().execute(
            {
                "title": "插入中间大纲区块",
                "changes": [
                    {
                        "path": "plot/outline.md",
                        "operation": "insert_after_outline_node",
                        "node_id": nodes["第一幕"]["id"],
                        "new_text": "## 第二幕 A\n\nA 正文。\n\n",
                    },
                    {
                        "path": "plot/outline.md",
                        "operation": "insert_before_outline_node",
                        "node_id": nodes["第三幕"]["id"],
                        "new_text": "## 第二幕 B\n\nB 正文。\n\n",
                    },
                ],
            },
            context,
        )

        assert await context.read_text("plot/outline.md") == original
        assert result.metadata["operation_counts"] == {
            "insert_after_outline_node": 1,
            "insert_before_outline_node": 1,
        }
        stored = await load_change_set(context, result.metadata["changeset_id"])
        assert stored.changes[0].source_operations == [
            "insert_after_outline_node",
            "insert_before_outline_node",
        ]
        assert stored.changes[0].outline_node_ids == [
            nodes["第一幕"]["id"],
            nodes["第三幕"]["id"],
        ]

        await apply_change_set(context, result.metadata["changeset_id"])

        updated = await context.read_text("plot/outline.md")
        assert updated == (
            "# 总纲\n\n"
            "## 第一幕\n"
            "第一幕正文。\n\n"
            "## 第二幕 A\n\n"
            "A 正文。\n\n"
            "## 第二幕 B\n\n"
            "B 正文。\n\n"
            "## 第三幕\n"
            "第三幕正文。\n"
        )
        refreshed = await context.read_json("plot/outline.json")
        assert [node["heading"] for node in refreshed["nodes"]] == [
            "第一幕",
            "第二幕 A",
            "第二幕 B",
            "第三幕",
        ]

    run(scenario())


def test_file_change_proposal_rejects_empty_outline_insert(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        await context.write_text("plot/outline.md", "# 总纲\n\n## 第一幕\n正文。\n")
        outline = await refresh_outline_index(context)

        with pytest.raises(ValueError, match="requires non-empty new_text"):
            await FileChangeProposalTool().execute(
                {
                    "title": "空插入",
                    "changes": [
                        {
                            "path": "plot/outline.md",
                            "operation": "insert_after_outline_node",
                            "node_id": outline["nodes"][0]["id"],
                            "new_text": "",
                        }
                    ],
                },
                context,
            )

    run(scenario())


def test_file_change_proposal_rejects_unknown_outline_node(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        await context.write_text("plot/outline.md", "# 总纲\n\n## 第一幕\n正文。\n")

        with pytest.raises(ValueError, match="大纲区块不存在或已变化"):
            await FileChangeProposalTool().execute(
                {
                    "title": "修改不存在区块",
                    "changes": [
                        {
                            "path": "plot/outline.md",
                            "operation": "replace_outline_node",
                            "node_id": "outline-missing",
                            "new_text": "## 新内容\n",
                        }
                    ],
                },
                context,
            )

    run(scenario())


@pytest.mark.parametrize(
    ("content", "old_text", "matches"),
    [
        ("没有目标文本\n", "旧设定", 0),
        ("旧设定\n旧设定\n", "旧设定", 2),
    ],
)
def test_file_change_proposal_rejects_non_unique_replace(tmp_path, content, old_text, matches):
    async def scenario():
        context = ProjectContext(tmp_path)
        path = "world/overview.md"
        await context.write_text(path, content)

        with pytest.raises(ValueError, match=f"实际匹配 {matches} 处"):
            await FileChangeProposalTool().execute(
                {
                    "title": "歧义替换",
                    "changes": [
                        {
                            "path": path,
                            "operation": "replace_text",
                            "old_text": old_text,
                            "new_text": "新设定",
                        }
                    ],
                },
                context,
            )
        assert await context.read_text(path) == content

    run(scenario())


def test_file_change_proposal_replaces_hash_guarded_line_range(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        path = "chapters/volume-01/chapter-01.md"
        original = "第一行\n旧正文一\n旧正文二\n最后一行\n"
        await context.write_text(path, original)

        result = await FileChangeProposalTool().execute(
            {
                "title": "局部修改正文",
                "changes": [
                    {
                        "path": path,
                        "operation": "replace_lines",
                        "start_line": 2,
                        "end_line": 3,
                        "source_hash": hash_text(original),
                        "new_text": "新正文一\n新正文二",
                    }
                ],
            },
            context,
        )

        assert result.metadata["operation_counts"] == {"replace_lines": 1}
        await apply_change_set(context, result.metadata["changeset_id"])
        assert await context.read_text(path) == "第一行\n新正文一\n新正文二\n最后一行\n"

    run(scenario())


def test_file_change_proposal_replaces_multiple_line_ranges_in_one_file(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        path = "notes.md"
        original = "one\ntwo\nthree\nfour\nfive\nsix\n"
        await context.write_text(path, original)

        result = await FileChangeProposalTool().execute(
            {
                "title": "Update multiple ranges",
                "changes": [
                    {
                        "path": path,
                        "operation": "replace_lines",
                        "start_line": 2,
                        "end_line": 2,
                        "source_hash": hash_text(original),
                        "new_text": "TWO",
                    },
                    {
                        "path": path,
                        "operation": "replace_lines",
                        "start_line": 5,
                        "end_line": 5,
                        "source_hash": hash_text(original),
                        "new_content": "FIVE\nEXTRA",
                    },
                    {
                        "path": path,
                        "operation": "replace_lines",
                        "start_line": 3,
                        "end_line": 3,
                        "source_hash": hash_text(original),
                        "new_text": "",
                    },
                ],
            },
            context,
        )

        assert result.metadata["operation_counts"] == {"replace_lines": 3}
        assert await context.read_text(path) == original
        await apply_change_set(context, result.metadata["changeset_id"])
        assert await context.read_text(path) == "one\nTWO\nfour\nFIVE\nEXTRA\nsix\n"

    run(scenario())


def test_file_change_proposal_rejects_overlapping_line_ranges(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        path = "notes.md"
        original = "one\ntwo\nthree\nfour\n"
        await context.write_text(path, original)

        with pytest.raises(ValueError, match="replace_lines 行范围不能重叠"):
            await FileChangeProposalTool().execute(
                {
                    "title": "Overlapping ranges",
                    "changes": [
                        {
                            "path": path,
                            "operation": "replace_lines",
                            "start_line": 2,
                            "end_line": 3,
                            "source_hash": hash_text(original),
                            "new_text": "middle",
                        },
                        {
                            "path": path,
                            "operation": "replace_lines",
                            "start_line": 3,
                            "end_line": 4,
                            "source_hash": hash_text(original),
                            "new_text": "tail",
                        },
                    ],
                },
                context,
            )

    run(scenario())


def test_file_change_proposal_rejects_line_range_mixed_with_text_patch(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        path = "notes.md"
        original = "one\ntwo\nthree\n"
        await context.write_text(path, original)

        with pytest.raises(ValueError, match="replace_lines 不能与同一文件的其他局部操作混用"):
            await FileChangeProposalTool().execute(
                {
                    "title": "Mixed patch modes",
                    "changes": [
                        {
                            "path": path,
                            "operation": "replace_lines",
                            "start_line": 2,
                            "end_line": 2,
                            "source_hash": hash_text(original),
                            "new_text": "TWO",
                        },
                        {
                            "path": path,
                            "operation": "replace_text",
                            "old_text": "three",
                            "new_text": "THREE",
                        },
                    ],
                },
                context,
            )

    run(scenario())


def test_file_change_proposal_rejects_stale_line_range_hash(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        path = "world/overview.md"
        await context.write_text(path, "当前内容\n")

        with pytest.raises(ValueError, match="文件内容已变化"):
            await FileChangeProposalTool().execute(
                {
                    "title": "错误的旧行号",
                    "changes": [
                        {
                            "path": path,
                            "operation": "replace_lines",
                            "start_line": 1,
                            "end_line": 1,
                            "source_hash": hash_text("旧内容\n"),
                            "new_text": "新内容",
                        }
                    ],
                },
                context,
            )

    run(scenario())


def test_file_change_proposal_rejects_full_write_mixed_with_patch(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        path = "notes.md"
        await context.write_text(path, "old\n")

        with pytest.raises(ValueError, match="完整写入不能与同一文件的其他操作混用"):
            await FileChangeProposalTool().execute(
                {
                    "title": "冲突操作",
                    "changes": [
                        {"path": path, "operation": "append_text", "new_text": "extra\n"},
                        {"path": path, "operation": "write", "new_content": "new\n"},
                    ],
                },
                context,
            )
        assert await context.read_text(path) == "old\n"

    run(scenario())


def test_file_change_proposal_expands_temp_directory_delete(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        await context.write_text("temp/archive/characters/old/profile.md", "old\n")
        await context.write_text("temp/archive/characters/old/profile.yaml", "role: old\n")
        await context.write_text("temp/.aisync-temp.json", "{}\n")
        tool = FileChangeProposalTool()

        result = await tool.execute(
            {
                "title": "清理临时归档",
                "changes": [
                    {
                        "path": "temp",
                        "operation": "delete_directory",
                        "reason": "删除 temp 下的临时归档文件",
                    }
                ],
            },
            context,
        )

        paths = result.metadata["paths"]
        assert sorted(paths) == [
            "temp/archive/characters/old/profile.md",
            "temp/archive/characters/old/profile.yaml",
        ]
        assert result.metadata["expanded_directories"] == ["temp"]
        assert await context.exists("temp/archive/characters/old/profile.md")
        assert await context.exists("temp/.aisync-temp.json")

        record = await apply_change_set(context, result.metadata["changeset_id"])
        assert record.status == "applied"
        assert not await context.exists("temp/archive/characters/old/profile.md")
        assert not await context.exists("temp/archive/characters/old/profile.yaml")
        assert await context.exists("temp/.aisync-temp.json")

    run(scenario())


def test_file_change_proposal_can_update_agent_md(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        await context.write_text("AGENT.md", "# 当前文风\n\n- 克制。\n")
        tool = FileChangeProposalTool()

        result = await tool.execute(
            {
                "title": "调整项目文风",
                "changes": [
                    {
                        "path": "AGENT.md",
                        "new_content": "# 当前文风\n\n- 克制。\n- 避免连续单句成段。\n",
                        "reason": "记录用户的长期文风偏好",
                    }
                ],
            },
            context,
        )

        assert result.metadata["paths"] == ["AGENT.md"]
        assert "避免连续单句成段" in result.ui_hint["data"]["changes"][0]["diff"]
        assert await context.read_text("AGENT.md") == "# 当前文风\n\n- 克制。\n"

    run(scenario())


def test_change_set_approval_waiter_resolves_after_apply(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        record = await create_change_set(
            context,
            title="等待确认",
            changes=[ProposedFileChange(path="notes.md", new_content="new\n")],
        )
        task = asyncio.create_task(wait_for_change_set_decision(context, record.id))
        for _ in range(50):
            if has_change_set_waiter(context.root, record.id):
                break
            await asyncio.sleep(0.01)

        assert has_change_set_waiter(context.root, record.id)
        response = await apply_project_change_set(
            record.id,
            ChangeSetActionRequest(project_path=str(context.root)),
        )
        assert response["agent_resumed"] is True
        assert await task == "applied"
        assert not has_change_set_waiter(context.root, record.id)

    run(scenario())


def test_change_set_can_defer_active_agent_without_changing_status(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        record = await create_change_set(
            context,
            title="稍后处理",
            changes=[ProposedFileChange(path="notes.md", new_content="new\n")],
        )
        task = asyncio.create_task(wait_for_change_set_decision(context, record.id))
        for _ in range(50):
            if has_change_set_waiter(context.root, record.id):
                break
            await asyncio.sleep(0.01)

        response = await defer_project_change_set(
            record.id,
            ChangeSetActionRequest(project_path=str(context.root)),
        )

        assert response["agent_resumed"] is True
        assert response["status"] == "pending"
        assert await task == "deferred"
        assert (await load_change_set(context, record.id)).status == "pending"
        assert not await context.exists("notes.md")

    run(scenario())


def test_change_set_waiter_times_out_without_changing_status(tmp_path):
    async def scenario():
        context = ProjectContext(tmp_path)
        record = await create_change_set(
            context,
            title="等待超时",
            changes=[ProposedFileChange(path="notes.md", new_content="new\n")],
        )

        decision = await wait_for_change_set_decision(context, record.id, timeout_seconds=0.01)

        assert decision == "timed_out"
        assert (await load_change_set(context, record.id)).status == "pending"
        assert not has_change_set_waiter(context.root, record.id)

    run(scenario())


def test_conversation_store_persists_change_set_card(tmp_path):
    store = ConversationStore(tmp_path)
    conversation = store.create("测试")
    store.append(
        conversation.id,
        "agent",
        "等待确认",
        "tool_result",
        ui_hint={"type": "changeset:proposal", "data": {"id": "changeset_test"}},
        metadata={"run_id": "run-test"},
    )

    loaded = store.load(conversation.id)
    assert loaded.messages[0].type == "tool_result"
    assert loaded.messages[0].ui_hint == {"type": "changeset:proposal", "data": {"id": "changeset_test"}}
    assert loaded.messages[0].metadata["run_id"] == "run-test"

    store.update_change_set_message(
        conversation.id,
        "changeset_test",
        content="已留待稍后处理",
        ui_hint={"type": "changeset:proposal", "data": {"id": "changeset_test", "agent_waiting": False}},
        metadata={"approval_decision": "deferred"},
    )
    updated = store.load(conversation.id).messages[0]
    assert updated.content == "已留待稍后处理"
    assert updated.ui_hint["data"]["agent_waiting"] is False
    assert updated.metadata["approval_decision"] == "deferred"
