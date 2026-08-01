from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent import MasterAgent
from app.llm.types import ChatResponse, WebSource
from app.projects.context import ProjectContext
from app.search.tavily import TavilySearchResult
from app.tools.base import ToolResult
from app.tools.registry import ToolRegistry
from app.tools.web_search import WebSearchTool


class SearchLLM:
    def __init__(self, responses: list[ChatResponse], enabled: bool = True) -> None:
        self.responses = list(responses)
        self.requests = []
        self.settings = SimpleNamespace(
            llm_native_web_search=enabled,
            llm_request_timeout=30,
            llm_provider="custom",
            llm_model_name="search-model",
            web_search_provider="auto",
            tavily_api_key=None,
            tavily_api_key_env="TAVILY_API_KEY",
            tavily_search_depth="basic",
            web_search_max_results=5,
            tavily_include_raw_content=False,
        )

    async def chat(self, request, on_text_delta=None):
        self.requests.append(request)
        response = self.responses.pop(0)
        if request.stream and on_text_delta and response.text:
            await on_text_delta(response.text)
        return response


@pytest.fixture(autouse=True)
def disable_public_search(monkeypatch):
    search = AsyncMock(return_value=[])
    monkeypatch.setattr("app.tools.web_search.search_public_web", search)
    monkeypatch.setattr("app.tools.web_search.search_tavily", AsyncMock())
    return search


async def test_web_search_tool_requires_structured_sources(tmp_path):
    llm = SearchLLM([ChatResponse(content=[], text="可能搜索过，但没有引用。")])

    result = await WebSearchTool().invoke(
        {"query": "今天的 OpenAI 官方更新"},
        ProjectContext(tmp_path),
        llm,
    )

    assert result is not None
    assert result.status == "error"
    assert result.metadata["search_status"] == "no_sources"
    assert result.ui_hint == {"type": "list:web_sources", "data": []}
    assert llm.requests[0].native_web_search is True
    assert llm.requests[0].tools == []


async def test_web_search_tool_accepts_explicit_provider_text_urls(tmp_path):
    llm = SearchLLM(
        [
            ChatResponse(
                content=[],
                text="检索摘要。\n来源：https://example.com/latest",
                usage={"input_tokens": 9, "output_tokens": 5, "total_tokens": 14},
            )
        ]
    )

    result = await WebSearchTool().invoke(
        {"query": "查询最新资料"},
        ProjectContext(tmp_path),
        llm,
    )

    assert result is not None
    assert result.status == "ok"
    assert result.metadata["source_count"] == 1
    assert result.metadata["web_sources"][0]["url"] == "https://example.com/latest"
    assert result.metadata["web_sources"][0]["provider"] == "openai-compatible-text"


async def test_web_search_tool_prefers_public_search_without_spending_llm_tokens(
    tmp_path,
    disable_public_search,
):
    disable_public_search.return_value = [
        WebSource(
            url="https://example.com/latest",
            title="最新资料",
            snippet="公开搜索摘要",
            provider="bing-rss",
        )
    ]
    llm = SearchLLM([])

    result = await WebSearchTool().invoke(
        {"query": "查询最新资料"},
        ProjectContext(tmp_path),
        llm,
    )

    assert result is not None
    assert result.status == "ok"
    assert result.metadata["search_mode"] == "public_search"
    assert result.metadata["provider"] == "bing-rss"
    assert result.metadata["source_count"] == 1
    assert llm.requests == []


async def test_web_search_tool_prefers_tavily_and_records_credit_metadata(
    tmp_path,
    monkeypatch,
    disable_public_search,
):
    tavily = AsyncMock(
        return_value=TavilySearchResult(
            sources=[
                WebSource(
                    url="https://example.com/detail",
                    title="详细资料",
                    snippet="正文片段",
                    provider="tavily",
                )
            ],
            credits=2,
            request_id="request-3",
            response_time=1.5,
        )
    )
    monkeypatch.setattr("app.tools.web_search.search_tavily", tavily)
    llm = SearchLLM([])
    llm.settings.tavily_api_key = "tvly-test"
    llm.settings.tavily_search_depth = "advanced"

    result = await WebSearchTool().invoke(
        {"query": "查询详细游戏数据"},
        ProjectContext(tmp_path),
        llm,
    )

    assert result is not None
    assert result.status == "ok"
    assert result.metadata["search_mode"] == "tavily"
    assert result.metadata["search_usage"] == {
        "provider": "tavily",
        "credits": 2,
        "request_id": "request-3",
        "response_time": 1.5,
        "search_depth": "advanced",
    }
    assert disable_public_search.await_count == 0
    assert llm.requests == []


