import pytest
from pydantic import ValidationError

from app.agent import MasterAgent
from app.llm.types import ChatRequest, ChatResponse
from app.projects.context import ProjectContext
from app.tools.factory import create_tool_registry
from app.tools.present_choices import PresentChoicesTool


def choice_params():
    return {
        "groups": [
            {
                "id": "direction",
                "title": "选择剧情方向",
                "mode": "single",
                "options": [
                    {"id": "ruins", "label": "进入遗迹"},
                    {"id": "town", "label": "返回聚落"},
                ],
            },
            {
                "id": "elements",
                "title": "选择加入的元素",
                "mode": "multiple",
                "required": False,
                "min_selections": 0,
                "max_selections": 2,
                "options": [
                    {"id": "rain", "label": "黑雨"},
                    {"id": "ai", "label": "旧时代 AI"},
                    {"id": "train", "label": "装甲列车"},
                ],
            },
        ]
    }


@pytest.mark.asyncio
async def test_present_choices_normalizes_single_and_multiple_groups(tmp_path):
    result = await PresentChoicesTool().execute(choice_params(), ProjectContext(tmp_path))

    assert result.status == "ok"
    assert result.metadata["choice_request_id"]
    groups = result.metadata["choice_groups"]
    assert groups[0]["min_selections"] == 1
    assert groups[0]["max_selections"] == 1
    assert groups[0]["options"][0]["value"] == "进入遗迹"
    assert groups[1]["min_selections"] == 0
    assert groups[1]["max_selections"] == 2


@pytest.mark.asyncio
async def test_present_choices_rejects_duplicate_option_ids(tmp_path):
    params = choice_params()
    params["groups"][0]["options"][1]["id"] = "ruins"

    with pytest.raises(ValidationError):
        await PresentChoicesTool().execute(params, ProjectContext(tmp_path))


class ChoiceLLM:
    def __init__(self):
        self.calls = 0
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls += 1
        self.requests.append(request)
        return ChatResponse(
            content=[],
            text="这一步需要你决定方向。",
            tool_calls=[{"id": "choice-1", "name": "present_choices", "input": choice_params()}],
        )


@pytest.mark.asyncio
async def test_agent_stops_after_presenting_choices_and_hides_raw_tool_result(tmp_path):
    llm = ChoiceLLM()
    events = []

    async def publish(event):
        events.append(event)

    agent = MasterAgent(
        llm_client=llm,
        tool_registry=create_tool_registry(),
        project=ProjectContext(tmp_path),
        publisher=publish,
    )

    result = await agent.run("给我几个方向", enabled_tools=["search_project"], override_enabled_tools=True)

    assert result == "这一步需要你决定方向。"
    assert llm.calls == 1
    assert any(schema["name"] == "present_choices" for schema in llm.requests[0].tools)
    assert agent.last_choice_request
    assert len(agent.last_choice_request["groups"]) == 2
    assert agent.last_prompt_audit["usage"]["termination_reason"] == "awaiting_choice"
    assert not any(event.get("type") == "tool_result" for event in events)


def test_choice_response_metadata_is_injected_into_current_model_request(tmp_path):
    agent = MasterAgent(
        llm_client=ChoiceLLM(),
        tool_registry=create_tool_registry(),
        project=ProjectContext(tmp_path),
    )
    messages = agent._build_initial_messages(
        "继续",
        [],
        "",
        [],
        "",
        [],
        {
            "choice_response": {
                "request_id": "request-1",
                "selections": [{"group_id": "direction", "values": ["进入遗迹"]}],
            }
        },
    )

    assert "结构化选择结果" in messages[-1]["content"]
    assert '"request_id":"request-1"' in messages[-1]["content"]
