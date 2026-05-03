from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.projects.context import ProjectContext


class ToolResult(BaseModel):
    content: str
    ui_hint: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseTool(ABC):
    name: str
    description: str
    has_frontend_ui: bool = True
    required_permissions: list[str] = []

    @abstractmethod
    def schema(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        raise NotImplementedError

    def ui_schema(self) -> dict[str, Any]:
        return self.schema()

    def build_prompt(self, params: dict[str, Any]) -> str:
        return (
            f"请使用 `{self.name}` 工具完成任务。\n"
            f"工具说明：{self.description}\n"
            f"参数：{params}"
        )

    def frontend_descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "has_frontend_ui": self.has_frontend_ui,
            "ui_schema": self.ui_schema() if self.has_frontend_ui else None,
        }

    def claude_schema(self) -> dict[str, Any]:
        schema = self.schema()
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
