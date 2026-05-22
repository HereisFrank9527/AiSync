from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.core.prompt_packs import PromptPack, PromptPackStage, prompt_pack_store
from app.projects.context import ProjectContext

PROJECT_PROMPT_PACK_SETTINGS_PATH = ".aisync/prompt_pack_settings.json"


async def load_project_prompt_pack_settings(context: ProjectContext) -> dict[str, Any]:
    if not await context.exists(PROJECT_PROMPT_PACK_SETTINGS_PATH):
        return {"mode": "global", "enabled_pack_ids": []}
    try:
        data = await context.read_json(PROJECT_PROMPT_PACK_SETTINGS_PATH)
    except Exception:
        return {"mode": "global", "enabled_pack_ids": []}
    if not isinstance(data, dict):
        return {"mode": "global", "enabled_pack_ids": []}
    mode = "project" if data.get("mode") == "project" else "global"
    raw_ids = data.get("enabled_pack_ids")
    enabled_pack_ids = [str(item) for item in raw_ids] if isinstance(raw_ids, list) else []
    return {"mode": mode, "enabled_pack_ids": enabled_pack_ids}


async def save_project_prompt_pack_settings(
    context: ProjectContext,
    mode: str,
    enabled_pack_ids: list[str],
) -> dict[str, Any]:
    normalized = {
        "mode": "project" if mode == "project" else "global",
        "enabled_pack_ids": list(dict.fromkeys(str(item) for item in enabled_pack_ids if str(item).strip())),
    }
    await context.write_json(PROJECT_PROMPT_PACK_SETTINGS_PATH, normalized)
    return normalized


def enabled_prompt_packs_for_stages(stages: Iterable[PromptPackStage]) -> list[PromptPack]:
    packs: list[PromptPack] = []
    seen: set[str] = set()
    for stage in stages:
        for pack in prompt_pack_store.enabled_for_stage(stage):
            if pack.id in seen:
                continue
            packs.append(pack)
            seen.add(pack.id)
    return packs


async def enabled_prompt_packs_for_project_stages(
    context: ProjectContext | None,
    stages: Iterable[PromptPackStage],
) -> list[PromptPack]:
    packs = enabled_prompt_packs_for_stages(stages)
    if context is None:
        return packs
    settings = await load_project_prompt_pack_settings(context)
    if settings["mode"] != "project":
        return packs
    allowed_ids = set(settings["enabled_pack_ids"])
    return [pack for pack in packs if pack.id in allowed_ids]


def render_prompt_pack_block(stages: Iterable[PromptPackStage]) -> str:
    packs = enabled_prompt_packs_for_stages(stages)
    return render_prompt_pack_block_from_packs(packs)


def prompt_pack_metadata(stages: Iterable[PromptPackStage]) -> dict[str, Any]:
    stage_list = list(stages)
    packs = enabled_prompt_packs_for_stages(stage_list)
    return {
        "stages": stage_list,
        "count": len(packs),
        "ids": [pack.id for pack in packs],
        "names": [pack.name for pack in packs],
        "categories": [pack.category for pack in packs],
    }


def prompt_pack_metadata_for_packs(stages: Iterable[PromptPackStage], packs: list[PromptPack]) -> dict[str, Any]:
    return {
        "stages": list(stages),
        "count": len(packs),
        "ids": [pack.id for pack in packs],
        "names": [pack.name for pack in packs],
        "categories": [pack.category for pack in packs],
    }


def render_prompt_pack_block_from_packs(packs: list[PromptPack]) -> str:
    if not packs:
        return ""

    lines = [
        "以下是当前阶段自动启用的长期提示词包。",
        "这些内容是写作、输出和模型行为规则，不是项目事实；若与项目对象冲突，以项目对象为准；若与用户本轮明确要求冲突，以用户本轮要求为准。",
    ]
    for pack in packs:
        lines.append("")
        lines.append(f"### 提示词包：{pack.name}")
        if pack.description.strip():
            lines.append(f"说明：{pack.description.strip()}")
        lines.append(f"分类：{pack.category}；适用阶段：{', '.join(pack.stages)}")
        lines.append(pack.content.strip())
    return "\n".join(lines)
