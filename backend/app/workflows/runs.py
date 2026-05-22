from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


WorkflowRunStatus = Literal["draft", "running", "paused", "completed", "failed", "cancelled"]
WorkflowStepStatus = Literal["pending", "running", "waiting_user", "completed", "failed", "skipped"]
WorkflowStepKind = Literal["plan", "context", "draft", "revise", "check", "write_file", "user_confirm", "custom"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowStepRecord(BaseModel):
    step_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    kind: WorkflowStepKind = "custom"
    status: WorkflowStepStatus = "pending"
    preset_id: str | None = None
    prompt_pack_ids: list[str] = Field(default_factory=list)
    context_pack_ids: list[str] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    output_path: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str = Field(default_factory=utc_now)


class WorkflowRunRecord(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    workflow_type: str = "custom"
    title: str
    status: WorkflowRunStatus = "draft"
    current_step_id: str | None = None
    conversation_id: str | None = None
    agent_run_id: str | None = None
    input_summary: str = ""
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    finished_at: str | None = None
    steps: list[WorkflowStepRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunCreate(BaseModel):
    workflow_type: str = "custom"
    title: str = "未命名工作流"
    input_summary: str = ""
    conversation_id: str | None = None
    agent_run_id: str | None = None
    steps: list[WorkflowStepRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunUpdate(BaseModel):
    title: str | None = None
    status: WorkflowRunStatus | None = None
    current_step_id: str | None = None
    input_summary: str | None = None
    metadata: dict[str, Any] | None = None


class WorkflowStepUpdate(BaseModel):
    name: str | None = None
    kind: WorkflowStepKind | None = None
    status: WorkflowStepStatus | None = None
    preset_id: str | None = None
    prompt_pack_ids: list[str] | None = None
    context_pack_ids: list[str] | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    output_path: str | None = None
    error: str | None = None


class WorkflowRunStore:
    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.root = self.project_root / ".aisync" / "workflows"

    def create(self, data: WorkflowRunCreate) -> WorkflowRunRecord:
        now = utc_now()
        steps = []
        for step in data.steps:
            steps.append(step.model_copy(update={"updated_at": now}))
        record = WorkflowRunRecord(
            workflow_type=data.workflow_type,
            title=data.title.strip() or "未命名工作流",
            input_summary=self._preview(data.input_summary),
            conversation_id=data.conversation_id,
            agent_run_id=data.agent_run_id,
            current_step_id=steps[0].step_id if steps else None,
            steps=steps,
            metadata=data.metadata,
            created_at=now,
            updated_at=now,
        )
        self.save(record)
        return record

    def list(self, limit: int = 50) -> list[WorkflowRunRecord]:
        self.root.mkdir(parents=True, exist_ok=True)
        records: list[WorkflowRunRecord] = []
        for path in self.root.glob("*.json"):
            try:
                records.append(self.load(path.stem))
            except Exception:
                continue
        return sorted(records, key=lambda item: item.updated_at, reverse=True)[:limit]

    def load(self, run_id: str) -> WorkflowRunRecord:
        return WorkflowRunRecord.model_validate_json(self._path(run_id).read_text(encoding="utf-8"))

    def update(self, run_id: str, data: WorkflowRunUpdate) -> WorkflowRunRecord:
        record = self.load(run_id)
        if data.title is not None:
            record.title = data.title.strip() or record.title
        if data.status is not None:
            record.status = data.status
            if data.status in {"completed", "failed", "cancelled"}:
                record.finished_at = utc_now()
            elif data.status in {"draft", "running", "paused"}:
                record.finished_at = None
        if data.current_step_id is not None:
            self._ensure_step(record, data.current_step_id)
            record.current_step_id = data.current_step_id
        if data.input_summary is not None:
            record.input_summary = self._preview(data.input_summary)
        if data.metadata is not None:
            record.metadata = data.metadata
        record.updated_at = utc_now()
        self.save(record)
        return record

    def update_step(self, run_id: str, step_id: str, data: WorkflowStepUpdate) -> WorkflowRunRecord:
        record = self.load(run_id)
        step = self._ensure_step(record, step_id)
        if data.name is not None:
            step.name = data.name.strip() or step.name
        if data.kind is not None:
            step.kind = data.kind
        if data.status is not None:
            step.status = data.status
            if data.status == "running" and step.started_at is None:
                step.started_at = utc_now()
            if data.status in {"completed", "failed", "skipped"}:
                step.finished_at = utc_now()
            if data.status in {"pending", "running", "waiting_user"}:
                step.finished_at = None
            if data.status in {"running", "waiting_user"}:
                record.current_step_id = step.step_id
        for field_name in ["preset_id", "prompt_pack_ids", "context_pack_ids", "input", "output", "output_path", "error"]:
            value = getattr(data, field_name)
            if value is not None:
                setattr(step, field_name, value)
        step.updated_at = utc_now()
        record.updated_at = step.updated_at
        self.save(record)
        return record

    def advance_to_next_step(self, run_id: str, current_step_id: str) -> WorkflowRunRecord:
        record = self.load(run_id)
        for index, step in enumerate(record.steps):
            if step.step_id != current_step_id:
                continue
            next_step = record.steps[index + 1] if index + 1 < len(record.steps) else None
            record.current_step_id = next_step.step_id if next_step else None
            if next_step is None and all(item.status in {"completed", "skipped"} for item in record.steps):
                record.status = "completed"
                record.finished_at = utc_now()
            record.updated_at = utc_now()
            self.save(record)
            return record
        raise ValueError(f"Workflow step not found: {current_step_id}")

    def save(self, record: WorkflowRunRecord) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(record.run_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def _path(self, run_id: str) -> Path:
        if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
            raise ValueError("Invalid workflow run id")
        return self.root / f"{run_id}.json"

    def _ensure_step(self, record: WorkflowRunRecord, step_id: str) -> WorkflowStepRecord:
        for step in record.steps:
            if step.step_id == step_id:
                return step
        raise ValueError(f"Workflow step not found: {step_id}")

    def _preview(self, value: str) -> str:
        text = value.strip().replace("\r\n", "\n")
        return f"{text[:400]}..." if len(text) > 400 else text
