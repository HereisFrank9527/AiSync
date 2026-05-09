from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from types import ModuleType

from app.tools.base import BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> BaseTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def get_all_schemas(self) -> list[dict]:
        return [self._tools[name].claude_schema() for name in sorted(self._tools)]

    def get_schemas(self, enabled_tools: list[str] | set[str] | None = None) -> list[dict]:
        if enabled_tools is None:
            return self.get_all_schemas()
        enabled = set(enabled_tools)
        return [self._tools[name].claude_schema() for name in sorted(self._tools) if name in enabled]

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def get_all_descriptors(self) -> list[dict]:
        return [self._tools[name].frontend_descriptor() for name in sorted(self._tools)]

    def all(self) -> list[BaseTool]:
        return [self._tools[name] for name in sorted(self._tools)]

    def auto_discover(self, package: str = "app.tools") -> None:
        root = Path(__file__).parent
        for path in root.glob("*.py"):
            if path.name.startswith("_") or path.stem in {"base", "registry"}:
                continue
            module = importlib.import_module(f"{package}.{path.stem}")
            self._register_module_tools(module)

    def _register_module_tools(self, module: ModuleType) -> None:
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is BaseTool or not issubclass(obj, BaseTool):
                continue
            if obj.__module__ != module.__name__:
                continue
            self.register(obj())
