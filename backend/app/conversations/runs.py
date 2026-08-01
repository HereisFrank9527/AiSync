from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field


AgentRunStatus = Literal["running", "completed", "failed", "interrupted", "waiting_user"]
AgentRetryMode = Literal["restart", "finalize"]

MUTATING_TOOL_NAMES = {
    "chapter_draft",
    "character_manage",
    "create_character",
    "edit_chapter",
    "file_change_proposal",
    "foreshadow_manage",
    "outline_generate",
    "update_worldview",
    "write_chapter",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _DraftOverlay:
    content: str
    version: int
    updated_at: str
    last_saved_at: float
    last_saved_chars: int


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
    input_text: str = ""
    input_preview: str = ""
    retry_of_run_id: str | None = None
    retry_mode: AgentRetryMode | None = None
    error: str | None = None
    draft_content: str = ""
    draft_version: int = 0
    draft_updated_at: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    prompt_audit: dict[str, Any] = Field(default_factory=dict)


class AgentRunStore:
    DRAFT_FLUSH_INTERVAL_SECONDS: ClassVar[float] = 0.35
    DRAFT_FLUSH_CHARACTERS: ClassVar[int] = 512
    _draft_overlays: ClassVar[dict[tuple[str, str], _DraftOverlay]] = {}

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.root = self.project_root / ".aisync" / "agent_runs"

    def start(
        self,
        conversation_id: str,
        user_input: str,
        preset_id: str | None = None,
        enabled_tools: list[str] | None = None,
        retry_of_run_id: str | None = None,
        retry_mode: AgentRetryMode | None = None,
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
            input_text=user_input,
            input_preview=self._preview(user_input),
            retry_of_run_id=retry_of_run_id,
            retry_mode=retry_mode,
        )
        self.save(record)
        return record

    def load(self, run_id: str) -> AgentRunRecord:
        record = AgentRunRecord.model_validate_json(self._path(run_id).read_text(encoding="utf-8"))
        overlay = self._draft_overlays.get(self._draft_key(run_id))
        if overlay and overlay.version >= record.draft_version:
            self._apply_draft_overlay(record, overlay)
        return record

    def latest_for_conversation(self, conversation_id: str) -> AgentRunRecord | None:
        records = self.records_for_conversation(conversation_id)
        return records[-1] if records else None

    def records_for_conversation(self, conversation_id: str) -> list[AgentRunRecord]:
        self.root.mkdir(parents=True, exist_ok=True)
        records: list[AgentRunRecord] = []
        for path in self.root.glob("*.json"):
            try:
                record = self.load(path.stem)
            except Exception:
                continue
            if record.conversation_id == conversation_id:
                records.append(record)
        return sorted(records, key=lambda item: (item.started_at, item.updated_at))

    def mark_interrupted_if_running(self, run_id: str, error: str | None = None) -> AgentRunRecord:
        record = self.load(run_id)
        if record.status != "running":
            return record
        return self.finish(run_id, "interrupted", error)

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
        preset_id: str | None = None,
        mode: str | None = None,
        params: dict[str, Any] | None = None,
        call_id: str | None = None,
    ) -> AgentRunRecord:
        record = self.load(run_id)
        now = utc_now()
        event = next(
            (
                item
                for item in reversed(record.tool_calls)
                if call_id and item.get("call_id") == call_id
            ),
            None,
        )
        if event is None:
            event = {
                "name": tool_name,
                "status": status,
                "duration_ms": duration_ms,
                "error": error,
                "at": now,
            }
            record.tool_calls.append(event)
        else:
            event.update(
                {
                    "name": tool_name,
                    "status": status,
                    "duration_ms": duration_ms,
                    "error": error,
                    "finished_at": now,
                }
            )
        if call_id:
            event["call_id"] = call_id
        if preset_id:
            event["preset_id"] = preset_id
        if mode:
            event["mode"] = mode
        if params:
            event["params"] = params
        record.updated_at = now
        self.save(record)
        return record

    def start_tool_event(
        self,
        run_id: str,
        tool_name: str,
        call_id: str,
        params: dict[str, Any] | None = None,
    ) -> AgentRunRecord:
        record = self.load(run_id)
        now = utc_now()
        event = {
            "call_id": call_id,
            "name": tool_name,
            "status": "running",
            "duration_ms": None,
            "error": None,
            "at": now,
        }
        if params:
            event["params"] = params
        record.tool_calls.append(event)
        record.updated_at = now
        self.save(record)
        return record

    def update_prompt_audit(self, run_id: str, prompt_audit: dict[str, Any]) -> AgentRunRecord:
        record = self.load(run_id)
        record.prompt_audit = prompt_audit
        record.updated_at = utc_now()
        self.save(record)
        return record

    def append_draft(self, run_id: str, delta: str, force: bool = False) -> AgentRunRecord:
        record = self.load(run_id)
        key = self._draft_key(run_id)
        overlay = self._draft_overlays.get(key)
        if overlay is None:
            overlay = _DraftOverlay(
                content=record.draft_content,
                version=record.draft_version,
                updated_at=record.draft_updated_at or record.updated_at,
                last_saved_at=monotonic(),
                last_saved_chars=len(record.draft_content),
            )
        overlay.content += delta
        overlay.version += 1
        overlay.updated_at = utc_now()
        self._draft_overlays[key] = overlay
        self._apply_draft_overlay(record, overlay)

        should_save = (
            force
            or monotonic() - overlay.last_saved_at >= self.DRAFT_FLUSH_INTERVAL_SECONDS
            or len(overlay.content) - overlay.last_saved_chars >= self.DRAFT_FLUSH_CHARACTERS
        )
        if should_save:
            self.save(record)
        return record

    def flush_draft(self, run_id: str) -> AgentRunRecord:
        record = self.load(run_id)
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
            "waiting_user": "等待你的选择",
            "running": record.phase_label,
        }[status]
        record.error = error
        if retry_mode_for_run(record) == "finalize":
            record.retry_mode = "finalize"
        elif status in {"failed", "interrupted"} and record.retry_mode is None:
            record.retry_mode = "restart"
        record.updated_at = utc_now()
        record.finished_at = record.updated_at
        if status in {"completed", "waiting_user"}:
            self._draft_overlays.pop(self._draft_key(run_id), None)
            record.draft_content = ""
            record.draft_version = 0
            record.draft_updated_at = None
        self.save(record)
        if status != "running":
            self._draft_overlays.pop(self._draft_key(run_id), None)
        return record

    def save(self, record: AgentRunRecord) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        overlay = self._draft_overlays.get(self._draft_key(record.run_id))
        if overlay and overlay.version >= record.draft_version:
            self._apply_draft_overlay(record, overlay)
        self._path(record.run_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")
        if overlay:
            overlay.last_saved_at = monotonic()
            overlay.last_saved_chars = len(overlay.content)

    def _path(self, run_id: str) -> Path:
        if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
            raise ValueError("Invalid agent run id")
        return self.root / f"{run_id}.json"

    def _draft_key(self, run_id: str) -> tuple[str, str]:
        return str(self.root), run_id

    @staticmethod
    def _apply_draft_overlay(record: AgentRunRecord, overlay: _DraftOverlay) -> None:
        record.draft_content = overlay.content
        record.draft_version = overlay.version
        record.draft_updated_at = overlay.updated_at
        record.updated_at = max(record.updated_at, overlay.updated_at)

    def _preview(self, value: str) -> str:
        text = value.strip().replace("\r\n", "\n")
        return f"{text[:240]}..." if len(text) > 240 else text


def retry_mode_for_run(record: AgentRunRecord) -> AgentRetryMode:
    usage = record.prompt_audit.get("usage") if isinstance(record.prompt_audit, dict) else None
    if isinstance(usage, dict):
        applied = usage.get("applied_change_sets")
        if isinstance(applied, list) and applied:
            return "finalize"
        approvals = usage.get("change_approvals")
        if isinstance(approvals, list) and any(
            isinstance(item, dict) and item.get("decision") == "applied" for item in approvals
        ):
            return "finalize"
    if any(
        call.get("status") == "completed" and str(call.get("name") or "") in MUTATING_TOOL_NAMES
        for call in record.tool_calls
        if isinstance(call, dict)
    ):
        return "finalize"
    return "restart"
