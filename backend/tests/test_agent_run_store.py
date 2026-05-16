from app.conversations.runs import AgentRunStore


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

    finished = store.finish(run.run_id, "completed")
    assert finished.status == "completed"
    assert finished.finished_at is not None

    latest = store.latest_for_conversation("conv-1")
    assert latest is not None
    assert latest.run_id == run.run_id


def test_agent_run_preview_is_truncated(tmp_path):
    store = AgentRunStore(tmp_path)
    run = store.start("conv-1", "x" * 300)

    assert len(run.input_preview) == 243
    assert run.input_preview.endswith("...")
