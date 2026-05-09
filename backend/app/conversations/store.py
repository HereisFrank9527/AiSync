from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    role: Literal["user", "agent"]
    content: str
    type: str = "message"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


ConversationStatus = Literal["idle", "running", "interrupted", "failed", "completed"]


class Conversation(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    status: ConversationStatus = "completed"
    last_error: str | None = None
    running_since: str | None = None
    messages: list[ConversationMessage] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    status: ConversationStatus
    last_error: str | None = None
    running_since: str | None = None


class ConversationStore:
    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.root = self.project_root / ".aisync" / "conversations"

    def list(self) -> list[ConversationSummary]:
        self.root.mkdir(parents=True, exist_ok=True)
        conversations: list[ConversationSummary] = []
        for path in self.root.glob("*.json"):
            try:
                conv = self.load(path.stem)
            except Exception:
                continue
            conversations.append(
                ConversationSummary(
                    id=conv.id,
                    title=conv.title,
                    created_at=conv.created_at,
                    updated_at=conv.updated_at,
                    message_count=len(conv.messages),
                    status=conv.status,
                    last_error=conv.last_error,
                    running_since=conv.running_since,
                )
            )
        return sorted(conversations, key=lambda item: item.updated_at, reverse=True)

    def create(self, title: str = "新对话") -> Conversation:
        now = datetime.now(timezone.utc).isoformat()
        conv = Conversation(
            id=uuid.uuid4().hex,
            title=title,
            created_at=now,
            updated_at=now,
            status="idle",
        )
        self.save(conv)
        return conv

    def load(self, conversation_id: str) -> Conversation:
        path = self._path(conversation_id)
        return Conversation.model_validate_json(path.read_text(encoding="utf-8"))

    def get_or_create(self, conversation_id: str | None = None) -> Conversation:
        if conversation_id:
            path = self._path(conversation_id)
            if path.exists():
                return self.load(conversation_id)
        return self.create()

    def save(self, conversation: Conversation) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        conversation.updated_at = datetime.now(timezone.utc).isoformat()
        self._path(conversation.id).write_text(conversation.model_dump_json(indent=2), encoding="utf-8")

    def delete(self, conversation_id: str) -> None:
        path = self._path(conversation_id)
        if path.exists():
            path.unlink()

    def append(self, conversation_id: str, role: Literal["user", "agent"], content: str, type: str = "message") -> Conversation:
        conversation = self.get_or_create(conversation_id)
        if len(conversation.messages) == 0 and role == "user":
            conversation.title = content.strip().splitlines()[0][:40] or "新对话"
        conversation.messages.append(ConversationMessage(role=role, content=content, type=type))
        self.save(conversation)
        return conversation

    def set_status(
        self,
        conversation_id: str,
        status: ConversationStatus,
        last_error: str | None = None,
    ) -> Conversation:
        conversation = self.get_or_create(conversation_id)
        conversation.status = status
        conversation.last_error = last_error
        conversation.running_since = datetime.now(timezone.utc).isoformat() if status == "running" else None
        self.save(conversation)
        return conversation

    def _path(self, conversation_id: str) -> Path:
        if not conversation_id or "/" in conversation_id or "\\" in conversation_id or ".." in conversation_id:
            raise ValueError("Invalid conversation id")
        return self.root / f"{conversation_id}.json"
