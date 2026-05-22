from app.agent import MasterAgent
from app.core import prompt_pack_rendering
from app.core.prompt_packs import PromptPack, PromptPackCreate, PromptPackStore
from app.llm.types import ChatRequest, ChatResponse
from app.projects.context import ProjectContext
from app.tools.registry import ToolRegistry


class DummyLLM:
    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        return ChatResponse(content=[], text="ok")


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
