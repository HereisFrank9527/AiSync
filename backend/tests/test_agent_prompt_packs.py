import asyncio

import pytest

from app.agent import AgentLLMError, MasterAgent
from app.change_approvals import resolve_change_set_decision
from app.change_sets import apply_change_set, discard_change_set, hash_text, load_change_set
from app.core import prompt_pack_rendering
from app.core.prompt_packs import PromptPack, PromptPackCreate, PromptPackStore
from app.llm.types import ChatRequest, ChatResponse
from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolResult
from app.tools.factory import create_tool_registry
from app.tools.file_change_proposal import FileChangeProposalTool
from app.tools.read_project_files import ReadProjectFilesTool
from app.tools.registry import ToolRegistry


class DummyLLM:
    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        return ChatResponse(content=[], text="ok")


class TruncatedLLM:
    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        if on_text_delta:
            await on_text_delta("未写完的半句")
        return ChatResponse(content=[], text="未写完的半句", stop_reason="length")


class SlowSettings:
    llm_request_timeout = 1


class SlowLLM:
    settings = SlowSettings()

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        import asyncio

        await asyncio.sleep(5)
        return ChatResponse(content=[], text="late")


class StreamingSlowLLM:
    settings = SlowSettings()

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        import asyncio

        await asyncio.sleep(0.6)
        if on_text_delta:
            await on_text_delta("a")
        await asyncio.sleep(0.6)
        if on_text_delta:
            await on_text_delta("b")
        return ChatResponse(content=[], text="ab")


class SilentStreamingLLM:
    settings = SlowSettings()

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        import asyncio

        await asyncio.sleep(5)
        return ChatResponse(content=[], text="late")


class ToolCallingLLM:
    def __init__(self):
        self.calls = 0
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1 and request.tools:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[{"id": "call-1", "name": "route_test", "input": {"value": "x"}}],
            )
        return ChatResponse(content=[], text="done")


class FileChangeProposalLLM:
    def __init__(self):
        self.calls = 0
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1 and request.tools:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "file_change_proposal",
                        "input": {
                            "title": "更新测试文件",
                            "changes": [
                                {
                                    "path": "notes.md",
                                    "new_content": "new\n",
                                    "reason": "测试自动应用",
                                }
                            ],
                        },
                    }
                ],
            )
        return ChatResponse(content=[], text="done")


class MultipleFileChangeProposalLLM:
    def __init__(self):
        self.calls = 0
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1 and request.tools:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {
                        "id": "call-batch-1",
                        "name": "file_change_proposal",
                        "input": {
                            "title": "更新世界观",
                            "changes": [{"path": "world/overview.md", "new_content": "new world\n"}],
                        },
                    },
                    {
                        "id": "call-batch-2",
                        "name": "file_change_proposal",
                        "input": {
                            "title": "更新角色",
                            "changes": [{"path": "characters/lin/profile.md", "new_content": "new role\n"}],
                        },
                    },
                ],
            )
        return ChatResponse(content=[], text="batch done")


class MultipleMutationLLM:
    def __init__(self):
        self.calls = 0

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        if self.calls == 1 and request.tools:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {"id": "call-write-1", "name": "stateful_write", "input": {}},
                    {"id": "call-write-2", "name": "stateful_write", "input": {}},
                ],
            )
        return ChatResponse(content=[], text="write batch rejected")


class ToolContinueFailingLLM:
    def __init__(self):
        self.calls = 0
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1 and request.tools:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[{"id": "call-1", "name": "route_test", "input": {"value": "x"}}],
            )
        if self.calls == 2 and request.tools:
            raise RuntimeError("Error code: 400 invalid_request: tool continuation failed")
        return ChatResponse(content=[], text="fallback done")


class ToolContinueGenericFailingLLM(ToolContinueFailingLLM):
    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1 and request.tools:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[{"id": "call-1", "name": "route_test", "input": {"value": "x"}}],
            )
        raise RuntimeError("generic provider failure")


class MultiStepToolLLM:
    def __init__(self):
        self.calls = 0
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1 and request.tools:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[{"id": "call-1", "name": "route_test", "input": {"value": "one"}}],
            )
        if self.calls == 2 and request.tools:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[{"id": "call-2", "name": "route_test", "input": {"value": "two"}}],
            )
        return ChatResponse(content=[], text="multi done")


class RepeatingToolLLM:
    def __init__(self):
        self.calls = 0
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        self.requests.append(request)
        if self.calls in {1, 2} and request.tools:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[{"id": f"call-{self.calls}", "name": "route_test", "input": {"value": "same"}}],
            )
        return ChatResponse(content=[], text="done after duplicate")


class RepeatingFailureLLM:
    def __init__(self):
        self.calls = 0

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        return ChatResponse(
            content=[],
            text="",
            tool_calls=[{"id": f"call-{self.calls}", "name": "failing_tool", "input": {"attempt": self.calls}}],
        )


