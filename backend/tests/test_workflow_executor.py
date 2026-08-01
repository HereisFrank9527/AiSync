from app.llm.types import ChatRequest, ChatResponse
from app.core.prompt_packs import PromptPackCreate, PromptPackStore
from app.projects.context import ProjectContext
from app.workflows.executor import WorkflowExecutor
from app.workflows.runs import WorkflowRunCreate, WorkflowRunStore, WorkflowStepRecord


class DummyLLM:
    def __init__(self) -> None:
        self.calls: list[ChatRequest] = []

    async def chat(self, request: ChatRequest, on_text_delta=None) -> ChatResponse:
        self.calls.append(request)
        text = str(request.messages[-1]["content"])
        if "不要直接写正文" in text:
            return ChatResponse(content=[], text="## 章节计划\n\n1. 开场\n2. 冲突")
        return ChatResponse(content=[], text="# 第一章\n\n正文草稿。")


async def test_workflow_executor_plan_confirm_draft(tmp_path, monkeypatch):
    context = ProjectContext(tmp_path)
    store = WorkflowRunStore(tmp_path)
    run = store.create(
        WorkflowRunCreate(
            workflow_type="chapter_draft",
            title="第一章草稿",
            input_summary="写第一章",
            steps=[
                WorkflowStepRecord(name="检索章节上下文", kind="context"),
                WorkflowStepRecord(name="生成章节计划", kind="plan", input={"extra_prompt": "计划必须包含悬念。"}),
                WorkflowStepRecord(name="用户确认计划", kind="user_confirm"),
                WorkflowStepRecord(name="分段写作草稿", kind="draft", output_path="temp/drafts/", input={"extra_prompt": "正文使用冷峻文风。"}),
            ],
        )
    )
    llm = DummyLLM()
    monkeypatch.setattr("app.workflows.executor.create_llm_client", lambda settings: llm)

    executor = WorkflowExecutor(context, store)
    after_context = await executor.run_next(run.run_id)
    assert after_context.steps[0].status == "completed"
    assert after_context.current_step_id == after_context.steps[1].step_id

    after_plan = await executor.run_next(run.run_id)
    assert after_plan.steps[1].status == "completed"
    assert "章节计划" in after_plan.steps[1].output["content"]
    assert after_plan.current_step_id == after_plan.steps[2].step_id
    assert "计划必须包含悬念。" in str(llm.calls[-1].messages[-1]["content"])

    waiting = await executor.run_next(run.run_id)
    assert waiting.steps[2].status == "waiting_user"

    confirmed = await executor.confirm_current_step(run.run_id, "计划可用")
    assert confirmed.steps[2].status == "completed"
    assert confirmed.current_step_id == confirmed.steps[3].step_id

    drafted = await executor.run_next(run.run_id)
    assert drafted.steps[3].status == "completed"
    assert drafted.steps[3].output_path == f"temp/drafts/{run.run_id}.md"
    assert await context.read_text(f"temp/drafts/{run.run_id}.md") == "# 第一章\n\n正文草稿。\n"
    assert "正文使用冷峻文风。" in str(llm.calls[-1].messages[-1]["content"])


async def test_workflow_executor_write_file_from_draft_to_chapter(tmp_path):
    context = ProjectContext(tmp_path)
    store = WorkflowRunStore(tmp_path)
    await context.write_text("temp/drafts/draft.md", "# 第一章\n\n草稿正文。\n")
    run = store.create(
        WorkflowRunCreate(
            workflow_type="chapter_draft",
            title="写入正式章节",
            steps=[
                WorkflowStepRecord(
                    name="写入正式章节",
                    kind="write_file",
                    input={
                        "source_path": "temp/drafts/draft.md",
                        "target_path": "chapters/vol-01/ch-001.md",
                    },
                ),
            ],
        )
    )

    executor = WorkflowExecutor(context, store)
    finished = await executor.run_next(run.run_id)

    assert finished.status == "completed"
    assert finished.steps[0].status == "completed"
    assert finished.steps[0].output["target_path"] == "chapters/vol-01/ch-001.md"
    assert await context.read_text("chapters/vol-01/ch-001.md") == "# 第一章\n\n草稿正文。\n"


async def test_workflow_executor_write_file_rejects_unsafe_target(tmp_path):
    context = ProjectContext(tmp_path)
    store = WorkflowRunStore(tmp_path)
    await context.write_text("temp/drafts/draft.md", "草稿")
    run = store.create(
        WorkflowRunCreate(
            workflow_type="chapter_draft",
            title="非法写入",
            steps=[
                WorkflowStepRecord(
                    name="写入正式章节",
                    kind="write_file",
                    input={
                        "source_path": "temp/drafts/draft.md",
                        "target_path": "world/overview.md",
                    },
                ),
            ],
        )
    )

    executor = WorkflowExecutor(context, store)
    failed = await executor.run_next(run.run_id)

    assert failed.status == "failed"
    assert failed.steps[0].status == "failed"
    assert "chapters/**/*.md" in failed.steps[0].error


