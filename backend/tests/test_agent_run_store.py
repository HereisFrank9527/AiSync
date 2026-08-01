import asyncio

from app.api.agent import (
    active_conversation_run_ids,
    active_conversation_ids,
    active_run_ids,
    active_conversation_agents,
    active_run_agents,
    active_run_tasks,
    attach_running_task,
    attach_running_agent,
    clear_conversation_running,
    format_exception,
    interrupt_running_agent,
    is_conversation_running,
    mark_conversation_running,
    mark_interrupt_requested,
    retry_basis_for_run,
    retry_finalize_prompt,
    retry_history_without_last_user,
    settled_agent_status,
    settle_stale_run_if_needed,
)
from app.conversations.runs import AgentRunStore, retry_mode_for_run
from app.conversations.store import ConversationStore


def test_agent_run_lifecycle(tmp_path):
    store = AgentRunStore(tmp_path)
    run = store.start("conv-1", "请继续写下一章", preset_id="default", enabled_tools=["write_chapter"])

    assert run.status == "running"
    assert run.conversation_id == "conv-1"
    assert run.input_preview == "请继续写下一章"

    updated = store.update_phase(run.run_id, "thinking", "正在请求模型")
    assert updated.phase == "thinking"
    assert updated.phase_label == "正在请求模型"

    with_tool = store.add_tool_event(run.run_id, "write_chapter", "completed", duration_ms=42)
    assert with_tool.tool_calls[0]["name"] == "write_chapter"
    assert with_tool.tool_calls[0]["duration_ms"] == 42

    with_failure = store.add_tool_event(
        run.run_id,
        "file_change_proposal",
        "failed",
        error="replace_text 未匹配",
        params={
            "changes": [
                {
                    "path": "chapters/ch-01.md",
                    "operation": "replace_text",
                    "old_text": "旧句",
                    "new_text_chars": 8,
                }
            ]
        },
    )
    assert with_failure.tool_calls[1]["params"]["changes"][0]["old_text"] == "旧句"

    running_tool = store.start_tool_event(
        run.run_id,
        "search_project",
        "call-search-1",
        params={"query": "主角"},
    )
    assert running_tool.tool_calls[2]["status"] == "running"
    assert running_tool.tool_calls[2]["call_id"] == "call-search-1"

    completed_tool = store.add_tool_event(
        run.run_id,
        "search_project",
        "completed",
        duration_ms=35,
        mode="execute",
        call_id="call-search-1",
    )
    assert len(completed_tool.tool_calls) == 3
    assert completed_tool.tool_calls[2]["status"] == "completed"
    assert completed_tool.tool_calls[2]["duration_ms"] == 35
    assert completed_tool.tool_calls[2]["params"] == {"query": "主角"}
    assert completed_tool.tool_calls[2]["finished_at"]

    with_audit = store.update_prompt_audit(
        run.run_id,
        {
            "system_prompt": {"source": "default", "chars": 120},
            "memory": {"summary": True, "recent_messages": 6},
            "vector_context": {"count": 3, "paths": ["world/overview.md"]},
            "foreshadow_context": {"included": False, "chars": 0},
            "tools": {"mode": "runtime_override", "count": 2, "names": ["search_project"]},
        },
    )
    assert with_audit.prompt_audit["system_prompt"]["source"] == "default"
    assert with_audit.prompt_audit["vector_context"]["count"] == 3

    finished = store.finish(run.run_id, "completed")
    assert finished.status == "completed"
    assert finished.finished_at is not None

    latest = store.latest_for_conversation("conv-1")
    assert latest is not None
    assert latest.run_id == run.run_id


def test_agent_run_draft_is_visible_across_store_instances_and_phase_updates(tmp_path):
    store = AgentRunStore(tmp_path)
    run = store.start("conv-draft", "continue")

    first = store.append_draft(run.run_id, "partial ")
    second = AgentRunStore(tmp_path).append_draft(run.run_id, "reply")

    assert first.draft_version == 1
    assert second.draft_content == "partial reply"
    assert second.draft_version == 2
    assert second.draft_updated_at is not None

    phased = AgentRunStore(tmp_path).update_phase(run.run_id, "tool", "calling tool")
    assert phased.draft_content == "partial reply"
    assert phased.draft_version == 2
    assert AgentRunStore(tmp_path).load(run.run_id).draft_content == "partial reply"