class ReadOnlyBudgetLLM:
    def __init__(self):
        self.calls = 0
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        self.requests.append(request)
        if any(tool.get("name") == "search_budget" for tool in request.tools):
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {
                        "id": f"search-{self.calls}",
                        "name": "search_budget",
                        "input": {"query": f"检索 {self.calls}"},
                    }
                ],
            )
        return ChatResponse(content=[], text="已停止继续检索")


class ReadOnlyBudgetTool(BaseTool):
    name = "search_budget"
    description = "测试只读检索预算"
    category = "search"
    write_policy = "none"

    def __init__(self):
        self.execute_count = 0

    def schema(self):
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        }

    async def execute(self, params, context):
        self.execute_count += 1
        return ToolResult(content=f"找到：{params['query']}")


class ParallelDiscoveryReadLLM:
    def __init__(self):
        self.calls = 0
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {
                        "id": "inspect-1",
                        "name": "read_project_files",
                        "input": {"mode": "inspect", "paths": ["notes.md"]},
                    },
                    *[
                        {
                            "id": f"search-{index}",
                            "name": "search_budget",
                            "input": {"query": f"检索 {index}"},
                        }
                        for index in range(5)
                    ],
                ],
            )
        return ChatResponse(content=[], text="已保留精确读取能力")


class PatchRecoveryLLM:
    def __init__(self):
        self.calls = 0
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {
                        "id": "proposal-bad",
                        "name": "file_change_proposal",
                        "input": {
                            "title": "修正文案",
                            "changes": [
                                {
                                    "path": "notes.md",
                                    "operation": "replace_text",
                                    "old_text": "并不存在的原文",
                                    "new_text": "更新后的正文",
                                }
                            ],
                        },
                    }
                ],
            )
        if self.calls == 2:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {
                        "id": "read-recovery",
                        "name": "read_project_files",
                        "input": {"mode": "content", "paths": ["notes.md"]},
                    }
                ],
            )
        if self.calls == 3:
            return ChatResponse(
                content=[],
                text="",
                tool_calls=[
                    {
                        "id": "proposal-fixed",
                        "name": "file_change_proposal",
                        "input": {
                            "title": "修正文案",
                            "changes": [
                                {
                                    "path": "notes.md",
                                    "operation": "replace_lines",
                                    "start_line": 1,
                                    "end_line": 1,
                                    "source_hash": hash_text("实际正文\n第二行\n"),
                                    "new_text": "更新后的正文",
                                }
                            ],
                        },
                    }
                ],
            )
        return ChatResponse(content=[], text="恢复完成")


class SearchWriteSearchLLM:
    def __init__(self):
        self.calls = 0

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            return ChatResponse(content=[], text="", tool_calls=[{"id": "search-1", "name": "route_test", "input": {"value": "same"}}])
        if self.calls == 2:
            return ChatResponse(content=[], text="", tool_calls=[{"id": "write-1", "name": "stateful_write", "input": {}}])
        if self.calls == 3:
            return ChatResponse(content=[], text="", tool_calls=[{"id": "search-2", "name": "route_test", "input": {"value": "same"}}])
        return ChatResponse(content=[], text="verified")


class ToolRouteLLM:
    pass


class RouteTestTool(BaseTool):
    name = "route_test"
    description = "route test"

    def __init__(self):
        self.used_invoke = False
        self.used_execute = False
        self.execute_count = 0
        self.invoke_count = 0
        self.invoked_llm = None

    def schema(self):
        return {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "additionalProperties": False,
        }

    async def execute(self, params, context):
        self.used_execute = True
        self.execute_count += 1
        return ToolResult(content="execute")

    async def invoke(self, params, context, llm):
        self.used_invoke = True
        self.invoke_count += 1
        self.invoked_llm = llm
        return ToolResult(content="invoke")


class FailingTool(BaseTool):
    name = "failing_tool"
    description = "always fails"

    def schema(self):
        return {"type": "object", "properties": {"attempt": {"type": "integer"}}}

    async def execute(self, params, context):
        raise RuntimeError("expected failure")


class StatefulWriteTool(BaseTool):
    name = "stateful_write"
    description = "changes project state"
    category = "edit"
    write_policy = "direct"

    def schema(self):
        return {"type": "object", "properties": {}}

    async def execute(self, params, context):
        await context.write_text("state.txt", "changed")
        return ToolResult(content="changed")


def test_agent_initial_messages_include_prompt_packs(tmp_path):
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
    )
    pack = PromptPack(
        name="冷峻文风",
        category="style",
        stages=["chat"],
        content="语言克制，减少解释。",
        description="默认文风",
    )

    messages = agent._build_initial_messages(
        "写一段开场",
        relevant_context=[],
        foreshadow_context="",
        history=[],
        memory_summary="",
        prompt_packs=[pack],
    )

    assert len(messages) == 2
    assert "提示词包：冷峻文风" in messages[0]["content"]
    assert "语言克制，减少解释。" in messages[0]["content"]
    assert messages[-1]["content"] == "写一段开场"


