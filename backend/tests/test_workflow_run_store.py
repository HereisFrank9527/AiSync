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


def test_workflow_step_update_can_clear_optional_fields(tmp_path):
    store = WorkflowRunStore(tmp_path)
    run = store.create(
        WorkflowRunCreate(
            title="测试",
            steps=[
                WorkflowStepRecord(
                    name="写草稿",
                    kind="draft",
                    preset_id="custom-model",
                    output_path="temp/drafts/old.md",
                    error="old error",
                )
            ],
        )
    )

    updated = store.update_step(
        run.run_id,
        run.steps[0].step_id,
        WorkflowStepUpdate(preset_id=None, output_path=None, error=None),
    )

    assert updated.steps[0].preset_id is None
    assert updated.steps[0].output_path is None
    assert updated.steps[0].error is None


def test_workflow_store_can_add_delete_steps_and_delete_run(tmp_path):
    store = WorkflowRunStore(tmp_path)
    run = store.create(WorkflowRunCreate(title="自定义流程"))

    with_step = store.add_step(run.run_id, WorkflowStepRecord(name="检索", kind="context"))
    assert len(with_step.steps) == 1
    assert with_step.current_step_id == with_step.steps[0].step_id

    without_step = store.delete_step(run.run_id, with_step.steps[0].step_id)
    assert without_step.steps == []
    assert without_step.current_step_id is None

    assert store.delete(run.run_id) is True
    assert store.delete(run.run_id) is False


def test_workflow_store_can_reset_and_skip_step(tmp_path):
    store = WorkflowRunStore(tmp_path)
    run = store.create(
        WorkflowRunCreate(
            title="重试流程",
            steps=[
                WorkflowStepRecord(name="失败步骤", kind="plan"),
                WorkflowStepRecord(name="后续步骤", kind="draft"),
            ],
        )
    )
    failed = store.update_step(
        run.run_id,
        run.steps[0].step_id,
        WorkflowStepUpdate(status="failed", error="bad"),
    )

    reset = store.reset_step(run.run_id, failed.steps[0].step_id)
    assert reset.status == "draft"
    assert reset.current_step_id == reset.steps[0].step_id
    assert reset.steps[0].status == "pending"
    assert reset.steps[0].error is None

    skipped = store.skip_step(run.run_id, reset.steps[0].step_id)
    assert skipped.steps[0].status == "skipped"
    assert skipped.current_step_id == skipped.steps[1].step_id
