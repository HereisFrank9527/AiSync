from app.workflows.runs import WorkflowRunCreate, WorkflowRunStore, WorkflowRunUpdate, WorkflowStepRecord, WorkflowStepUpdate


def test_workflow_run_lifecycle(tmp_path):
    store = WorkflowRunStore(tmp_path)
    run = store.create(
        WorkflowRunCreate(
            workflow_type="chapter_draft",
            title="第一章草稿",
            input_summary="写第一章开场",
            steps=[
                WorkflowStepRecord(name="生成章节计划", kind="plan", preset_id="planner"),
                WorkflowStepRecord(name="等待确认", kind="user_confirm"),
                WorkflowStepRecord(name="写入草稿", kind="draft", output_path="temp/drafts/ch-001.md"),
            ],
        )
    )

    assert run.run_id
    assert run.status == "draft"
    assert run.current_step_id == run.steps[0].step_id
    assert run.steps[0].name == "生成章节计划"

    updated = store.update_step(
        run.run_id,
        run.steps[0].step_id,
        WorkflowStepUpdate(status="running", input={"goal": "开场"}),
    )
    assert updated.current_step_id == run.steps[0].step_id
    assert updated.steps[0].status == "running"
    assert updated.steps[0].started_at is not None
    assert updated.steps[0].input == {"goal": "开场"}

    completed = store.update_step(
        run.run_id,
        run.steps[0].step_id,
        WorkflowStepUpdate(status="completed", output={"summary": "计划完成"}),
    )
    assert completed.steps[0].status == "completed"
    assert completed.steps[0].finished_at is not None
    assert completed.steps[0].output == {"summary": "计划完成"}

    finished = store.update(run.run_id, WorkflowRunUpdate(status="completed"))
    assert finished.status == "completed"
    assert finished.finished_at is not None

    loaded = store.load(run.run_id)
    assert loaded.run_id == run.run_id


def test_workflow_run_list_latest_first(tmp_path):
    store = WorkflowRunStore(tmp_path)
    first = store.create(WorkflowRunCreate(title="旧工作流"))
    second = store.create(WorkflowRunCreate(title="新工作流"))

    runs = store.list()

    assert [run.run_id for run in runs] == [second.run_id, first.run_id]


def test_workflow_invalid_step_raises(tmp_path):
    store = WorkflowRunStore(tmp_path)
    run = store.create(WorkflowRunCreate(title="测试", steps=[WorkflowStepRecord(name="步骤")]))

    try:
        store.update_step(run.run_id, "missing", WorkflowStepUpdate(status="running"))
    except ValueError as exc:
        assert "Workflow step not found" in str(exc)
    else:
        raise AssertionError("missing workflow step should raise")