def test_failed_run_preserves_draft_but_completed_run_clears_it(tmp_path):
    store = AgentRunStore(tmp_path)
    failed_run = store.start("conv-failed", "continue")
    store.append_draft(failed_run.run_id, "recoverable text")

    failed = store.finish(failed_run.run_id, "failed", "upstream failed")

    assert failed.draft_content == "recoverable text"
    assert store.load(failed_run.run_id).draft_content == "recoverable text"

    completed_run = store.start("conv-completed", "continue")
    store.append_draft(completed_run.run_id, "final text")

    completed = store.finish(completed_run.run_id, "completed")

    assert completed.draft_content == ""
    assert completed.draft_version == 0
    assert store.load(completed_run.run_id).draft_content == ""


def test_waiting_user_is_not_reported_as_completed(tmp_path):
    store = AgentRunStore(tmp_path)
    run = store.start("conv-1", "需要选择")

    waiting = store.finish(run.run_id, "waiting_user")

    assert waiting.status == "waiting_user"
    assert waiting.phase_label == "等待你的选择"
    assert settled_agent_status("请选择下一步", "human_intervention") == "waiting_user"
    assert settled_agent_status("请选择选项", "awaiting_choice") == "waiting_user"
    assert settled_agent_status("完成", "completed") == "completed"


def test_agent_run_preview_is_truncated(tmp_path):
    store = AgentRunStore(tmp_path)
    run = store.start("conv-1", "x" * 300)

    assert len(run.input_preview) == 243
    assert run.input_preview.endswith("...")


def test_agent_run_keeps_original_input_and_retry_link(tmp_path):
    store = AgentRunStore(tmp_path)
    original = store.start("conv-1", "请写入角色设定", preset_id="writer", enabled_tools=["create_character"])
    retried = store.start(
        "conv-1",
        original.input_text,
        preset_id=original.preset_id,
        enabled_tools=original.enabled_tools,
        retry_of_run_id=original.run_id,
        retry_mode="restart",
    )

    assert original.input_text == "请写入角色设定"
    assert retried.retry_of_run_id == original.run_id
    assert retried.retry_mode == "restart"
    assert retried.preset_id == "writer"
    assert retried.enabled_tools == ["create_character"]


def test_retry_mode_uses_finalize_after_mutation_or_applied_change(tmp_path):
    store = AgentRunStore(tmp_path)
    read_only = store.start("conv-1", "查一下设定", enabled_tools=["search_project"])
    store.add_tool_event(read_only.run_id, "search_project", "completed")
    assert retry_mode_for_run(store.load(read_only.run_id)) == "restart"

    mutated = store.start("conv-1", "写入设定", enabled_tools=["file_change_proposal"])
    store.add_tool_event(mutated.run_id, "file_change_proposal", "completed")
    assert retry_mode_for_run(store.load(mutated.run_id)) == "finalize"

    applied = store.start("conv-1", "应用设定")
    store.update_prompt_audit(
        applied.run_id,
        {"usage": {"applied_change_sets": [{"changeset_id": "changeset-1", "paths": ["plot/outline.md"]}]}},
    )
    assert retry_mode_for_run(store.load(applied.run_id)) == "finalize"


def test_retry_finalize_prompt_reports_applied_files_without_repeating_tools(tmp_path):
    store = AgentRunStore(tmp_path)
    run = store.start("conv-1", "把讨论写入文件")
    store.add_tool_event(run.run_id, "file_change_proposal", "completed")
    store.update_prompt_audit(
        run.run_id,
        {
            "usage": {
                "applied_change_sets": [
                    {
                        "changeset_id": "changeset-1",
                        "status": "verified",
                        "paths": ["plot/outline.md", "world/baseline.md"],
                    }
                ]
            }
        },
    )
    failed = store.finish(run.run_id, "failed", "503 auth unavailable")

    prompt = retry_finalize_prompt(failed)

    assert "把讨论写入文件" in prompt
    assert "plot/outline.md" in prompt
    assert "不要再次调用工具" in prompt


def test_retry_history_removes_only_latest_user_turn():
    history = [
        {"role": "user", "content": "第一问"},
        {"role": "agent", "content": "第一答"},
        {"role": "user", "content": "失败的这一问"},
    ]

    assert retry_history_without_last_user(history) == [
        {"role": "user", "content": "第一问"},
        {"role": "agent", "content": "第一答"},
    ]


