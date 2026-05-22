from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.prompt_packs import PromptPackStage
from app.core.prompt_pack_rendering import (
    enabled_prompt_packs_for_project_stages,
    prompt_pack_metadata,
    prompt_pack_metadata_for_packs,
    render_prompt_pack_block,
    render_prompt_pack_block_from_packs,
)
from app.llm.types import LLMClient
from app.projects.context import ProjectContext


class ToolFileAccess(BaseModel):
    read: list[str] = Field(default_factory=list)
    write: list[str] = Field(default_factory=list)
    generate: list[str] = Field(default_factory=list)


class ToolPresentation(BaseModel):
    type: str
    description: str | None = None


class ToolWorkspaceView(BaseModel):
    view_id: str
    label: str
    marker: str = "工具"


class ToolResult(BaseModel):
    content: str
    ui_hint: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseTool(ABC):
    name: str
    description: str
    has_frontend_ui: bool = True
    required_permissions: list[str] = []
    default_preset_id: str | None = None
    default_agent: str | None = None
    workspace_view: ToolWorkspaceView | None = None

    @abstractmethod
    def schema(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        raise NotImplementedError

    async def invoke(
        self,
        params: dict[str, Any],
        context: ProjectContext,
        llm: LLMClient,
    ) -> ToolResult | None:
        return None

    def ui_schema(self) -> dict[str, Any]:
        return self.schema()

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess()

    def presentation(self) -> ToolPresentation | None:
        return None

    def build_prompt(self, params: dict[str, Any]) -> str:
        access = self.file_access()
        file_lines: list[str] = []
        if access.read:
            file_lines.append(f"可能读取：{', '.join(access.read)}")
        if access.write:
            file_lines.append(f"可能修改：{', '.join(access.write)}")
        if access.generate:
            file_lines.append(f"可能生成：{', '.join(access.generate)}")
        file_notice = "\n".join(file_lines) if file_lines else "无声明的文件影响"
        return (
            f"请使用 `{self.name}` 工具完成任务。\n"
            f"工具说明：{self.description}\n"
            f"文件影响：\n{file_notice}\n"
            f"参数：{params}"
        )

    def prompt_pack_stages(self) -> list[PromptPackStage]:
        return []

    def prompt_pack_block(self) -> str:
        return render_prompt_pack_block(self.prompt_pack_stages())

    def prompt_pack_metadata(self) -> dict[str, Any] | None:
        stages = self.prompt_pack_stages()
        if not stages:
            return None
        return prompt_pack_metadata(stages)

    async def project_prompt_pack_block(self, context: ProjectContext) -> str:
        packs = await enabled_prompt_packs_for_project_stages(context, self.prompt_pack_stages())
        return render_prompt_pack_block_from_packs(packs)

    async def project_prompt_pack_metadata(self, context: ProjectContext) -> dict[str, Any] | None:
        stages = self.prompt_pack_stages()
        if not stages:
            return None
        packs = await enabled_prompt_packs_for_project_stages(context, stages)
        return prompt_pack_metadata_for_packs(stages, packs)

    def frontend_descriptor(self) -> dict[str, Any]:
        presentation = self.presentation()
        return {
            "name": self.name,
            "description": self.description,
            "has_frontend_ui": self.has_frontend_ui,
            "input_schema": self.schema(),
            "ui_schema": self.ui_schema() if self.has_frontend_ui else None,
            "default_preset_id": self.default_preset_id,
            # Deprecated compatibility field. Older frontend builds displayed this as an Agent name.
            "default_agent": self.default_agent,
            "file_access": self.file_access().model_dump(),
            "presentation": presentation.model_dump() if presentation else None,
            "workspace_view": self.workspace_view.model_dump() if self.workspace_view else None,
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