def test_agent_normalizes_old_all_tools_list_to_include_file_change_proposal(tmp_path):
    registry = create_tool_registry()
    all_names = {schema["name"] for schema in registry.get_all_schemas()}
    old_frontend_all_tools = all_names - {"file_change_proposal", "consistency_check"}
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    normalized = agent._normalize_enabled_tools(old_frontend_all_tools)

    assert normalized is not None
    assert "file_change_proposal" in normalized
    assert "consistency_check" not in normalized


def test_agent_does_not_add_file_change_proposal_to_small_manual_tool_subset(tmp_path):
    registry = create_tool_registry()
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    normalized = agent._normalize_enabled_tools({"search_project"})

    assert normalized == {"search_project"}


def test_agent_does_not_infer_patch_permission_from_user_text(tmp_path):
    registry = create_tool_registry()
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    normalized = agent._normalize_enabled_tools({"search_project"})

    assert normalized == {"search_project"}


def test_agent_adds_file_change_proposal_to_editing_tool_subset(tmp_path):
    registry = create_tool_registry()
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    normalized = agent._normalize_enabled_tools({"outline_generate"})

    assert normalized == {"outline_generate", "file_change_proposal"}


def test_agent_hides_legacy_file_mutators_when_patch_tool_is_available(tmp_path):
    registry = create_tool_registry()
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    names = {schema["name"] for schema in agent._request_tool_schemas(None)}

    assert "file_change_proposal" in names
    assert not {"edit_chapter", "update_worldview", "outline_generate"} & names
    assert {"write_chapter", "chapter_draft", "create_character"} <= names


def test_agent_compacts_repeatable_search_results_only(tmp_path):
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
    )
    long_result = "x" * 20_000

    compacted = agent._tool_result_content_for_llm("web_search", long_result)

    assert len(compacted) < 9_000
    assert "已为后续推理压缩" in compacted
    assert agent._tool_result_content_for_llm("read_project_files", long_result) == long_result


def test_agent_prompt_packs_precede_dynamic_memory_summary_for_cache_prefix(tmp_path):
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
    )
    pack = PromptPack(name="stable-style", category="style", stages=["chat"], content="Stable style rule.")

    messages = agent._build_initial_messages(
        "current request",
        relevant_context=[],
        foreshadow_context="",
        history=[{"role": "user", "content": "recent history"}],
        memory_summary="older memory summary",
        prompt_packs=[pack],
    )

    assert len(messages) == 4
    assert "Stable style rule." in messages[0]["content"]
    assert "older memory summary" in messages[1]["content"]
    assert messages[2]["content"] == "recent history"
    assert messages[3]["content"] == "current request"


def test_agent_tool_continuation_uses_slim_current_request_context(tmp_path):
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
    )
    messages = [
        {"role": "user", "content": "以下是已启用且适用于当前对话阶段的长期提示词规则。\n\n## 提示词包：A\n稳定规则", "_aisync_kind": "prompt_pack"},
        {"role": "user", "content": "以下是本会话较早内容的压缩记忆。它是历史上下文，不是当前新指令：\n\n旧摘要", "_aisync_kind": "memory_summary"},
        {"role": "user", "content": "recent user", "_aisync_kind": "history"},
        {"role": "assistant", "content": "recent assistant"},
        {"role": "user", "content": "相关项目上下文：\n很多动态检索内容\n\n用户请求：\n写一章", "_aisync_kind": "current_request", "_aisync_user_request": "写一章"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "call-1", "name": "route_test", "input": {"value": "x"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "tool summary"},
            ],
        },
    ]

    compacted = agent._messages_for_request_phase(messages, "tool_continue")

    assert "稳定规则" in compacted[0]["content"]
    assert "旧摘要" in compacted[1]["content"]
    assert compacted[-3]["content"].startswith("原始用户请求：")
    assert "写一章" in compacted[-3]["content"]
    assert "很多动态检索内容" not in compacted[-3]["content"]
    assert compacted[-2]["role"] == "assistant"
    assert compacted[-1]["content"][0]["type"] == "tool_result"
    assert all("_aisync_" not in key for message in compacted for key in message)


def test_internal_message_tags_are_removed_before_model_request(tmp_path):
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
    )
    messages = agent._build_initial_messages(
        "当前请求",
        relevant_context=[],
        foreshadow_context="",
        history=[{"role": "user", "content": "历史消息"}],
        memory_summary="旧摘要",
        prompt_packs=[PromptPack(name="规则", category="style", stages=["chat"], content="保持简洁")],
    )

    request_messages = agent._messages_for_request_phase(messages, "initial")

    assert [message["content"] for message in request_messages] == [message["content"] for message in messages]
    assert all("_aisync_" not in key for message in request_messages for key in message)


