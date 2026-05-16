from types import SimpleNamespace

from app.llm.openai_client import OpenAICompatibleLLMClient


def make_client(
    *,
    model_name: str = "deepseek-v4",
    api_base: str = "https://api.deepseek.com",
    enable_thinking: bool = True,
) -> OpenAICompatibleLLMClient:
    client = object.__new__(OpenAICompatibleLLMClient)
    client.settings = SimpleNamespace(
        llm_api_base=api_base,
        llm_model_name=model_name,
        llm_enable_thinking=enable_thinking,
        llm_effort="high",
    )
    return client


def test_prepare_messages_preserves_deepseek_reasoning_content() -> None:
    client = make_client()

    messages = client._prepare_messages([
        {
            "role": "assistant",
            "content": [
                {"type": "reasoning", "reasoning_content": "内部推理摘要"},
                {"type": "text", "text": "需要调用工具。"},
                {"type": "tool_use", "id": "call_1", "name": "search_project", "input": {"query": "方舟"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "检索结果"},
            ],
        },
    ])

    assert messages[0]["role"] == "assistant"
    assert messages[0]["reasoning_content"] == "内部推理摘要"
    assert messages[0]["tool_calls"][0]["id"] == "call_1"
    assert messages[1] == {"role": "tool", "tool_call_id": "call_1", "content": "检索结果"}


def test_prepare_messages_drops_reasoning_content_when_thinking_disabled() -> None:
    client = make_client(enable_thinking=False)

    messages = client._prepare_messages([
        {
            "role": "assistant",
            "content": [
                {"type": "reasoning", "reasoning_content": "内部推理摘要"},
                {"type": "text", "text": "普通回复"},
            ],
        },
    ])

    assert "reasoning_content" not in messages[0]


def test_prepare_messages_drops_reasoning_content_for_legacy_deepseek_reasoner() -> None:
    client = make_client(model_name="deepseek-reasoner")

    messages = client._prepare_messages([
        {
            "role": "assistant",
            "content": [
                {"type": "reasoning", "reasoning_content": "旧 reasoner 不应回传"},
                {"type": "text", "text": "普通回复"},
            ],
        },
    ])

    assert "reasoning_content" not in messages[0]


def test_deepseek_chat_params_controls_thinking_mode() -> None:
    client = make_client(enable_thinking=False)

    params = client._chat_params([{"role": "user", "content": "hi"}], None, 1024)

    assert params["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in params


def test_extract_reasoning_content_from_model_extra() -> None:
    client = make_client()
    value = SimpleNamespace(model_extra={"reasoning_content": "模型额外字段"})

    assert client._extract_reasoning_content(value) == "模型额外字段"


def test_deepseek_thinking_tools_disable_streaming() -> None:
    client = make_client(enable_thinking=True)
    request = SimpleNamespace(tools=[{"name": "search_project"}])

    assert client._should_disable_streaming_for_reasoning_tools(request)
