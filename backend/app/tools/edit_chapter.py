from __future__ import annotations

from typing import Any

from app.core.prompt_packs import PromptPackStage
from app.projects.context import ProjectContext
from app.projects.facts import fact_records_schema
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult
from app.tools.chapter_change import create_chapter_change_set
from app.change_sets import change_set_ui_data


class EditChapterTool(BaseTool):
    name = "edit_chapter"
    description = "编辑已有章节 Markdown 文件。"
    category = "edit"
    write_policy = "direct"
    agent_boundary = "用于按章节路径整体替换、追加或前置章节正文；跨文件清理或精准删除局部说明块应使用 file_change_proposal。"

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(
            read=["chapters/**/*.md", "plot/foreshadows.json", "plot/facts/**/*.json", "plot/outline.json", "chapters/**/ch-meta.yaml"],
            write=["chapters/**/*.md", "plot/facts/**/*.json"],
        )

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="stream:editor", description="章节编辑器预览")

    def prompt_pack_stages(self) -> list[PromptPackStage]:
        return ["revision"]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对于项目根目录的章节路径。"},
                "content": {"type": "string", "description": "要写入、追加或前置的 Markdown 内容。"},
                "mode": {
                    "type": "string",
                    "description": "如何应用到章节。",
                    "enum": ["replace", "append", "prepend"],
                    "default": "replace",
                },
                "foreshadow_actions": {
                    "type": "array",
                    "description": "本次编辑涉及的伏笔动作。没有埋设、推进或回收时传空数组。",
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
        path = str(params.get("path") or "")
        mode = str(params.get("mode") or "replace")
        content = str(params.get("content") or "").strip()
        prompt_pack_block = self.prompt_pack_block()
        return self._build_prompt_text(path, mode, content, prompt_pack_block)

    async def build_project_prompt(self, params: dict[str, Any], context: ProjectContext) -> str:
        path = str(params.get("path") or "")
        mode = str(params.get("mode") or "replace")
        content = str(params.get("content") or "").strip()
        prompt_pack_block = await self.project_prompt_pack_block(context)
        return self._build_prompt_text(path, mode, content, prompt_pack_block)

    def _build_prompt_text(self, path: str, mode: str, content: str, prompt_pack_block: str) -> str:
        prompt_pack_section = f"\n\n{prompt_pack_block}\n" if prompt_pack_block else "\n"
        return (
            "请根据当前项目设定编辑章节，并调用 `edit_chapter` 工具写回章节文件。\n"
            f"目标章节路径：{path or '请从用户要求判断'}\n"
            f"应用方式：{mode}\n"
            f"编辑要求或草稿：{content or '按当前章节内容、项目上下文和用户要求修改。'}\n"
            f"{prompt_pack_section}"
            "如果本次编辑埋设、推进或回收伏笔，请在工具参数中同时填写 foreshadow_actions；"
            "plant 必须给出 title 和 summary，advance/payoff 必须使用已有 foreshadow_id；没有处理伏笔时使用空数组。\n"
            "请检查 plot/foreshadows.json：如果目标章节是某个伏笔的埋设/回收章节，或关联同一大纲节点，"
            "修改时应保持伏笔状态一致；不要主动使用已废弃伏笔。"
            "如果本次修改改变了本章长期事实，请填写 fact_records，内容应是修改后整章的事实快照而非仅新增项；"
            "传空数组表示清空该章旧事实快照，不传则保持旧快照不变。每条必须带正文证据，最多 12 条。"
        )

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        path = str(params["path"])
        content = str(params["content"])
        mode = str(params.get("mode", "replace"))

        if not path.startswith("chapters/") or not path.endswith(".md"):
            raise ValueError("Chapter path must be under chapters/ and end with .md")
        if mode not in {"replace", "append", "prepend"}:
            raise ValueError("Mode must be replace, append, or prepend")
        if not await context.exists(path):
            raise ValueError(f"Chapter does not exist: {path}")

        current = await context.read_text(path)
        if mode == "append":
            updated = f"{current.rstrip()}\n\n{content.lstrip()}"
        elif mode == "prepend":
            updated = f"{content.rstrip()}\n\n{current.lstrip()}"
        else:
            updated = content

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
            content=updated,
            actions=actions,
            fact_records=raw_facts,
            title=f"编辑章节并更新结构化记录：{path}",
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
                    f"章节编辑、{len(facts)} 条长期事实和 {len(applied_actions)} 条伏笔动作"
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
                    "mode": mode,
                },
            )

        await context.write_text(path, updated)
        return ToolResult(
            content=f"章节已更新：{path}",
            ui_hint={"type": "stream:editor", "data": {"path": path, "content": updated}},
            metadata={"path": path, "mode": mode},
        )