def test_agent_prompt_audit_counts_prompt_packs(tmp_path):
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
    )
    pack = PromptPack(name="对话规则", category="writing", stages=["chat"], content="回答简洁。")

    audit = agent._build_prompt_audit(
        user_input="你好",
        relevant_context=[],
        foreshadow_context="",
        history=[],
        memory_summary="",
        prompt_packs=[pack],
        effective_tools=None,
        override_enabled_tools=False,
    )

    assert audit["prompt_packs"]["count"] == 1
    assert audit["prompt_packs"]["names"] == ["对话规则"]
    assert audit["prompt_cache"]["layout"] == "system + prompt_packs + memory_summary + recent_history + dynamic_context"
    assert audit["prompt_cache"]["stable_prefix_messages"] == 1


async def test_agent_uses_project_prompt_pack_settings(tmp_path, monkeypatch):
    store = PromptPackStore(tmp_path / "prompt_packs.json")
    selected = store.create(
        PromptPackCreate(name="本项目对话规则", category="writing", stages=["chat"], content="回答更克制。")
    )
    store.create(
        PromptPackCreate(name="其他项目对话规则", category="writing", stages=["chat"], content="回答更热闹。")
    )
    monkeypatch.setattr(prompt_pack_rendering, "prompt_pack_store", store)
    context = ProjectContext(tmp_path / "novel")
    await prompt_pack_rendering.save_project_prompt_pack_settings(context, "project", [selected.id])
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=ToolRegistry(),
        project=context,
    )

    await agent.run("你好")

    assert agent.last_prompt_audit["prompt_packs"]["names"] == ["本项目对话规则"]


async def test_agent_routes_tool_invoke_to_tool_llm(tmp_path):
    tool = RouteTestTool()
    registry = ToolRegistry()
    registry.register(tool)
    route_llm = ToolRouteLLM()

    async def resolve_tool_llm(name: str):
        if name == "route_test":
            return route_llm, "cheap-checker"
        return None, None

    tool_calling_llm = ToolCallingLLM()
    agent = MasterAgent(
        llm_client=tool_calling_llm,
        tool_registry=registry,
        project=ProjectContext(tmp_path),
        tool_llm_resolver=resolve_tool_llm,
    )

    result = await agent.run("run routed tool", max_iterations=2)

    assert result == "done"
    assert tool.used_invoke
    assert not tool.used_execute
    assert tool.invoked_llm is route_llm
    assert len(tool_calling_llm.requests) == 2
    assert tool_calling_llm.requests[0].stream is True
    assert tool_calling_llm.requests[0].tools
    assert tool_calling_llm.requests[1].stream is True
    assert tool_calling_llm.requests[1].tools == []
    usage = agent.last_prompt_audit["usage"]
    assert usage["last_request_phase"] == "tool_finalize"
    assert usage["llm_calls"][0]["phase"] == "initial"
    assert usage["llm_calls"][0]["tool_count"] > 0
    assert usage["llm_calls"][1]["phase"] == "tool_finalize"
    assert usage["llm_calls"][1]["tool_count"] == 0
    assert usage["llm_calls"][1]["has_tool_result"] is True
    assert usage["termination_reason"] == "completed"
    assert agent.last_prompt_audit["tool_llm_routes"] == [{"tool": "route_test", "preset_id": "cheap-checker"}]


async def test_agent_tool_continuation_can_call_more_tools(tmp_path):
    tool = RouteTestTool()
    registry = ToolRegistry()
    registry.register(tool)
    llm = MultiStepToolLLM()
    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    result = await agent.run("run multiple tools", max_iterations=4)

    assert result == "multi done"
    assert len(llm.requests) == 3
    assert llm.requests[1].stream is True
    assert llm.requests[1].tools
    assert llm.requests[2].stream is True
    assert llm.requests[2].tools
    usage = agent.last_prompt_audit["usage"]
    assert [call["phase"] for call in usage["llm_calls"]] == ["initial", "tool_continue", "tool_continue"]
    assert usage["tool_calls"] == 2


async def test_agent_loop_skips_exact_duplicate_tool_calls(tmp_path):
    tool = RouteTestTool()
    registry = ToolRegistry()
    registry.register(tool)
    llm = RepeatingToolLLM()
    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    result = await agent.run("repeat the same tool", max_iterations=4)

    assert result == "done after duplicate"
    assert len(llm.requests) == 3
    assert tool.execute_count == 1
    usage = agent.last_prompt_audit["usage"]
    assert usage["tool_calls"] == 2
    assert usage["duplicate_tool_calls"] == 1
    assert usage["tool_batches"][1]["tools"][0]["status"] == "duplicate"


