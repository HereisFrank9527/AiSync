from app.llm.types import ChatRequest, ChatResponse
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
                WorkflowStepRecord(name="生成章节计划", kind="plan"),
                WorkflowStepRecord(name="用户确认计划", kind="user_confirm"),
                WorkflowStepRecord(name="分段写作草稿", kind="draft", output_path="temp/drafts/"),
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

    waiting = await executor.run_next(run.run_id)
    assert waiting.steps[2].status == "waiting_user"

    confirmed = await executor.confirm_current_step(run.run_id, "计划可用")
    assert confirmed.steps[2].status == "completed"
    assert confirmed.current_step_id == confirmed.steps[3].step_id

    drafted = await executor.run_next(run.run_id)
    assert drafted.steps[3].status == "completed"
    assert drafted.steps[3].output_path == f"temp/drafts/{run.run_id}.md"
    assert await context.read_text(f"temp/drafts/{run.run_id}.md") == "# 第一章\n\n正文草稿。\n"
