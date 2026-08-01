from app.agent import SYSTEM_PROMPT, MasterAgent
from app.api.agent import active_agents, discard_cached_agents_for_project, run_event
from app.conversations.runs import AgentRunRecord
from app.core.system_rules import compose_system_prompt, load_project_system_rules, save_project_system_rules
from app.llm.types import ChatRequest, ChatResponse
from app.projects.context import ProjectContext
from app.tools.registry import ToolRegistry


class CapturingLLM:
    def __init__(self):
        self.system = ""

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.system = request.system or ""
        return ChatResponse(content=[], text="ok")


async def test_project_system_rules_roundtrip(tmp_path):
    context = ProjectContext(tmp_path)

    initial = await load_project_system_rules(context)
    assert initial.mode == "default"
    assert initial.default_content

    saved = await save_project_system_rules(context, "project", "正式文件写入前先说明影响范围。")
    loaded = await load_project_system_rules(context)

    assert saved.mode == "project"
    assert loaded.mode == "project"
    assert loaded.content == "正式文件写入前先说明影响范围。\n"
    assert loaded.updated_at is not None
    assert await context.read_text("AGENT.md") == "正式文件写入前先说明影响范围。\n"


async def test_agent_md_is_loaded_directly(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text("AGENT.md", "# 当前文风\n\n- 避免连续单句成段。\n")

    loaded = await load_project_system_rules(context)

    assert loaded.mode == "project"
    assert "避免连续单句成段" in loaded.content


async def test_legacy_project_rules_migrate_to_agent_md(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_json(
        ".aisync/system_rules.json",
        {"mode": "project", "content": "旧项目规则", "updated_at": "legacy-time"},
    )

    loaded = await load_project_system_rules(context)

    assert loaded.mode == "project"
    assert loaded.content == "旧项目规则\n"
    assert loaded.updated_at == "legacy-time"
    assert await context.read_text("AGENT.md") == "旧项目规则\n"


def test_compose_system_prompt_appends_project_rules():
    prompt, audit = compose_system_prompt(
        SYSTEM_PROMPT,
        "default",
        type("Rules", (), {
            "mode": "project",
            "content": "临时草稿写入 temp/drafts。",
            "updated_at": "now",
        })(),
    )

    assert "## 当前项目 AGENT.md" in prompt
    assert "临时草稿写入 temp/drafts。" in prompt
    assert audit["source"] == "project"
    assert audit["base_source"] == "default"
    assert audit["project_rules"]["included"] is True


async def test_agent_prompt_audit_records_system_rules(tmp_path):
    llm = CapturingLLM()
    prompt, audit = compose_system_prompt(
        SYSTEM_PROMPT,
        "default",
        type("Rules", (), {
            "mode": "project",
            "content": "项目规则测试。",
            "updated_at": "now",
        })(),
    )
    agent = MasterAgent(
        llm_client=llm,
        tool_registry=ToolRegistry(),
        project=ProjectContext(tmp_path),
        system_prompt=prompt,
        system_prompt_audit=audit,
    )

    await agent.run("你好")

    assert "项目规则测试。" in llm.system
    assert agent.last_prompt_audit["system_prompt"]["source"] == "project"
    assert agent.last_prompt_audit["system_prompt"]["project_rules"]["included"] is True


def test_discard_cached_agents_for_project_only_removes_target_project(tmp_path):
    other_project = tmp_path / "other"
    active_agents.clear()
    try:
        active_agents[f"{tmp_path}:default:old"] = object()  # type: ignore[assignment]
        active_agents[f"{other_project}:default:keep"] = object()  # type: ignore[assignment]

        discard_cached_agents_for_project(str(tmp_path))

        assert f"{tmp_path}:default:old" not in active_agents
        assert f"{other_project}:default:keep" in active_agents
    finally:
        active_agents.clear()


def test_run_event_keeps_its_conversation_id():
    record = AgentRunRecord(
        run_id="run-1",
        conversation_id="conversation-1",
        status="running",
        phase="starting",
        phase_label="Starting",
        started_at="2026-07-31T00:00:00+00:00",
        updated_at="2026-07-31T00:00:00+00:00",
    )

    event = run_event(record)

    assert event["conversation_id"] == "conversation-1"
    assert event["run"]["conversation_id"] == "conversation-1"


def test_system_prompt_explains_agent_md_self_maintenance_boundary():
    assert "提议修改 `AGENT.md`" in SYSTEM_PROMPT
    assert "不能改变工具权限" in SYSTEM_PROMPT
