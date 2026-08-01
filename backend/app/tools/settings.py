from __future__ import annotations

from typing import Any

from app.projects.context import ProjectContext

TOOL_SETTINGS_PATH = ".aisync/tool_settings.json"


async def load_tool_settings(context: ProjectContext) -> dict[str, Any]:
    if not await context.exists(TOOL_SETTINGS_PATH):
        return {"tools": {}}
    try:
        data = await context.read_json(TOOL_SETTINGS_PATH)
    except Exception:
        return {"tools": {}}
    if not isinstance(data, dict):
        return {"tools": {}}
    tools = data.get("tools")
    if not isinstance(tools, dict):
        data["tools"] = {}
    return data


async def save_tool_settings(context: ProjectContext, settings_data: dict[str, Any]) -> None:
    await context.write_json(TOOL_SETTINGS_PATH, settings_data)


async def configured_default_preset_id(
    context: ProjectContext,
    tool_name: str,
    code_default: str | None,
) -> str | None:
    settings_data = await load_tool_settings(context)
    entry = settings_data.get("tools", {}).get(tool_name)
    if isinstance(entry, dict) and "default_preset_id" in entry:
        value = entry.get("default_preset_id")
        return str(value) if value else None
    return code_default
