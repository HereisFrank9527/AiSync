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
    required_permissions: list[str] = []

    @abstractmethod
    def schema(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        raise NotImplementedError

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