async def test_workflow_step_selected_prompt_packs_are_injected(tmp_path, monkeypatch):
    context = ProjectContext(tmp_path)
    store = WorkflowRunStore(tmp_path)
    prompt_store = PromptPackStore(tmp_path / "prompt_packs.json")
    selected = prompt_store.create(
        PromptPackCreate(
            name="半文半白",
            category="style",
            stages=["chapter_plan"],
            content="计划语言半文半白。",
        )
    )
    unselected = prompt_store.create(
        PromptPackCreate(
            name="未选提示词",
            category="style",
            stages=["chapter_plan"],
            content="这段不应进入 prompt。",
        )
    )
    run = store.create(
        WorkflowRunCreate(
            workflow_type="chapter_draft",
            title="第一章计划",
            input_summary="写计划",
            steps=[
                WorkflowStepRecord(
                    name="生成章节计划",
                    kind="plan",
                    prompt_pack_ids=[selected.id],
                ),
            ],
        )
    )
    llm = DummyLLM()
    monkeypatch.setattr("app.workflows.executor.create_llm_client", lambda settings: llm)
    monkeypatch.setattr("app.workflows.executor.prompt_pack_store", prompt_store)

    executor = WorkflowExecutor(context, store)
    finished = await executor.run_next(run.run_id)
    prompt = str(llm.calls[-1].messages[-1]["content"])

    assert "计划语言半文半白。" in prompt
    assert "这段不应进入 prompt。" not in prompt
    assert finished.steps[0].output["prompt_packs"]["mode"] == "step_selected"
    assert finished.steps[0].output["prompt_packs"]["ids"] == [selected.id]
    assert finished.steps[0].output["prompt_packs"]["prompt_chars"] > 0
    assert finished.steps[0].output["prompt_packs"]["extra_prompt_included"] is False
    assert unselected.id not in finished.steps[0].output["prompt_packs"]["ids"]


async def test_workflow_executor_applies_draft_foreshadow_actions_with_chapter(tmp_path):
    context = ProjectContext(tmp_path)
    store = WorkflowRunStore(tmp_path)
    await context.write_text("temp/drafts/draft.md", "# 第一章\n门禁亮了一下。\n")
    run = store.create(
        WorkflowRunCreate(
            workflow_type="chapter_draft",
            title="带伏笔的工作流写入",
            steps=[
                WorkflowStepRecord(
                    name="生成章节草稿",
                    kind="draft",
                    output={
                        "content": "# 第一章\n门禁亮了一下。\n",
                        "foreshadow_actions": [
                            {
                                "action": "plant",
                                "title": "门禁异常",
                                "summary": "断电后的门禁仍识别出未知权限。",
                                "evidence": "门禁屏幕闪过未知权限。",
                            }
                        ],
                        "fact_records": [
                            {
                                "category": "state",
                                "subject": "门禁",
                                "predicate": "能源状态",
                                "value": "断电后短暂亮起",
                                "evidence": "门禁亮了一下。",
                                "certainty": "confirmed",
                            }
                        ],
                    },
                    output_path="temp/drafts/draft.md",
                    status="completed",
                ),
                WorkflowStepRecord(
                    name="写入正式章节",
                    kind="write_file",
                    input={
                        "source_path": "temp/drafts/draft.md",
                        "target_path": "chapters/vol-01/ch-001.md",
                    },
                ),
            ],
        )
    )

    finished = await WorkflowExecutor(context, store).run_next(run.run_id)

    assert finished.status == "completed"
    assert finished.steps[1].output["foreshadow_actions"][0]["action"] == "plant"
    assert finished.steps[1].output["fact_records"][0]["subject"] == "门禁"
    assert finished.steps[1].output["change_set_id"]
    assert finished.steps[1].output["foreshadow_verification"][0]["status"] == "review"
    assert await context.read_text("chapters/vol-01/ch-001.md") == "# 第一章\n门禁亮了一下。\n"
    assert (await context.read_json("plot/foreshadows.json"))["items"][0]["title"] == "门禁异常"
    fact_document = await context.read_json("plot/facts/vol-01/ch-001.json")
    assert fact_document["chapter_path"] == "chapters/vol-01/ch-001.md"
    assert fact_document["facts"][0]["value"] == "断电后短暂亮起"
