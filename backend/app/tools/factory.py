from __future__ import annotations

from app.tools.registry import ToolRegistry


def create_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.auto_discover()
    return registry