async def test_agent_allows_same_read_after_project_state_changes(tmp_path):
    read_tool = RouteTestTool()
    registry = ToolRegistry()
    registry.register(read_tool)
    registry.register(StatefulWriteTool())
    agent = MasterAgent(
        llm_client=SearchWriteSearchLLM(),
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    result = await agent.run("search, write, then verify", max_iterations=5)

    assert result == "verified"
    assert read_tool.execute_count == 2
    assert agent.last_prompt_audit["usage"]["duplicate_tool_calls"] == 0


async def test_agent_stops_after_two_no_progress_tool_batches(tmp_path):
    registry = ToolRegistry()
    registry.register(FailingTool())
    llm = RepeatingFailureLLM()
    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    result = await agent.run("run failing tool", max_iterations=6)

    assert "连续两轮工具调用" in result
    usage = agent.last_prompt_audit["usage"]
    assert llm.calls == 2
    assert usage["failed_tool_calls"] == 2
    assert usage["termination_reason"] == "human_intervention"
    assert usage["intervention"]["kind"] == "tool_stalled"
    assert [item["id"] for item in usage["intervention"]["options"]] == ["retry", "finalize", "clarify"]


async def test_agent_pauses_repeated_discovery_without_hiding_exact_reader(tmp_path):
    registry = ToolRegistry()
    registry.register(ReadOnlyBudgetTool())
    registry.register(ReadProjectFilesTool())
    llm = ReadOnlyBudgetLLM()
    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    result = await agent.run("清理临时文件", max_iterations=6)

    assert result == "已停止继续检索"
    assert llm.calls == 3
    assert all(
        any(tool.get("name") == "search_budget" for tool in request.tools)
        for request in llm.requests[:2]
    )
    assert [tool["name"] for tool in llm.requests[2].tools] == ["read_project_files"]
    assert agent.last_prompt_audit["usage"]["read_only_tool_calls"] == 2
    assert agent.last_prompt_audit["usage"]["discovery_tool_calls"] == 2
    assert agent.last_prompt_audit["usage"]["read_only_budget_exhausted"] is True


async def test_agent_limits_parallel_discovery_without_consuming_exact_reads(tmp_path):
    discovery = ReadOnlyBudgetTool()
    registry = ToolRegistry()
    registry.register(discovery)
    registry.register(ReadProjectFilesTool())
    context = ProjectContext(tmp_path)
    await context.write_text("notes.md", "正文\n")
    llm = ParallelDiscoveryReadLLM()
    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        project=context,
    )

    result = await agent.run("先检查再检索", max_iterations=4)

    assert result == "已保留精确读取能力"
    assert discovery.execute_count == 3
    second_tool_names = {tool["name"] for tool in llm.requests[1].tools}
    assert "read_project_files" in second_tool_names
    assert "search_budget" in second_tool_names
    usage = agent.last_prompt_audit["usage"]
    assert usage["exact_read_tool_calls"] == 1
    assert usage["discovery_tool_calls"] == 3
    assert usage["budget_blocked_tool_calls"] == 2
    assert usage["tool_batches"][0]["blocked"] == 2


async def test_agent_recovers_from_non_matching_patch_with_exact_read(tmp_path):
    registry = ToolRegistry()
    registry.register(FileChangeProposalTool())
    registry.register(ReadProjectFilesTool())
    context = ProjectContext(tmp_path)
    await context.write_text("notes.md", "实际正文\n第二行\n")
    llm = PatchRecoveryLLM()
    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        project=context,
    )

    result = await agent.run("修正文案", auto_apply_file_changes=True, max_iterations=6)

    assert result == "恢复完成"
    assert await context.read_text("notes.md") == "更新后的正文\n第二行\n"
    assert [tool["name"] for tool in llm.requests[1].tools] == ["read_project_files"]
    assert "file_change_proposal" in {tool["name"] for tool in llm.requests[2].tools}
    usage = agent.last_prompt_audit["usage"]
    assert usage["patch_recovery_attempts"] == 1
    assert usage["patch_recovery_reads"] == 1
    assert usage["patch_recovery_paths"] == []
    assert usage["consecutive_no_progress_batches"] == 0


async def test_agent_tool_continuation_falls_back_to_safe_finalize(tmp_path):
    tool = RouteTestTool()
    registry = ToolRegistry()
    registry.register(tool)
    llm = ToolContinueFailingLLM()
    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    result = await agent.run("run tool with fallback", max_iterations=3)

    assert result == "fallback done"
    assert len(llm.requests) == 3
    assert llm.requests[1].tools
    assert llm.requests[2].tools == []
    usage = agent.last_prompt_audit["usage"]
    assert [call["phase"] for call in usage["llm_calls"]] == ["initial", "tool_continue", "tool_finalize"]
    assert usage["llm_calls"][1]["status"] == "failed"
    assert usage["llm_calls"][2]["tool_count"] == 0
    assert usage["safe_finalize_attempts"] == 1


