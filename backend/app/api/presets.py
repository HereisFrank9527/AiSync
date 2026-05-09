"""REST API for preset CRUD operations."""

from __future__ import annotations

import os

from anthropic import AsyncAnthropic
from fastapi import APIRouter, HTTPException
from openai import AsyncOpenAI

from app.core.presets import (
    LLMParams,
    Preset,
    PresetCopy,
    PresetCreate,
    PresetUpdate,
    preset_store,
)

router = APIRouter(prefix="/presets", tags=["presets"])


@router.get("")
async def list_presets() -> list[Preset]:
    return preset_store.list_all()


@router.get("/{preset_id}")
async def get_preset(preset_id: str) -> Preset:
    preset = preset_store.get(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return preset


@router.post("", status_code=201)
async def create_preset(body: PresetCreate) -> Preset:
    return preset_store.create(body)


@router.post("/models")
async def list_models(body: LLMParams) -> dict[str, list[str]]:
    api_key = body.api_key or os.getenv(body.api_key_env)
    if not api_key:
        raise HTTPException(status_code=400, detail="缺少 API Key 或可用的 API Key 环境变量")

    try:
        if body.provider in {"openai", "custom"}:
            client = AsyncOpenAI(api_key=api_key, base_url=body.api_base)
            response = await client.models.list()
            models = sorted(str(item.id) for item in response.data if getattr(item, "id", None))
            return {"models": models}

        if body.provider == "anthropic":
            kwargs = {"api_key": api_key}
            if body.api_base:
                kwargs["base_url"] = body.api_base
            client = AsyncAnthropic(**kwargs)
            response = await client.models.list()
            data = getattr(response, "data", response)
            models = sorted(str(item.id) for item in data if getattr(item, "id", None))
            return {"models": models}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法获取模型列表：{exc}") from exc

    raise HTTPException(status_code=400, detail=f"不支持的供应商：{body.provider}")


@router.post("/{preset_id}/copy", status_code=201)
async def copy_preset(preset_id: str, body: PresetCopy) -> Preset:
    preset = preset_store.copy(preset_id, body.name)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return preset


@router.put("/{preset_id}")
async def update_preset(preset_id: str, body: PresetUpdate) -> Preset:
    preset = preset_store.update(preset_id, body)
    if not preset:
        raise HTTPException(
            status_code=404,
            detail="Preset not found or is a built-in preset",
        )
    return preset


@router.delete("/{preset_id}")
async def delete_preset(preset_id: str) -> dict[str, str]:
    if not preset_store.delete(preset_id):
        raise HTTPException(
            status_code=404,
            detail="Preset not found or is a built-in preset",
        )
    return {"status": "deleted"}
