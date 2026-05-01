"""REST API for preset CRUD operations."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.presets import (
    Preset,
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
