from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolResult


class ChoiceOption(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=120)
    value: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=300)

    @field_validator("id", "label", "value", "description", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def fill_value(self) -> "ChoiceOption":
        if not self.value:
            self.value = self.label
        return self


class ChoiceGroup(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    mode: Literal["single", "multiple"] = "single"
    required: bool = True
    min_selections: int | None = Field(default=None, ge=0)
    max_selections: int | None = Field(default=None, ge=1)
    options: list[ChoiceOption] = Field(min_length=2, max_length=8)

    @field_validator("id", "title", "description", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_selection_limits(self) -> "ChoiceGroup":
        option_ids = [option.id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError(f"选择组 {self.id} 的选项 id 不能重复")

        if self.mode == "single":
            self.min_selections = 1 if self.required else 0
            self.max_selections = 1
            return self

        minimum = self.min_selections
        if minimum is None:
            minimum = 1 if self.required else 0
        maximum = self.max_selections
        if maximum is None:
            maximum = len(self.options)
        if self.required and minimum < 1:
            raise ValueError(f"必选组 {self.id} 的 min_selections 至少为 1")
        if minimum > maximum:
            raise ValueError(f"选择组 {self.id} 的 min_selections 不能大于 max_selections")
        if maximum > len(self.options):
            raise ValueError(f"选择组 {self.id} 的 max_selections 不能超过选项数量")
        self.min_selections = minimum
        self.max_selections = maximum
        return self


class ChoiceRequest(BaseModel):
    groups: list[ChoiceGroup] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_group_ids(self) -> "ChoiceRequest":
        group_ids = [group.id for group in self.groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("选择组 id 不能重复")
        return self


class PresentChoicesTool(BaseTool):
    name = "present_choices"
    description = (
        "向用户展示结构化选择并暂停本轮 Agent，等待用户提交。"
        "支持单选、多选、多个独立选择组，以及必选、可选和最少/最多选择限制。"
        "只有真正需要用户决策时才调用；普通步骤说明、编号列表和总结不要调用。"
    )
    has_frontend_ui = False
    agent_internal = True
    category = "manage"
    write_policy = "none"
    agent_boundary = (
        "这是交互协议工具，不读写项目文件。必须在已具备决策所需信息后单独调用，"
        "不要与其他工具并行调用；选项只放在工具参数中，不要在正文里重复编号列表。"
    )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "groups": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "description": "本次需要用户处理的一个或多个选择组。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "pattern": "^[A-Za-z0-9_-]+$",
                                "description": "本次回复内唯一且稳定的选择组 id。",
                            },
                            "title": {"type": "string", "description": "用户看到的简短问题。"},
                            "description": {"type": "string", "description": "可选的补充说明。"},
                            "mode": {
                                "type": "string",
                                "enum": ["single", "multiple"],
                                "description": "single 为单选，multiple 为多选。",
                            },
                            "required": {"type": "boolean", "default": True},
                            "min_selections": {
                                "type": "integer",
                                "minimum": 0,
                                "description": "多选组最少选择数量。",
                            },
                            "max_selections": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "多选组最多选择数量。",
                            },
                            "options": {
                                "type": "array",
                                "minItems": 2,
                                "maxItems": 8,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {
                                            "type": "string",
                                            "pattern": "^[A-Za-z0-9_-]+$",
                                            "description": "组内唯一的选项 id。",
                                        },
                                        "label": {"type": "string", "description": "选项标题。"},
                                        "value": {
                                            "type": "string",
                                            "description": "提交给 Agent 的值；省略时使用 label。",
                                        },
                                        "description": {"type": "string", "description": "可选的选项说明。"},
                                    },
                                    "required": ["id", "label"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["id", "title", "mode", "options"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["groups"],
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        del context
        request = ChoiceRequest.model_validate(params)
        request_id = uuid.uuid4().hex
        groups = [group.model_dump() for group in request.groups]
        return ToolResult(
            content=f"已展示 {len(groups)} 个选择组，等待用户提交。",
            metadata={
                "choice_request_id": request_id,
                "choice_groups": groups,
            },
        )