async def test_agent_does_not_auto_resend_generic_tool_continuation_failure(tmp_path):
    tool = RouteTestTool()
    registry = ToolRegistry()
    registry.register(tool)
    llm = ToolContinueGenericFailingLLM()
    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        project=ProjectContext(tmp_path),
    )

    with pytest.raises(AgentLLMError, match="模型请求失败"):
        await agent.run("run tool without hidden resend", max_iterations=4)

    assert len(llm.requests) == 2
    assert agent.last_prompt_audit["usage"]["safe_finalize_attempts"] == 0


def test_agent_maximum_context_window_expands_memory_and_context(tmp_path):
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
        context_window="maximum",
    )
    history = [
        {"role": "user", "content": f"历史消息 {index}"}
        for index in range(80)
    ]
    relevant_context = [
        {"path": f"world/{index}.md", "content": "设定" * 1400}
        for index in range(20)
    ]

    messages = agent._build_initial_messages(
        "继续写",
        relevant_context=relevant_context,
        foreshadow_context="",
        history=history,
        memory_summary="",
        prompt_packs=[],
    )
    audit = agent._build_prompt_audit(
        user_input="继续写",
        relevant_context=relevant_context,
        foreshadow_context="",
        history=history,
        memory_summary="",
        prompt_packs=[],
        effective_tools=None,
        override_enabled_tools=False,
    )

    assert audit["context_window"]["mode"] == "maximum"
    assert audit["memory"]["injected_recent_messages"] == 80
    assert audit["context_window"]["vector_top_k"] == 24
    assert "world/19.md" in messages[-1]["content"]


def test_agent_deduplicates_vector_context_and_limits_chunks_per_path(tmp_path):
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
    )
    relevant_context = [
        {
            "path": "chapters/ch-01.md",
            "chunk_id": f"chapter-{index}",
            "content": f"第一章片段 {index}",
        }
        for index in range(5)
    ]
    relevant_context.extend(
        [
            {
                "path": "chapters/ch-01.md",
                "chunk_id": "duplicate-id",
                "content": "第一章片段 0",
            },
            {
                "path": "world/overview.md",
                "chunk_id": "world-1",
                "content": "世界观片段",
            },
        ]
    )

    selected = agent._dedupe_relevant_context(relevant_context, limit=24)
    audit = agent._build_prompt_audit(
        user_input="继续写",
        relevant_context=selected,
        foreshadow_context="",
        history=[],
        memory_summary="",
        prompt_packs=[],
        effective_tools=None,
        override_enabled_tools=False,
        raw_relevant_context_count=len(relevant_context),
    )

    assert [item["path"] for item in selected].count("chapters/ch-01.md") == 3
    assert [item["path"] for item in selected].count("world/overview.md") == 1
    assert audit["vector_context"]["raw_count"] == 7
    assert audit["vector_context"]["count"] == 4
    assert audit["vector_context"]["deduplicated"] == 3


def test_agent_summarizes_failed_patch_parameters_without_full_new_content(tmp_path):
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
    )

    summary = agent._summarize_params(
        {
            "title": "修正文案",
            "changes": [
                {
                    "path": "chapters/ch-01.md",
                    "operation": "replace_text",
                    "old_text": "需要精确匹配的原句",
                    "new_text": "新正文" * 1000,
                }
            ],
        }
    )

    change = summary["changes"][0]
    assert change["path"] == "chapters/ch-01.md"
    assert change["operation"] == "replace_text"
    assert change["old_text"] == "需要精确匹配的原句"
    assert change["new_text_chars"] == 3000
    assert "new_text" not in change


def test_agent_economy_context_window_limits_memory_and_context(tmp_path):
    agent = MasterAgent(
        llm_client=DummyLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
        context_window="economy",
    )
    history = [
        {"role": "user", "content": f"历史消息 {index}"}
        for index in range(20)
    ]
    relevant_context = [
        {"path": f"world/{index}.md", "content": "设定" * 200}
        for index in range(10)
    ]

    messages = agent._build_initial_messages(
        "继续写",
        relevant_context=relevant_context,
        foreshadow_context="",
        history=history,
        memory_summary="",
        prompt_packs=[],
    )
    audit = agent._build_prompt_audit(
        user_input="继续写",
        relevant_context=relevant_context,
        foreshadow_context="",
        history=history,
        memory_summary="",
        prompt_packs=[],
        effective_tools=None,
        override_enabled_tools=False,
    )

    assert audit["context_window"]["mode"] == "economy"
    assert audit["memory"]["injected_recent_messages"] == 8
    assert "world/3.md" in messages[-1]["content"]
    assert "world/4.md" not in messages[-1]["content"]


async def test_agent_llm_request_timeout_is_classified(tmp_path):
    agent = MasterAgent(
        llm_client=SlowLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
    )

    with pytest.raises(AgentLLMError) as error:
        await agent._chat_with_timeout(ChatRequest(messages=[{"role": "user", "content": "hello"}]))

    assert error.value.category == "timeout"
    usage = agent.last_prompt_audit["usage"]
    assert usage["last_error_category"] == "timeout"
    assert usage["request_timeout_seconds"] == 1
    assert usage["request_timeout_mode"] == "total"


