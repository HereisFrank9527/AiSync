import pytest

from app.llm.types import ChatResponse
from app.projects.context import ProjectContext
from app.tools.consistency_check import ConsistencyCheckTool


def test_consistency_check_ignores_outline_numbers_and_generic_ai_tokens():
    tool = ConsistencyCheckTool()
    issues = tool._inspect(
        "1. 新方案\n2. 服务 AI 响应\n3. 继续推进",
        [
            {
                "path": "plot/outline.md",
                "content": "1. 林铎建立防线。2. 机械圣教分裂。3. 服务AI只能执行有限命令。",
                "score": 0.5,
            }
        ],
        "",
    )

    assert issues == []


def test_consistency_check_does_not_treat_related_content_as_conflict():
    tool = ConsistencyCheckTool()
    issues = tool._inspect(
        "林铎进入黑雨城，试图接入天幕系统。",
        [
            {
                "path": "plot/outline.md",
                "content": "林铎在黑雨城接入天幕残轨通信塔，并获得城市扫描能力。",
                "score": 0.6,
            }
        ],
        "",
    )

    assert issues == []


def test_consistency_check_detects_same_entity_numeric_conflict():
    tool = ConsistencyCheckTool()
    issues = tool._inspect(
        "林铎的年龄为20岁。",
        [{"path": "characters/lin-duo/profile.md", "content": "林铎的年龄为19岁。", "score": 0.8}],
        "",
    )

    assert len(issues) == 1
    assert issues[0]["title"] == "数值设定可能不一致"
    assert "林铎" in issues[0]["detail"]
    assert issues[0]["new_snippet"] == "林铎的年龄为20岁"
    assert issues[0]["existing_snippet"] == "林铎的年龄为19岁"


def test_consistency_check_normalizes_chinese_and_arabic_numbers():
    tool = ConsistencyCheckTool()
    issues = tool._inspect(
        "林铎的年龄为20岁。",
        [{"path": "characters/lin-duo/profile.md", "content": "林铎的年龄为二十岁左右。", "score": 0.8}],
        "",
    )

    assert issues == []


def test_consistency_check_detects_conflict_with_chinese_number():
    tool = ConsistencyCheckTool()
    issues = tool._inspect(
        "林铎的年龄为21岁。",
        [{"path": "characters/lin-duo/profile.md", "content": "林铎的年龄为二十岁左右。", "score": 0.8}],
        "",
    )

    assert len(issues) == 1
    assert "21" in issues[0]["detail"]
    assert "20" in issues[0]["detail"]


def test_consistency_check_does_not_mix_different_entities_numeric_facts():
    tool = ConsistencyCheckTool()
    issues = tool._inspect(
        "林铎的年龄为20岁。",
        [{"path": "characters/xia-he/profile.md", "content": "夏禾的年龄为19岁。", "score": 0.8}],
        "",
    )

    assert issues == []


def test_consistency_check_detects_same_entity_state_conflict():
    tool = ConsistencyCheckTool()
    issues = tool._inspect(
        "沈砚秋已经死亡。",
        [{"path": "characters/shen-yanqiu/profile.md", "content": "沈砚秋仍然活着。", "score": 0.8}],
        "",
    )

    assert len(issues) == 1
    assert issues[0]["title"] == "状态设定可能冲突"


def test_consistency_check_skips_state_change_with_explicit_timeline():
    tool = ConsistencyCheckTool()
    issues = tool._inspect(
        "后来沈砚秋死亡。",
        [{"path": "characters/shen-yanqiu/profile.md", "content": "沈砚秋仍然活着。", "score": 0.8}],
        "",
    )

    assert issues == []


class StubConsistencyLLM:
    def __init__(self, text: str):
        self.text = text
        self.settings = type(
            "Settings",
            (),
            {"llm_model_name": "review-model", "llm_provider": "custom"},
        )()

    async def chat(self, request, on_text_delta=None):
        return ChatResponse(
            content=[],
            text=self.text,
            usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )


