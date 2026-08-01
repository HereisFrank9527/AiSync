import json

import httpx

from app.core.presets import LLMParams
from app.llm.factory import settings_from_preset
from app.search.tavily import parse_tavily_response, search_tavily


def test_parse_tavily_response_prefers_raw_content_and_records_credits():
    result = parse_tavily_response(
        {
            "results": [
                {
                    "title": "详细游戏数据",
                    "url": "https://example.com/game-data",
                    "content": "摘要",
                    "raw_content": "完整正文内容",
                },
                {"title": "无效", "url": "file:///secret", "content": "忽略"},
            ],
            "usage": {"credits": 2},
            "request_id": "request-1",
            "response_time": "1.25",
        },
        limit=5,
    )

    assert len(result.sources) == 1
    assert result.sources[0].snippet == "完整正文内容"
    assert result.sources[0].provider == "tavily"
    assert result.credits == 2
    assert result.request_id == "request-1"
    assert result.response_time == 1.25


async def test_search_tavily_uses_bearer_auth_and_advanced_chunks():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tvly-test"
        body = json.loads(request.content)
        assert body["query"] == "绝地潜兵武器伤害"
        assert body["max_results"] == 20
        assert body["search_depth"] == "advanced"
        assert body["chunks_per_source"] == 3
        assert body["include_raw_content"] == "text"
        assert body["include_usage"] is True
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Wiki",
                        "url": "https://example.com/wiki",
                        "content": "相关片段",
                        "raw_content": "详细正文",
                    }
                ],
                "usage": {"credits": 2},
                "request_id": "request-2",
            },
        )

    result = await search_tavily(
        "绝地潜兵武器伤害",
        "tvly-test",
        99,
        search_depth="advanced",
        include_raw_content=True,
        transport=httpx.MockTransport(handler),
    )

    assert result.sources[0].url == "https://example.com/wiki"
    assert result.sources[0].snippet == "详细正文"
    assert result.credits == 2


def test_tavily_settings_are_carried_from_llm_preset():
    settings = settings_from_preset(
        LLMParams(
            tavily_api_key="tvly-test",
            web_search_provider="tavily",
            tavily_search_depth="advanced",
            web_search_max_results=4,
            tavily_include_raw_content=True,
        )
    )

    assert settings.tavily_api_key == "tvly-test"
    assert settings.web_search_provider == "tavily"
    assert settings.tavily_search_depth == "advanced"
    assert settings.web_search_max_results == 4
    assert settings.tavily_include_raw_content is True
