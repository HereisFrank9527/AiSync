from types import SimpleNamespace

import pytest

from app.llm.types import ChatRequest
from app.llm.openai_client import OpenAICompatibleLLMClient


def make_client(
    *,
    model_name: str = "deepseek-v4",
    api_base: str = "https://api.deepseek.com",
    enable_thinking: bool = True,
    native_web_search: bool = False,
    effort: str = "high",
) -> OpenAICompatibleLLMClient:
    client = object.__new__(OpenAICompatibleLLMClient)
    client.settings = SimpleNamespace(
        llm_api_base=api_base,
        llm_model_name=model_name,
        llm_max_tokens=16000,
        llm_enable_thinking=enable_thinking,
        llm_effort=effort,
        llm_native_web_search=native_web_search,
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


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_deepseek_chat_params_preserves_supported_reasoning_effort(effort: str) -> None:
    client = make_client(effort=effort)

    params = client._chat_params([{"role": "user", "content": "hi"}], None, 1024)

    assert params["reasoning_effort"] == effort


@pytest.mark.parametrize(
    ("configured_effort", "expected_effort"),
    [
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "xhigh"),
        ("max", "xhigh"),
    ],
)
def test_openai_reasoning_model_receives_supported_effort(
    configured_effort: str,
    expected_effort: str,
) -> None:
    client = make_client(
        model_name="gpt-5.6",
        api_base="https://api.openai.com/v1",
        effort=configured_effort,
    )
    client.settings.llm_provider = "openai"

    params = client._chat_params([{"role": "user", "content": "hi"}], None, 1024)

    assert params["reasoning_effort"] == expected_effort
    assert "extra_body" not in params


def test_openai_standard_model_does_not_receive_reasoning_parameter() -> None:
    client = make_client(
        model_name="gpt-4o",
        api_base="https://api.openai.com/v1",
        effort="max",
    )
    client.settings.llm_provider = "openai"

    params = client._chat_params([{"role": "user", "content": "hi"}], None, 1024)

    assert "reasoning_effort" not in params


def test_openai_native_web_search_is_opt_in() -> None:
    disabled = make_client(native_web_search=False)._chat_params(
        [{"role": "user", "content": "hi"}], None, 1024
    )
    enabled = make_client(native_web_search=True)._chat_params(
        [{"role": "user", "content": "hi"}], None, 1024
    )

    assert "web_search_options" not in disabled
    assert enabled["web_search_options"] == {}

    request_override = make_client(native_web_search=True)._chat_params(
        [{"role": "user", "content": "hi"}], None, 1024, native_web_search=False
    )
    assert "web_search_options" not in request_override


def test_extract_reasoning_content_from_model_extra() -> None:
    client = make_client()
    value = SimpleNamespace(model_extra={"reasoning_content": "模型额外字段"})

    assert client._extract_reasoning_content(value) == "模型额外字段"


def test_deepseek_thinking_tool_stream_keeps_thinking_enabled() -> None:
    client = make_client(enable_thinking=True)

    params = client._chat_params(
        [{"role": "user", "content": "hi"}],
        [{"type": "function", "function": {"name": "search_project", "parameters": {"type": "object"}}}],
        1024,
    )

    assert params["extra_body"] == {"thinking": {"type": "enabled"}}
    assert params["reasoning_effort"] == "high"


def test_deepseek_complete_tool_history_keeps_thinking_enabled() -> None:
    client = make_client(enable_thinking=True)
    messages = client._prepare_messages([
        {
            "role": "assistant",
            "content": [
                {"type": "reasoning", "reasoning_content": "先检索项目"},
                {"type": "tool_use", "id": "call_1", "name": "search_project", "input": {"query": "方舟"}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "检索结果"}],
        },
    ])

    assert not client._should_disable_thinking_for_incomplete_tool_history(messages)