def test_retry_basis_recovers_previous_side_effectful_run_after_empty_retry(tmp_path):
    store = AgentRunStore(tmp_path)
    original = store.start(
        "conv-1",
        "把讨论写入文件",
        preset_id="writer",
        enabled_tools=["file_change_proposal"],
    )
    store.add_tool_event(original.run_id, "file_change_proposal", "completed")
    store.update_prompt_audit(
        original.run_id,
        {"usage": {"applied_change_sets": [{"changeset_id": "changeset-1", "paths": ["plot/outline.md"]}]}},
    )
    store.finish(original.run_id, "failed", "503 auth unavailable")

    empty_retry = store.start("conv-1", "把讨论写入文件")
    store.update_prompt_audit(empty_retry.run_id, {"usage": {"model_requests": 0}})
    empty_retry = store.finish(empty_retry.run_id, "failed", "503 auth unavailable")

    basis = retry_basis_for_run(store, empty_retry)

    assert basis.run_id == original.run_id
    assert basis.enabled_tools == ["file_change_proposal"]
    assert retry_mode_for_run(basis) == "finalize"


def test_stale_running_agent_run_is_settled(tmp_path):
    conversations = ConversationStore(tmp_path)
    conversation = conversations.create()
    conversations.set_status(conversation.id, "running")
    runs = AgentRunStore(tmp_path)
    run = runs.start(conversation.id, "hello")

    settled = settle_stale_run_if_needed(run, runs, conversations)

    assert settled is not None
    assert settled.status == "interrupted"
    assert settled.finished_at is not None
    assert conversations.load(conversation.id).status == "interrupted"


def test_active_running_agent_run_is_not_settled(tmp_path):
    conversations = ConversationStore(tmp_path)
    conversation = conversations.create()
    conversations.set_status(conversation.id, "running")
    runs = AgentRunStore(tmp_path)
    run = runs.start(conversation.id, "hello")
    active_run_ids.add(run.run_id)
    try:
        settled = settle_stale_run_if_needed(run, runs, conversations)
    finally:
        active_run_ids.discard(run.run_id)

    assert settled is not None
    assert settled.status == "running"
    assert conversations.load(conversation.id).status == "running"


def test_empty_exception_is_formatted():
    class EmptyError(Exception):
        def __str__(self):
            return ""

    assert format_exception(EmptyError()) == "EmptyError"


def test_conversation_running_guard_tracks_run_id():
    conversation_id = "conv-running"
    run_id = "run-running"
    active_conversation_ids.discard(conversation_id)
    active_run_ids.discard(run_id)

    mark_conversation_running(conversation_id, run_id)
    try:
        assert is_conversation_running(conversation_id)
        assert run_id in active_run_ids
    finally:
        clear_conversation_running(conversation_id, run_id)

    assert not is_conversation_running(conversation_id)
    assert run_id not in active_run_ids


def test_interrupt_running_agent_targets_attached_agent():
    class FakeAgent:
        def __init__(self):
            self.interrupted = False

        def interrupt(self):
            self.interrupted = True
            return True

    conversation_id = "conv-interrupt"
    run_id = "run-interrupt"
    agent = FakeAgent()
    active_conversation_agents.pop(conversation_id, None)
    active_run_agents.pop(run_id, None)

    mark_conversation_running(conversation_id, run_id)
    attach_running_agent(conversation_id, run_id, agent)  # type: ignore[arg-type]
    try:
        assert interrupt_running_agent(conversation_id=conversation_id)
        assert agent.interrupted
    finally:
        clear_conversation_running(conversation_id, run_id)

    assert not interrupt_running_agent(conversation_id=conversation_id)


def test_interrupt_running_agent_cancels_attached_task():
    conversation_id = "conv-task-interrupt"
    run_id = "run-task-interrupt"
    active_conversation_run_ids.pop(conversation_id, None)
    active_run_tasks.pop(run_id, None)

    async def sleeper():
        await asyncio.sleep(60)

    async def scenario():
        task = asyncio.create_task(sleeper())
        mark_conversation_running(conversation_id, run_id)
        attach_running_task(run_id, task)
        try:
            assert interrupt_running_agent(conversation_id=conversation_id)
            await asyncio.sleep(0)
            assert task.cancelled()
        finally:
            clear_conversation_running(conversation_id, run_id)

    asyncio.run(scenario())


def test_mark_interrupt_requested_updates_run_and_conversation(tmp_path):
    conversations = ConversationStore(tmp_path)
    conversation = conversations.create()
    conversations.set_status(conversation.id, "running")
    runs = AgentRunStore(tmp_path)
    run = runs.start(conversation.id, "hello")
    mark_conversation_running(conversation.id, run.run_id)
    try:
        record = mark_interrupt_requested(runs, conversations, conversation_id=conversation.id)
    finally:
        clear_conversation_running(conversation.id, run.run_id)

    assert record is not None
    assert record.status == "interrupted"
    assert conversations.load(conversation.id).status == "interrupted"
