import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.workflows import router as workflows_router
from app.api.workflows import settings as workflow_settings
from app.llm.types import ChatRequest, ChatResponse
from app.projects.context import ProjectContext
from app.projects.facts import chapter_fact_document, chapter_fact_path
from app.workflows.chapter_batch import ChapterBatchCreate, build_chapter_batch_workflow
from app.workflows.executor import WorkflowExecutor
from app.workflows.runs import WorkflowRunStore


class ChapterBatchLLM:
    def __init__(self) -> None:
        self.calls: list[ChatRequest] = []

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls.append(request)
        prompt = str(request.messages[-1]["content"])
        matched = re.search(r"撰写长篇小说第 (\d+) 章", prompt)
        chapter_number = int(matched.group(1)) if matched else 0
        payload = {
            "content": f"# 第{chapter_number}章\n\n第{chapter_number}章正文标记。",
            "foreshadow_actions": [],
            "fact_records": [
                {
                    "category": "state",
                    "subject": "主角",
                    "predicate": "进度",
                    "value": f"完成第{chapter_number}章事件",
                    "evidence": f"第{chapter_number}章正文标记。",
                    "certainty": "confirmed",
                }
            ],
        }
        return ChatResponse(content=[], text=json.dumps(payload, ensure_ascii=False))


def test_build_chapter_batch_workflow_expands_one_checkpoint_per_chapter():
    data = ChapterBatchCreate(
        start_chapter=5,
        end_chapter=7,
        volume="vol-02",
        requirements="推进城防线。",
        preset_id="writer",
        target_characters=4200,
    )

    workflow = build_chapter_batch_workflow(data)

    assert workflow.workflow_type == "chapter_batch"
    assert len(workflow.steps) == 3
    assert [step.kind for step in workflow.steps] == ["chapter", "chapter", "chapter"]
    assert [step.input["target_path"] for step in workflow.steps] == [
        "chapters/vol-02/ch-005.md",
        "chapters/vol-02/ch-006.md",
        "chapters/vol-02/ch-007.md",
    ]
    assert all(step.preset_id == "writer" for step in workflow.steps)
    assert workflow.metadata["chapter_count"] == 3


def test_chapter_batch_rejects_too_many_chapters_and_unsafe_volume():
    with pytest.raises(ValidationError, match="单次最多连续写 20 章"):
        ChapterBatchCreate(start_chapter=1, end_chapter=21)
    with pytest.raises(ValidationError, match="卷目录只能包含"):
        ChapterBatchCreate(start_chapter=1, end_chapter=2, volume="../outside")


def test_chapter_batch_api_creates_dynamic_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(
        type(workflow_settings),
        "project_path",
        lambda self, project_path=None, project_id=None: tmp_path,
    )
    app = FastAPI()
    app.include_router(workflows_router)
    client = TestClient(app)

    response = client.post(
        "/workflows/chapter-batches?project_path=isolated",
        json={
            "start_chapter": 8,
            "end_chapter": 9,
            "volume": "第二卷",
            "requirements": "完成转场。",
            "target_characters": 3500,
            "overwrite_existing": False,
        },
    )

    assert response.status_code == 201
    record = response.json()
    assert record["workflow_type"] == "chapter_batch"
    assert [step["input"]["target_path"] for step in record["steps"]] == [
        "chapters/第二卷/ch-008.md",
        "chapters/第二卷/ch-009.md",
    ]


async def test_chapter_batch_executes_one_chapter_at_a_time_with_bounded_context(tmp_path, monkeypatch):
    context = ProjectContext(tmp_path)
    await context.write_text("chapters/vol-01/ch-001.md", "# 第一章\n\n第一章唯一旧内容。\n")
    await context.write_json(
        chapter_fact_path("chapters/vol-01/ch-001.md"),
        chapter_fact_document(
            "chapters/vol-01/ch-001.md",
            [
                {
                    "id": "fact-old",
                    "category": "state",
                    "subject": "主角",
                    "predicate": "状态",
                    "value": "负伤",
                    "certainty": "confirmed",
                    "source_path": "chapters/vol-01/ch-001.md",
                    "evidence": "伤口仍在渗血。",
                }
            ],
        ),
    )
    store = WorkflowRunStore(tmp_path)
    run = store.create(
        build_chapter_batch_workflow(
            ChapterBatchCreate(start_chapter=2, end_chapter=3, requirements="继续向北推进。")
        )
    )
    llm = ChapterBatchLLM()
    monkeypatch.setattr("app.workflows.executor.create_llm_client", lambda settings: llm)
    executor = WorkflowExecutor(context, store)

    async def empty_query(query: str, top_k: int = 6):
        return []

    monkeypatch.setattr(executor.vector_store, "query", empty_query)

    after_second = await executor.run_next(run.run_id)

    assert after_second.status == "running"
    assert after_second.steps[0].status == "completed"
    assert after_second.steps[1].status == "pending"
    assert after_second.current_step_id == after_second.steps[1].step_id
    assert "第一章唯一旧内容" in str(llm.calls[0].messages[-1]["content"])
    assert '"value": "负伤"' in str(llm.calls[0].messages[-1]["content"])
    assert await context.exists("chapters/vol-01/ch-002.md")
    assert "content" not in after_second.steps[0].output
    assert after_second.steps[0].output["context"]["previous_tail_characters"] > 0

    finished = await executor.run_next(run.run_id)

    assert finished.status == "completed"
    assert all(step.status == "completed" for step in finished.steps)
    second_prompt = str(llm.calls[1].messages[-1]["content"])
    assert "第2章正文标记" in second_prompt
    assert "第一章唯一旧内容" not in second_prompt
    assert await context.exists("chapters/vol-01/ch-003.md")
    assert await context.exists("plot/facts/vol-01/ch-003.json")


async def test_chapter_batch_does_not_overwrite_existing_chapter_by_default(tmp_path, monkeypatch):
    context = ProjectContext(tmp_path)
    await context.write_text("chapters/vol-01/ch-005.md", "# 已有第五章\n")
    store = WorkflowRunStore(tmp_path)
    run = store.create(build_chapter_batch_workflow(ChapterBatchCreate(start_chapter=5, end_chapter=5)))
    llm = ChapterBatchLLM()
    monkeypatch.setattr("app.workflows.executor.create_llm_client", lambda settings: llm)

    failed = await WorkflowExecutor(context, store).run_next(run.run_id)

    assert failed.status == "failed"
    assert failed.steps[0].status == "failed"
    assert "章节已存在" in str(failed.steps[0].error)
    assert llm.calls == []
    assert await context.read_text("chapters/vol-01/ch-005.md") == "# 已有第五章\n"
