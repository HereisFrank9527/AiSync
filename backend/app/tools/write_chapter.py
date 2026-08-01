from __future__ import annotations

from typing import Any

from app.change_sets import change_set_ui_data
from app.core.prompt_packs import PromptPackStage
from app.projects.context import ProjectContext
from app.projects.facts import fact_records_schema
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult, ToolWorkspaceView
from app.tools.chapter_change import create_chapter_change_set


class WriteChapterTool(BaseTool):
    name = "write_chapter"
    description = "写入或覆盖短章节 Markdown 文件；长章节应使用 chapter_draft 分块生成后提交。"
    workspace_view = ToolWorkspaceView(view_id="chapters", label="章节管理")
    category = "generate"
    write_policy = "direct"
    agent_boundary = (
        "用于不超过约 6000 字符的完整章节正文；更长正文必须使用 chapter_draft 分块缓冲。"
        "局部清理、删除旧段落或跨文件修补应使用 file_change_proposal。"
    )

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(
            read=["plot/foreshadows.json", "plot/facts/**/*.json", "plot/outline.json", "chapters/**/ch-meta.yaml"],
            write=["chapters/**/*.md", "plot/facts/**/*.json"],
        )

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="stream:editor", description="章节编辑器预览")

    def prompt_pack_stages(self) -> list[PromptPackStage]:
        return ["chapter_draft"]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对于项目根目录的章节路径。"},
                "content": {
                    "type": "string",
                    "maxLength": 6000,
                    "description": "短章节 Markdown 内容，最多 6000 字符；长章节改用 chapter_draft。",
                },
                "foreshadow_actions": {
                    "type": "array",
                    "description": "本章伏笔动作。没有埋设、推进或回收时传空数组。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["plant", "advance", "payoff", "none"]},
                            "foreshadow_id": {"type": "string"},
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "payoff_chapter": {"type": "string"},
                            "evidence": {"type": "string"},
                            "importance": {"type": "string", "enum": ["minor", "medium", "major"]},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["action"],
                        "additionalProperties": False,
                    },
                },
                "fact_records": fact_records_schema(),
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }

    def build_prompt(self, params: dict[str, Any]) -> str:
        path = str(params.get("path") or "chapters/vol-01/ch-001.md")
        requirements = str(params.get("content") or "").strip()
        prompt_pack_block = self.prompt_pack_block()
        return self._build_prompt_text(path, requirements, prompt_pack_block)

    async def build_project_prompt(self, params: dict[str, Any], context: ProjectContext) -> str:
        path = str(params.get("path") or "chapters/vol-01/ch-001.md")
        requirements = str(params.get("content") or "").strip()
        prompt_pack_block = await self.project_prompt_pack_block(context)
        return self._build_prompt_text(path, requirements, prompt_pack_block)

    def _build_prompt_text(self, path: str, requirements: str, prompt_pack_block: str) -> str:
        prompt_pack_section = f"\n\n{prompt_pack_block}\n" if prompt_pack_block else "\n"
        return (
            "请根据当前项目设定撰写章节。预计正文不超过约 6000 字符时调用 `write_chapter`；"
            "更长章节必须调用 `chapter_draft`，依次 begin、分块 append、finalize，"
            "不要把整章正文塞进一次工具参数。\n"
            f"目标章节路径：{path}\n"
            f"写作要求或草稿：{requirements or '按当前大纲、章节元数据和项目上下文创作。'}\n"
            f"{prompt_pack_section}"
            "如果本章埋设、推进或回收伏笔，请在工具参数中同时填写 foreshadow_actions；"
            "plant 必须给出 title 和 summary，advance/payoff 必须使用已有 foreshadow_id；没有处理伏笔时使用空数组。\n"
            "请优先参考 plot/foreshadows.json：如果存在与目标章节、大纲节点或标签相关的伏笔，"
            "需要判断本章应埋设、推进还是回收；不要主动使用已废弃伏笔。"
            "同时填写 fact_records，只记录本章结束后仍值得跨章节记住的身份、状态、关系、位置、持有物、时间点和世界规则；"
            "每条必须引用正文短证据，最多 12 条。普通动作、气氛和修辞不要记录；没有长期事实时传空数组。"
        )

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        path = str(params["path"])
        content = str(params["content"])
        if not path.startswith("chapters/") or not path.endswith(".md"):
            raise ValueError("Chapter path must be under chapters/ and end with .md")
        raw_actions = params.get("foreshadow_actions") or []
        if not isinstance(raw_actions, list):
            raise ValueError("foreshadow_actions must be a list")
        actions = [item for item in raw_actions if isinstance(item, dict)]
        raw_facts = params.get("fact_records") if "fact_records" in params else None
        if raw_facts is not None and not isinstance(raw_facts, list):
            raise ValueError("fact_records must be a list")
        proposal = await create_chapter_change_set(
            context,
            path=path,
            content=content,
            actions=actions,
            fact_records=raw_facts,
            title=f"写入章节并更新结构化记录：{path}",
        )
        if proposal:
            record = proposal.record
            applied_actions = proposal.foreshadow_actions
            facts = proposal.fact_records
            warnings = proposal.warnings
            ui_data = change_set_ui_data(record)
            ui_data["foreshadow_actions"] = applied_actions
            ui_data["fact_records"] = facts
            ui_data["warnings"] = warnings
            warning_text = f"另有 {len(warnings)} 条无效伏笔动作已跳过，正文不受影响。" if warnings else ""
            return ToolResult(
                content=(
                    f"章节内容、{len(facts)} 条长期事实和 {len(applied_actions)} 条伏笔动作"
                    f"已生成待确认改动包：{record.id}。"
                    f"{warning_text}"
                    "请在差异预览中确认后再写入。"
                ),
                ui_hint={"type": "changeset:proposal", "data": ui_data},
                metadata={
                    "changeset_id": record.id,
                    "foreshadow_actions": applied_actions,
                    "fact_records": facts,
                    "warnings": warnings,
                    "paths": [change.path for change in record.changes],
                },
            )
        await context.write_text(path, content)
        return ToolResult(
            content=f"章节已写入：{path}",
            ui_hint={"type": "stream:editor", "data": {"path": path, "content": content}},
            metadata={"fact_records": []},
        )
