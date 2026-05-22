from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


AgentRunStatus = Literal["running", "completed", "failed", "interrupted"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRunRecord(BaseModel):
    run_id: str
    conversation_id: str
    status: AgentRunStatus
    phase: str
    phase_label: str
    started_at: str
    updated_at: str
    finished_at: str | None = None
    preset_id: str | None = None
    enabled_tools: list[str] | None = None
    input_preview: str = ""
    error: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    prompt_audit: dict[str, Any] = Field(default_factory=dict)


class AgentRunStore:
    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.root = self.project_root / ".aisync" / "agent_runs"

    def start(
        self,
        conversation_id: str,
        user_input: str,
        preset_id: str | None = None,
        enabled_tools: list[str] | None = None,
    ) -> AgentRunRecord:
        now = utc_now()
        record = AgentRunRecord(
            run_id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            status="running",
            phase="starting",
            phase_label="正在启动 Agent",
            started_at=now,
            updated_at=now,
            preset_id=preset_id,
            enabled_tools=enabled_tools,
            input_preview=self._preview(user_input),
        )
        self.save(record)
        return record

    def load(self, run_id: str) -> AgentRunRecord:
        return AgentRunRecord.model_validate_json(self._path(run_id).read_text(encoding="utf-8"))

    def latest_for_conversation(self, conversation_id: str) -> AgentRunRecord | None:
        self.root.mkdir(parents=True, exist_ok=True)
        records: list[AgentRunRecord] = []
        for path in self.root.glob("*.json"):
            try:
                record = self.load(path.stem)
            except Exception:
                continue
            if record.conversation_id == conversation_id:
                records.append(record)
        if not records:
            return None
        return max(records, key=lambda item: item.updated_at)

    def update_phase(self, run_id: str, phase: str, phase_label: str) -> AgentRunRecord:
        record = self.load(run_id)
        if record.status == "running":
            record.phase = phase
            record.phase_label = phase_label
            record.updated_at = utc_now()
            self.save(record)
        return record

    def add_tool_event(
        self,
        run_id: str,
        tool_name: str,
        status: str,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> AgentRunRecord:
        record = self.load(run_id)
        record.tool_calls.append(
            {
                "name": tool_name,
                "status": status,
                "duration_ms": duration_ms,
                "error": error,
                "at": utc_now(),
            }
        )
        record.updated_at = utc_now()
        self.save(record)
        return record

    def update_prompt_audit(self, run_id: str, prompt_audit: dict[str, Any]) -> AgentRunRecord:
        record = self.load(run_id)
        record.prompt_audit = prompt_audit
        record.updated_at = utc_now()
        self.save(record)
        return record

    def finish(self, run_id: str, status: AgentRunStatus, error: str | None = None) -> AgentRunRecord:
        record = self.load(run_id)
        record.status = status
        record.phase = status
        record.phase_label = {
            "completed": "回复已完成",
            "failed": "回复失败",
            "interrupted": "回复已中断",
            "running": record.phase_label,
        }[status]
        record.error = error
        record.updated_at = utc_now()
        record.finished_at = record.updated_at
        self.save(record)
        return record

    def save(self, record: AgentRunRecord) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(record.run_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def _path(self, run_id: str) -> Path:
        if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
            raise ValueError("Invalid agent run id")
        return self.root / f"{run_id}.json"

    def _preview(self, value: str) -> str:
        text = value.strip().replace("\r\n", "\n")
        return f"{text[:240]}..." if len(text) > 240 else text