async def test_agent_streaming_timeout_tracks_idle_time_not_total_time(tmp_path):
    agent = MasterAgent(
        llm_client=StreamingSlowLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
    )
    deltas: list[str] = []

    async def on_text_delta(delta: str) -> None:
        deltas.append(delta)

    response = await agent._chat_with_timeout(
        ChatRequest(messages=[{"role": "user", "content": "hello"}], stream=True),
        on_text_delta=on_text_delta,
    )

    assert response.text == "ab"
    assert deltas == ["a", "b"]
    usage = agent.last_prompt_audit["usage"]
    assert usage["request_timeout_seconds"] == 1
    assert usage["request_timeout_mode"] == "idle"
    assert usage["request_stream_requested"] is True


async def test_agent_streaming_timeout_still_fails_without_progress(tmp_path):
    agent = MasterAgent(
        llm_client=SilentStreamingLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
    )

    async def on_text_delta(delta: str) -> None:
        pass

    with pytest.raises(AgentLLMError) as error:
        await agent._chat_with_timeout(
            ChatRequest(messages=[{"role": "user", "content": "hello"}], stream=True),
            on_text_delta=on_text_delta,
        )

    assert error.value.category == "timeout"
    usage = agent.last_prompt_audit["usage"]
    assert usage["last_error_category"] == "timeout"
    assert usage["request_timeout_mode"] == "idle"


async def test_agent_marks_length_limited_reply_as_incomplete(tmp_path):
    events: list[dict] = []

    async def publish(event: dict) -> None:
        events.append(event)

    agent = MasterAgent(
        llm_client=TruncatedLLM(),
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
        publisher=publish,
    )

    result = await agent.run("继续", on_text_delta=lambda _delta: _async_noop())

    assert result.startswith("未写完的半句")
    assert "未完整生成" in result
    assert agent.last_prompt_audit["usage"]["termination_reason"] == "output_truncated"
    assert agent.last_prompt_audit["usage"]["output_truncated"] is True
    assert any(event.get("type") == "output_truncated" for event in events)


async def _async_noop() -> None:
    return None


async def test_agent_file_change_proposal_keeps_manual_review_by_default(tmp_path):
    registry = ToolRegistry()
    registry.register(FileChangeProposalTool())
    context = ProjectContext(tmp_path)
    await context.write_text("notes.md", "old\n")
    events: list[dict] = []
    proposal_ready = asyncio.Event()

    async def publish(event: dict) -> None:
        events.append(event)
        if event.get("type") == "tool_result" and event.get("ui_hint", {}).get("type") == "changeset:proposal":
            proposal_ready.set()

    agent = MasterAgent(
        llm_client=FileChangeProposalLLM(),
        tool_registry=registry,
        project=context,
        publisher=publish,
    )

    task = asyncio.create_task(agent.run("更新文件"))
    await asyncio.wait_for(proposal_ready.wait(), timeout=2)
    assert not task.done()
    proposal = next(event for event in events if event.get("ui_hint", {}).get("type") == "changeset:proposal")
    change_set_id = proposal["ui_hint"]["data"]["id"]
    await apply_change_set(context, change_set_id)
    assert resolve_change_set_decision(context.root, change_set_id, "applied")
    result = await asyncio.wait_for(task, timeout=2)

    assert result == "done"
    assert await context.read_text("notes.md") == "new\n"
    phases = [event.get("metadata", {}).get("phase") for event in events if event.get("type") == "agent_status"]
    assert "waiting_approval" in phases
    assert "verifying" in phases
    assert agent.last_prompt_audit["usage"]["change_approvals"][0]["decision"] == "applied"


async def test_agent_coalesces_multiple_change_proposals_and_enters_read_only_verification(tmp_path):
    registry = ToolRegistry()
    registry.register(FileChangeProposalTool())
    registry.register(ReadProjectFilesTool())
    context = ProjectContext(tmp_path)
    await context.write_text("world/overview.md", "old world\n")
    await context.write_text("characters/lin/profile.md", "old role\n")
    events: list[dict] = []
    proposal_ready = asyncio.Event()
    llm = MultipleFileChangeProposalLLM()

    async def publish(event: dict) -> None:
        events.append(event)
        if event.get("type") == "tool_result" and event.get("ui_hint", {}).get("type") == "changeset:proposal":
            proposal_ready.set()

    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        project=context,
        publisher=publish,
    )
    task = asyncio.create_task(agent.run("同时更新世界观和角色"))
    await asyncio.wait_for(proposal_ready.wait(), timeout=2)

    proposals = [event for event in events if event.get("ui_hint", {}).get("type") == "changeset:proposal"]
    assert len(proposals) == 1
    proposal = proposals[0]
    assert len(proposal["ui_hint"]["data"]["changes"]) == 2
    change_set_id = proposal["ui_hint"]["data"]["id"]
    await apply_change_set(context, change_set_id)
    assert resolve_change_set_decision(context.root, change_set_id, "applied")

    assert await asyncio.wait_for(task, timeout=2) == "batch done"
    assert await context.read_text("world/overview.md") == "new world\n"
    assert await context.read_text("characters/lin/profile.md") == "new role\n"
    assert [schema["name"] for schema in llm.requests[1].tools] == ["read_project_files"]
    usage = agent.last_prompt_audit["usage"]
    assert usage["coalesced_change_proposals"] == 1
    assert usage["applied_change_sets"][0]["status"] == "verified"
    update = next(event for event in events if event.get("type") == "changeset_update")
    assert update["ui_hint"]["data"]["file_verification"]["verified"] == 2


