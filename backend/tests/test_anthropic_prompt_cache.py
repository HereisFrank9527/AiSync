from types import SimpleNamespace

from app.llm.anthropic_client import AnthropicLLMClient
from app.llm.types import ChatRequest


def make_client(prompt_cache: bool = True, native_web_search: bool = False) -> AnthropicLLMClient:
    client = object.__new__(AnthropicLLMClient)
    client.settings = SimpleNamespace(
        llm_prompt_cache=prompt_cache,
        llm_model_name="claude-sonnet-4-5",
        llm_max_tokens=1024,
        llm_native_web_search=native_web_search,
    )
    return client


def test_anthropic_tool_cache_marks_copy_without_mutating_original():
    client = make_client(prompt_cache=True)
    tools = [
        {"name": "a", "description": "A", "input_schema": {"type": "object"}},
        {"name": "b", "description": "B", "input_schema": {"type": "object"}},
    ]

    cached = client._tools_with_cache(tools)

    assert "cache_control" not in tools[-1]
    assert "cache_control" not in cached[0]
    assert cached[-1]["cache_control"] == {"type": "ephemeral"}
    assert cached[-1]["name"] == "b"


def test_anthropic_tool_cache_respects_disabled_setting():
    client = make_client(prompt_cache=False)
    tools = [{"name": "a", "description": "A", "input_schema": {"type": "object"}}]

    assert client._tools_with_cache(tools) is tools


def test_anthropic_native_web_search_is_opt_in():
    client = make_client(native_web_search=True)
    request = ChatRequest(messages=[{"role": "user", "content": "查一下最新资料"}], native_web_search=True)

    params = client._request_params(request)

    assert params["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]


def test_anthropic_native_web_search_does_not_add_tool_when_disabled():
    client = make_client(native_web_search=False)
    request = ChatRequest(messages=[{"role": "user", "content": "普通聊天"}])

    assert request.native_web_search is False
    assert "tools" not in client._request_params(request)
