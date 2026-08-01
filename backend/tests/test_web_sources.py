from types import SimpleNamespace

from app.agent import MasterAgent
from app.llm.types import ChatResponse, WebSource
from app.llm.web_sources import (
    extract_anthropic_web_sources,
    extract_openai_web_sources,
    extract_text_web_sources,
    merge_web_sources,
)
from app.projects.context import ProjectContext
from app.tools.registry import ToolRegistry


def test_extract_openai_url_citations_and_reject_invalid_urls():
    message = SimpleNamespace(
        content="根据官方文档，当前版本支持流式返回。",
        annotations=[
            SimpleNamespace(
                type="url_citation",
                url_citation=SimpleNamespace(
                    url="https://example.com/docs",
                    title="官方文档",
                    start_index=0,
                    end_index=6,
                ),
            ),
            {"type": "url_citation", "url_citation": {"url": "file:///secret.txt", "title": "无效"}},
        ],
    )

    sources = extract_openai_web_sources(message)

    assert [source.url for source in sources] == ["https://example.com/docs"]
    assert sources[0].title == "官方文档"
    assert sources[0].snippet == "根据官方文档"
    assert sources[0].provider == "openai"


def test_extract_openai_compatible_plain_citation_urls():
    message = SimpleNamespace(
        content="结果",
        annotations=None,
        model_extra={"citations": ["https://example.com/a", "https://example.com/a"]},
    )

    sources = extract_openai_web_sources(message)

    assert len(sources) == 1
    assert sources[0].url == "https://example.com/a"


def test_extract_openai_sources_from_response_root_and_compatible_fields():
    response = SimpleNamespace(
        citations=[{"link": "https://example.com/root", "name": "根节点来源"}],
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="结果",
                    model_extra={
                        "references": [
                            {
                                "source_url": "https://example.com/reference",
                                "description": "兼容中转站引用",
                            }
                        ]
                    },
                )
            )
        ],
    )

    sources = extract_openai_web_sources(response)

    assert [source.url for source in sources] == [
        "https://example.com/root",
        "https://example.com/reference",
    ]
    assert sources[0].title == "根节点来源"
    assert sources[1].snippet == "兼容中转站引用"


def test_extract_explicit_urls_from_native_search_text():
    sources = extract_text_web_sources(
        "来源：[官方文档](https://example.com/docs)\n备选：https://example.org/report。"
    )

    assert [source.url for source in sources] == [
        "https://example.com/docs",
        "https://example.org/report",
    ]
    assert sources[0].title == "官方文档"
    assert sources[0].provider == "provider-text"


def test_extract_anthropic_search_results_and_text_citations():
    blocks = [
        {
            "type": "web_search_tool_result",
            "content": [
                {
                    "type": "web_search_result",
                    "url": "https://example.com/report",
                    "title": "研究报告",
                }
            ],
        },
        {
            "type": "text",
            "text": "报告显示数据已经更新。",
            "citations": [
                {
                    "type": "web_search_result_location",
                    "url": "https://example.com/report",
                    "title": "研究报告",
                    "cited_text": "数据更新于本月。",
                }
            ],
        },
    ]

    sources = extract_anthropic_web_sources(blocks)

    assert len(sources) == 1
    assert sources[0].title == "研究报告"
    assert sources[0].snippet == "数据更新于本月。"
    assert sources[0].provider == "anthropic"


def test_merge_web_sources_fills_missing_fields_without_duplicates():
    merged = merge_web_sources(
        [WebSource(url="https://example.com", title="示例")],
        [WebSource(url="https://example.com", snippet="引用片段", provider="openai")],
    )

    assert len(merged) == 1
    assert merged[0].model_dump() == {
        "url": "https://example.com",
        "title": "示例",
        "snippet": "引用片段",
        "provider": "openai",
    }


def test_agent_accumulates_web_sources_across_model_rounds(tmp_path):
    llm = SimpleNamespace(settings=SimpleNamespace(llm_native_web_search=True))
    agent = MasterAgent(llm, ToolRegistry(), ProjectContext(tmp_path))
    agent._reset_usage_summary()

    agent._record_model_request(
        [{"role": "user", "content": "查资料"}],
        ChatResponse(
            content=[],
            text="第一轮",
            web_sources=[WebSource(url="https://example.com", title="示例")],
        ),
    )
    agent._record_model_request(
        [{"role": "user", "content": "继续"}],
        ChatResponse(
            content=[],
            text="第二轮",
            web_sources=[WebSource(url="https://example.com", snippet="补充引用")],
        ),
    )

    assert agent.web_source_metadata() == [
        {
            "url": "https://example.com",
            "title": "示例",
            "snippet": "补充引用",
            "provider": "",
        }
    ]
    assert agent.last_prompt_audit["web_search"] == {"enabled": True, "source_count": 1}