async def test_agent_blocks_multiple_direct_writes_in_one_tool_batch(tmp_path):
    registry = ToolRegistry()
    registry.register(StatefulWriteTool())
    events: list[dict] = []

    async def publish(event: dict) -> None:
        events.append(event)

    context = ProjectContext(tmp_path)
    agent = MasterAgent(
        llm_client=MultipleMutationLLM(),
        tool_registry=registry,
        project=context,
        publisher=publish,
    )

    assert await agent.run("执行两个写入") == "write batch rejected"
    assert not await context.exists("state.txt")
    errors = [event for event in events if event.get("type") == "tool_call_error"]
    assert len(errors) == 1
    assert all("多个写入工具" in str(event.get("tool", {}).get("error") or "") for event in errors)
    usage = agent.last_prompt_audit["usage"]
    assert usage["failed_tool_calls"] == 1
    assert usage["duplicate_tool_calls"] == 1


async def test_agent_resumes_after_file_change_proposal_is_discarded(tmp_path):
    registry = ToolRegistry()
    registry.register(FileChangeProposalTool())
    context = ProjectContext(tmp_path)
    await context.write_text("notes.md", "old\n")
    events: list[dict] = []
    proposal_ready = asyncio.Event()

    async def publish(event: dict) -> None:
        events.append(event)
        if event.get("type") == "tool_result" and event.get("ui_hint", {}).get("type") == "changeset:proposal":
            proposal_ready.set()

    llm = FileChangeProposalLLM()
    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        project=context,
        publisher=publish,
    )

    task = asyncio.create_task(agent.run("更新文件"))
    await asyncio.wait_for(proposal_ready.wait(), timeout=2)
    proposal = next(event for event in events if event.get("ui_hint", {}).get("type") == "changeset:proposal")
    change_set_id = proposal["ui_hint"]["data"]["id"]
    await discard_change_set(context, change_set_id)
    assert resolve_change_set_decision(context.root, change_set_id, "discarded")
    result = await asyncio.wait_for(task, timeout=2)

    assert result == "done"
    assert await context.read_text("notes.md") == "old\n"
    assert agent.last_prompt_audit["usage"]["change_approvals"][0]["decision"] == "discarded"
    assert llm.requests[1].tools == []


async def test_agent_file_change_approval_timeout_keeps_proposal_pending(tmp_path):
    registry = ToolRegistry()
    registry.register(FileChangeProposalTool())
    context = ProjectContext(tmp_path)
    await context.write_text("notes.md", "old\n")
    events: list[dict] = []
    llm = FileChangeProposalLLM()

    async def publish(event: dict) -> None:
        events.append(event)

    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        project=context,
        publisher=publish,
    )

    result = await agent.run("更新文件", file_change_approval_timeout_seconds=0.02)

    proposal = next(event for event in events if event.get("ui_hint", {}).get("type") == "changeset:proposal")
    change_set_id = proposal["ui_hint"]["data"]["id"]
    assert result == "done"
    assert (await load_change_set(context, change_set_id)).status == "pending"
    assert await context.read_text("notes.md") == "old\n"
    assert agent.last_prompt_audit["usage"]["change_approvals"][0]["decision"] == "timed_out"
    assert llm.requests[1].tools == []
    update = next(event for event in events if event.get("type") == "changeset_update")
    assert update["ui_hint"]["data"]["agent_waiting"] is False


async def test_agent_file_change_proposal_can_auto_apply(tmp_path):
    registry = ToolRegistry()
    registry.register(FileChangeProposalTool())
    context = ProjectContext(tmp_path)
    await context.write_text("notes.md", "old\n")
    events: list[dict] = []

    async def publish(event: dict) -> None:
        events.append(event)

    agent = MasterAgent(
        llm_client=FileChangeProposalLLM(),
        tool_registry=registry,
        project=context,
        publisher=publish,
    )

    result = await agent.run("更新文件", auto_apply_file_changes=True)

    assert result == "done"
    assert await context.read_text("notes.md") == "new\n"
    tool_result = next(event for event in events if event["type"] == "tool_result")
    assert "已自动应用改动" in tool_result["content"]
    assert tool_result["ui_hint"]["data"]["status"] == "applied"