def test_agent_records_search_service_credits(tmp_path):
    agent = MasterAgent(SearchLLM([]), ToolRegistry(), ProjectContext(tmp_path))
    agent._reset_usage_summary()

    agent._record_tool_search_usage(
        "web_search",
        ToolResult(
            content="ok",
            metadata={
                "search_usage": {
                    "provider": "tavily",
                    "credits": 2,
                    "request_id": "request-4",
                    "search_depth": "advanced",
                }
            },
        ),
    )

    assert agent.last_prompt_audit["usage"]["search_credits"] == 2
    assert agent.last_prompt_audit["usage"]["search_calls"] == [
        {
            "provider": "tavily",
            "credits": 2,
            "request_id": "request-4",
            "search_depth": "advanced",
            "tool": "web_search",
        }
    ]


async def test_web_search_tool_returns_bounded_sources_and_usage(tmp_path):
    sources = [
        WebSource(url=f"https://example.com/{index}", title=f"来源 {index}", provider="openai")
        for index in range(5)
    ]
    llm = SearchLLM(
        [
            ChatResponse(
                content=[],
                text="这是联网检索摘要。",
                usage={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
                web_sources=sources,
            )
        ]
    )

    result = await WebSearchTool().invoke(
        {"query": "查询最新资料", "max_sources": 2},
        ProjectContext(tmp_path),
        llm,
    )

    assert result is not None
    assert result.status == "ok"
    assert result.metadata["source_count"] == 2
    assert result.metadata["llm_usage"]["total_tokens"] == 20
    assert len(result.ui_hint["data"]) == 2
    assert "可验证来源" in result.content


async def test_agent_exposes_explicit_search_and_keeps_primary_requests_off_hosted_search(tmp_path):
    llm = SearchLLM(
        [
            ChatResponse(
                content=[],
                text="",
                tool_calls=[{"id": "search-1", "name": "web_search", "input": {"query": "最新资料"}}],
                usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            ),
            ChatResponse(
                content=[],
                text="联网摘要",
                usage={"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
                web_sources=[WebSource(url="https://example.com/latest", title="最新资料")],
            ),
            ChatResponse(
                content=[],
                text="已根据最新资料回答。",
                usage={"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
            ),
        ]
    )
    registry = ToolRegistry()
    registry.register(WebSearchTool())
    events = []

    async def publish(event):
        events.append(event)

    agent = MasterAgent(
        llm,
        registry,
        ProjectContext(tmp_path),
        publisher=publish,
    )

    result = await agent.run("帮我联网查最新资料", max_iterations=3)

    assert result == "已根据最新资料回答。"
    assert [request.native_web_search for request in llm.requests] == [False, True, False]
    assert [tool["name"] for tool in llm.requests[0].tools] == ["web_search"]
    assert llm.requests[1].tools == []
    assert agent.web_source_metadata()[0]["url"] == "https://example.com/latest"
    assert agent.last_prompt_audit["usage"]["total_tokens"] == 31
    assert agent.last_prompt_audit["usage"]["tool_llm_calls"] == [
        {
            "tool": "web_search",
            "usage": {"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
        }
    ]
    tool_results = [event for event in events if event["type"] == "tool_result"]
    assert tool_results[0]["metadata"]["source_count"] == 1


def test_agent_hides_web_search_schema_when_setting_is_disabled(tmp_path):
    registry = ToolRegistry()
    registry.register(WebSearchTool())
    agent = MasterAgent(
        SearchLLM([], enabled=False),
        registry,
        ProjectContext(tmp_path),
    )

    assert agent._request_tool_schemas(None) == []