def test_deepseek_incomplete_tool_history_disables_thinking_for_compatible_finalize() -> None:
    client = make_client(enable_thinking=True)
    messages = client._prepare_messages([
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "先检索项目"},
                {"type": "tool_use", "id": "call_1", "name": "search_project", "input": {"query": "方舟"}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "检索结果"}],
        },
    ])

    assert client._should_disable_thinking_for_incomplete_tool_history(messages)

    params = client._chat_params(messages, None, 1024, disable_thinking=True)
    assert params["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in params


@pytest.mark.asyncio
async def test_deepseek_incomplete_tool_history_is_sanitized_in_chat_request() -> None:
    client = make_client(enable_thinking=True)
    captured: dict = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return FakeStream([stream_chunk("收尾完成", finish_reason="stop")])

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    await client.chat(
        ChatRequest(
            messages=[
                {
                    "role": "assistant",
                    "content": [
                        {"type": "reasoning", "reasoning_content": "此前完整推理"},
                        {"type": "tool_use", "id": "call_1", "name": "search_project", "input": {}},
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "结果一"}],
                },
                {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "call_2", "name": "search_project", "input": {}}],
                },
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "call_2", "content": "结果二"}],
                },
            ],
            stream=True,
        ),
        on_text_delta=lambda _delta: _async_noop(),
    )

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert all("reasoning_content" not in message for message in captured["messages"])


class FakeStream:
    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self.chunks = chunks

    def __aiter__(self):
        self._iterator = iter(self.chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def stream_chunk(
    content: str | None = None,
    finish_reason: str | None = None,
    reasoning_content: str | None = None,
    tool_calls: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    delta = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        model_extra={"reasoning_content": reasoning_content} if reasoning_content else {},
    )
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


def streamed_tool_call() -> SimpleNamespace:
    return SimpleNamespace(
        index=0,
        id="call_1",
        function=SimpleNamespace(name="search_project", arguments='{"query":"方舟"}'),
    )


@pytest.mark.asyncio
async def test_streaming_deepseek_tool_call_preserves_reasoning_for_next_turn() -> None:
    client = make_client()
    captured: dict = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return FakeStream([
            stream_chunk(reasoning_content="先检索项目"),
            stream_chunk(tool_calls=[streamed_tool_call()], finish_reason="tool_calls"),
        ])

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    response = await client.chat(
        ChatRequest(
            messages=[{"role": "user", "content": "检查方舟设定"}],
            tools=[{"name": "search_project", "input_schema": {"type": "object"}}],
            stream=True,
        ),
        on_text_delta=lambda _delta: _async_noop(),
    )

    assert captured["stream"] is True
    assert captured["extra_body"] == {"thinking": {"type": "enabled"}}
    assert response.reasoning_content == "先检索项目"
    assert response.tool_calls == [{"id": "call_1", "name": "search_project", "input": {"query": "方舟"}}]

    next_messages = client._prepare_messages([
        {
            "role": "assistant",
            "content": [
                {"type": "reasoning", "reasoning_content": response.reasoning_content},
                {
                    "type": "tool_use",
                    "id": response.tool_calls[0]["id"],
                    "name": response.tool_calls[0]["name"],
                    "input": response.tool_calls[0]["input"],
                },
            ],
        }
    ])
    assert next_messages[0]["reasoning_content"] == "先检索项目"
    assert not client._should_disable_thinking_for_incomplete_tool_history(next_messages)


@pytest.mark.asyncio
async def test_stream_chat_preserves_finish_reason() -> None:
    client = make_client()

    async def create(**_kwargs):
        return FakeStream([stream_chunk("半句"), stream_chunk(finish_reason="length")])

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    response = await client.chat(
        ChatRequest(messages=[{"role": "user", "content": "继续"}], stream=True),
        on_text_delta=lambda _delta: _async_noop(),
    )

    assert response.text == "半句"
    assert response.stop_reason == "length"


@pytest.mark.asyncio
async def test_stream_chat_marks_missing_finish_frame_as_incomplete() -> None:
    client = make_client()

    async def create(**_kwargs):
        return FakeStream([stream_chunk("半句")])

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    response = await client.chat(
        ChatRequest(messages=[{"role": "user", "content": "继续"}], stream=True),
        on_text_delta=lambda _delta: _async_noop(),
    )

    assert response.stop_reason == "stream_incomplete"


async def _async_noop() -> None:
    return None
