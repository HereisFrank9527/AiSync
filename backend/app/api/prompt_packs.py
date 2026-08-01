from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.config import settings
from app.core.prompt_pack_rendering import (
    load_project_prompt_pack_settings,
    save_project_prompt_pack_settings,
)
from app.core.prompt_pack_examples import prompt_pack_create_from_example, prompt_pack_examples
from app.core.prompt_packs import (
    PromptPack,
    PromptPackCopy,
    PromptPackCreate,
    PromptPackUpdate,
    prompt_pack_store,
)
from app.projects.context import ProjectContext

router = APIRouter(prefix="/prompt-packs", tags=["prompt-packs"])


class ProjectPromptPackSettingsUpdate(BaseModel):
    project_path: str
    mode: str = "global"
    enabled_pack_ids: list[str] = []


def project_context(project_path: str) -> ProjectContext:
    return ProjectContext(settings.project_path(project_path=project_path))


@router.get("")
async def list_prompt_packs() -> list[PromptPack]:
    return prompt_pack_store.list_all()


@router.get("/examples")
async def list_prompt_pack_examples() -> list[dict[str, object]]:
    return prompt_pack_examples()


@router.post("/examples/{example_id}", status_code=201)
async def create_prompt_pack_from_example(example_id: str) -> PromptPack:
    data = prompt_pack_create_from_example(example_id)
    if not data:
        raise HTTPException(status_code=404, detail="Prompt pack example not found")
    return prompt_pack_store.create(data)


@router.get("/project-settings")
async def get_project_prompt_pack_settings(project_path: str = Query(...)) -> dict[str, Any]:
    return await load_project_prompt_pack_settings(project_context(project_path))


@router.put("/project-settings")
async def update_project_prompt_pack_settings(body: ProjectPromptPackSettingsUpdate) -> dict[str, Any]:
    known_ids = {pack.id for pack in prompt_pack_store.list_all()}
    filtered_ids = [pack_id for pack_id in body.enabled_pack_ids if pack_id in known_ids]
    return await save_project_prompt_pack_settings(project_context(body.project_path), body.mode, filtered_ids)


@router.get("/{pack_id}")
async def get_prompt_pack(pack_id: str) -> PromptPack:
    pack = prompt_pack_store.get(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Prompt pack not found")
    return pack


@router.post("", status_code=201)
async def create_prompt_pack(body: PromptPackCreate) -> PromptPack:
    return prompt_pack_store.create(body)


@router.post("/{pack_id}/copy", status_code=201)
async def copy_prompt_pack(pack_id: str, body: PromptPackCopy) -> PromptPack:
    pack = prompt_pack_store.copy(pack_id, body.name)
    if not pack:
        raise HTTPException(status_code=404, detail="Prompt pack not found")
    return pack


@router.put("/{pack_id}")
async def update_prompt_pack(pack_id: str, body: PromptPackUpdate) -> PromptPack:
    pack = prompt_pack_store.update(pack_id, body)
    if not pack:
        raise HTTPException(status_code=404, detail="Prompt pack not found")
    return pack


@router.delete("/{pack_id}")
async def delete_prompt_pack(pack_id: str) -> dict[str, str]:
    if not prompt_pack_store.delete(pack_id):
        raise HTTPException(status_code=404, detail="Prompt pack not found")
    return {"status": "deleted"}
