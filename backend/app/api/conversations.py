from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.conversations.store import ConversationStore

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationCreateRequest(BaseModel):
    title: str = "新对话"
    project_path: str | None = None


def get_store(project_path: str | None) -> ConversationStore:
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path is required")
    return ConversationStore(Path(project_path))


@router.get("")
async def list_conversations(project_path: str = Query(...)) -> list[dict[str, Any]]:
    store = get_store(project_path)
    return [item.model_dump() for item in store.list()]


@router.post("")
async def create_conversation(request: ConversationCreateRequest) -> dict[str, Any]:
    store = get_store(request.project_path)
    conv = store.create(request.title)
    return conv.model_dump()


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, project_path: str = Query(...)) -> dict[str, Any]:
    store = get_store(project_path)
    try:
        return store.load(conversation_id).model_dump()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, project_path: str = Query(...)) -> dict[str, str]:
    store = get_store(project_path)
    store.delete(conversation_id)
    return {"status": "deleted"}