@pytest.mark.asyncio
async def test_consistency_exact_recall_prioritizes_character_profile(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text(
        "characters/lin-duo/profile.md",
        "# 林铎\n\n## 基本信息\n\n- 年龄：二十岁左右\n\n" + "废土经历。" * 250,
    )
    await context.write_text(
        "plot/outline.md",
        "# 大纲\n\n" + "林铎推进城市建设和势力发展。" * 150,
    )

    tool = ConsistencyCheckTool()
    related = await tool._related_context("林铎的年龄为21岁。", context, 8)

    assert related
    assert related[0]["path"] == "characters/lin-duo/profile.md", [
        (item["path"], item.get("score"), item.get("match_type"), item.get("matched_terms"))
        for item in related
    ]
    assert any("二十岁" in item["content"] for item in related)
    issues = tool._inspect("林铎的年龄为21岁。", related, "")
    assert len(issues) == 1
    assert issues[0]["path"] == "characters/lin-duo/profile.md"


@pytest.mark.asyncio
async def test_consistency_llm_can_confirm_no_conflict(monkeypatch, tmp_path):
    async def query(self, text, collections=None, top_k=10):
        return [{
            "path": "characters/lin-duo/profile.md",
            "content": "林铎的年龄为19岁。",
            "score": 0.8,
            "collection": "characters",
        }]

    monkeypatch.setattr("app.tools.consistency_check.ProjectVectorStore.query", query)
    tool = ConsistencyCheckTool()
    result = await tool.invoke(
        {"content": "林铎的年龄为20岁。"},
        ProjectContext(tmp_path),
        StubConsistencyLLM('{"issues": []}'),
    )

    assert result is not None
    assert result.ui_hint == {"type": "list:issues", "data": []}
    assert result.metadata["mode"] == "llm"
    assert result.metadata["mode_label"] == "LLM 复核"
    assert result.metadata["llm_output_valid"] is True
    assert result.metadata["llm_usage"]["total_tokens"] == 120
    assert result.metadata["llm_model"] == "review-model"
    assert result.metadata["llm_provider"] == "custom"
    assert result.metadata["reviewed_paths"] == ["characters/lin-duo/profile.md"]


@pytest.mark.asyncio
async def test_consistency_invalid_llm_output_uses_labeled_rule_fallback(monkeypatch, tmp_path):
    async def query(self, text, collections=None, top_k=10):
        return [{
            "path": "characters/lin-duo/profile.md",
            "content": "林铎的年龄为19岁。",
            "score": 0.8,
            "collection": "characters",
        }]

    monkeypatch.setattr("app.tools.consistency_check.ProjectVectorStore.query", query)
    tool = ConsistencyCheckTool()
    result = await tool.invoke(
        {"content": "林铎的年龄为20岁。"},
        ProjectContext(tmp_path),
        StubConsistencyLLM("无法输出 JSON"),
    )

    assert result is not None
    assert result.metadata["mode"] == "rules_fallback"
    assert result.metadata["llm_output_valid"] is False
    assert result.metadata["issue_count"] == 1


@pytest.mark.asyncio
async def test_consistency_without_candidates_does_not_claim_a_successful_review(monkeypatch, tmp_path):
    async def query(self, text, collections=None, top_k=10):
        return []

    monkeypatch.setattr("app.tools.consistency_check.ProjectVectorStore.query", query)
    tool = ConsistencyCheckTool()
    result = await tool.invoke(
        {"content": "一个没有可比对资料的新设定。", "limit": 999},
        ProjectContext(tmp_path),
        StubConsistencyLLM('{"issues": []}'),
    )

    assert result is not None
    assert result.metadata["mode"] == "no_candidates"
    assert result.metadata["related_chunks"] == 0
    assert "无法完成有效一致性审查" in result.content


def test_consistency_llm_rejects_unknown_paths_and_invalid_severity():
    tool = ConsistencyCheckTool()
    parsed, issues = tool._parse_llm_issues(
        '{"issues": ['
        '{"severity":"urgent","title":"真实路径","path":"world/overview.md","detail":"冲突"},'
        '{"severity":"critical","title":"虚构路径","path":"world/missing.md","detail":"冲突"}'
        "]}",
        [{"path": "world/overview.md", "score": 0.9, "collection": "world"}],
    )

    assert parsed is True
    assert len(issues) == 1
    assert issues[0]["severity"] == "notice"
    assert issues[0]["path"] == "world/overview.md"
