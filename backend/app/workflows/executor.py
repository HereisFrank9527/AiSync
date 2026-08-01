from __future__ import annotations

import json
import re
from typing import Any

from app.change_sets import apply_change_set
from app.core.config import settings
from app.core.prompt_pack_rendering import enabled_prompt_packs_for_project_stages, render_prompt_pack_block_from_packs
from app.core.prompt_packs import PromptPackStage, prompt_pack_store
from app.core.presets import preset_store
from app.llm.factory import create_llm_client, create_llm_client_from_preset
from app.llm.types import ChatRequest, LLMClient
from app.projects.context import ProjectContext
from app.projects.facts import load_chapter_facts
from app.projects.foreshadows import (
    foreshadow_context_for_prompt,
    persist_foreshadow_verification,
    verify_foreshadow_actions,
)
from app.tools.chapter_change import create_chapter_change_set
from app.vector.store import ProjectVectorStore
from app.workflows.chapter_batch import chapter_path, normalize_volume
from app.workflows.runs import WorkflowRunRecord, WorkflowRunStore, WorkflowRunUpdate, WorkflowStepRecord, WorkflowStepUpdate


class WorkflowExecutor:
    def __init__(self, context: ProjectContext, store: WorkflowRunStore) -> None:
        self.context = context
        self.store = store
        self.vector_store = ProjectVectorStore(context)

    async def run_next(self, run_id: str) -> WorkflowRunRecord:
        run = self.store.load(run_id)
        if run.status in {"completed", "failed", "cancelled"}:
            return run
        step = self._current_or_next_step(run)
        if step is None:
            return self.store.update(run_id, WorkflowRunUpdate(status="completed"))

        self.store.update(run_id, WorkflowRunUpdate(status="running", current_step_id=step.step_id))
        try:
            if step.kind == "context":
                return await self._run_context_step(run_id, step)
            if step.kind == "plan":
                return await self._run_plan_step(run_id, step)
            if step.kind == "user_confirm":
                return self.store.update_step(run_id, step.step_id, WorkflowStepUpdate(status="waiting_user"))
            if step.kind in {"draft", "revise"}:
                return await self._run_draft_step(run_id, step)
            if step.kind == "write_file":
                return await self._run_write_file_step(run_id, step)
            if step.kind == "chapter":
                return await self._run_chapter_step(run_id, step)
            return self.store.update_step(
                run_id,
                step.step_id,
                WorkflowStepUpdate(status="completed", output={"note": "当前步骤类型暂无自动执行器，已跳过执行。"}),
            )
        except Exception as exc:
            self.store.update_step(run_id, step.step_id, WorkflowStepUpdate(status="failed", error=str(exc)))
            return self.store.update(run_id, WorkflowRunUpdate(status="failed"))

    async def confirm_current_step(self, run_id: str, note: str = "") -> WorkflowRunRecord:
        run = self.store.load(run_id)
        if not run.current_step_id:
            return run
        step = self._step_by_id(run, run.current_step_id)
        if step.kind != "user_confirm" or step.status != "waiting_user":
            return run
        self.store.update_step(
            run_id,
            step.step_id,
            WorkflowStepUpdate(status="completed", output={"confirmed": True, "note": note}),
        )
        return self.store.advance_to_next_step(run_id, step.step_id)

    async def _run_write_file_step(self, run_id: str, step: WorkflowStepRecord) -> WorkflowRunRecord:
        run = self.store.load(run_id)
        self.store.update_step(run_id, step.step_id, WorkflowStepUpdate(status="running"))
        source_path = str(step.input.get("source_path") or "").strip()
        target_path = str(step.input.get("target_path") or "").strip()
        if not source_path:
            source_path = self._latest_draft_path(run)
        if not source_path.startswith("temp/drafts/") or not source_path.endswith(".md"):
            raise ValueError("正式写入步骤只允许从 temp/drafts/*.md 读取草稿。")
        if not target_path.startswith("chapters/") or not target_path.endswith(".md"):
            raise ValueError("正式写入目标必须是 chapters/**/*.md。")
        content = await self.context.read_text(source_path)
        draft_step = next(
            (candidate for candidate in reversed(run.steps) if candidate.kind in {"draft", "revise"} and candidate.output),
            None,
        )
        raw_actions = draft_step.output.get("foreshadow_actions", []) if draft_step and isinstance(draft_step.output, dict) else []
        actions = [item for item in raw_actions if isinstance(item, dict)] if isinstance(raw_actions, list) else []
        raw_facts = (
            draft_step.output.get("fact_records")
            if draft_step and isinstance(draft_step.output, dict) and "fact_records" in draft_step.output
            else None
        )
        fact_records = raw_facts if isinstance(raw_facts, list) else None
        proposal = await create_chapter_change_set(
            self.context,
            path=target_path,
            content=content.rstrip() + "\n",
            actions=actions,
            fact_records=fact_records,
            title=f"工作流写入章节并更新结构化记录：{target_path}",
        )
        change_set_id = None
        applied_actions: list[dict[str, Any]] = []
        applied_facts: list[dict[str, Any]] = []
        foreshadow_verification: list[dict[str, Any]] = []
        warnings: list[str] = []
        if proposal:
            record = proposal.record
            applied_actions = proposal.foreshadow_actions
            applied_facts = proposal.fact_records
            warnings = proposal.warnings
            await apply_change_set(self.context, record.id)
            change_set_id = record.id
            foreshadow_verification = await verify_foreshadow_actions(self.context, applied_actions)
            await persist_foreshadow_verification(self.context, foreshadow_verification)
        else:
            await self.context.write_text(target_path, content.rstrip() + "\n")
        output = {
            "source_path": source_path,
            "target_path": target_path,
            "characters": len(content),
            "summary": f"已将草稿写入正式章节：{target_path}",
            "foreshadow_actions": applied_actions,
            "fact_records": applied_facts,
            "foreshadow_verification": foreshadow_verification,
            "warnings": warnings,
            "change_set_id": change_set_id,
        }
        self.store.update_step(
            run_id,
            step.step_id,
            WorkflowStepUpdate(status="completed", output=output, output_path=target_path),
        )
        return self.store.advance_to_next_step(run_id, step.step_id)

    async def _run_context_step(self, run_id: str, step: WorkflowStepRecord) -> WorkflowRunRecord:
        run = self.store.load(run_id)
        self.store.update_step(run_id, step.step_id, WorkflowStepUpdate(status="running"))
        query = run.input_summary or run.title
        vector_context = await self.vector_store.query(query, top_k=6)
        foreshadow_context = await foreshadow_context_for_prompt(self.context, query, limit=6)
        output = {
            "query": query,
            "vector_context": [
                {
                    "path": item.get("path"),
                    "collection": item.get("collection"),
                    "score": item.get("score"),
                    "content": str(item.get("content") or "")[:700],
                }
                for item in vector_context
            ],
            "foreshadow_context": foreshadow_context,
        }
        self.store.update_step(run_id, step.step_id, WorkflowStepUpdate(status="completed", output=output))
        return self.store.advance_to_next_step(run_id, step.step_id)

    async def _run_chapter_step(self, run_id: str, step: WorkflowStepRecord) -> WorkflowRunRecord:
        run = self.store.load(run_id)
        self.store.update_step(run_id, step.step_id, WorkflowStepUpdate(status="running", error=None))
        chapter_number = self._chapter_number(step)
        volume = normalize_volume(str(step.input.get("volume") or "vol-01"))
        target_path = str(step.input.get("target_path") or chapter_path(volume, chapter_number)).strip()
        if target_path != chapter_path(volume, chapter_number):
            raise ValueError("连续章节步骤的目标路径与章节号不匹配")
        if await self.context.exists(target_path) and not bool(step.input.get("overwrite_existing")):
            raise ValueError(f"章节已存在：{target_path}。如需重写，请编辑步骤并启用覆盖。")

        prompt, prompt_pack_metadata, context_metadata = await self._build_chapter_prompt(run, step)
        response = await self._llm(step).chat(
            ChatRequest(messages=[{"role": "user", "content": prompt}], stream=False)
        )
        content, foreshadow_actions, fact_records = self._parse_draft_response(response.text)
        if not content.strip():
            raise ValueError("模型没有返回章节正文")

        proposal = await create_chapter_change_set(
            self.context,
            path=target_path,
            content=content.rstrip() + "\n",
            actions=[item for item in foreshadow_actions if isinstance(item, dict)],
            fact_records=fact_records,
            title=f"连续章节工作流写入第 {chapter_number} 章：{target_path}",
        )
        change_set_id = None
        applied_actions: list[dict[str, Any]] = []
        applied_facts: list[dict[str, Any]] = []
        verification: list[dict[str, Any]] = []
        warnings: list[str] = []
        if proposal:
            change_set_id = proposal.record.id
            applied_actions = proposal.foreshadow_actions
            applied_facts = proposal.fact_records
            warnings = proposal.warnings
            await apply_change_set(self.context, proposal.record.id)
            verification = await verify_foreshadow_actions(self.context, applied_actions)
            await persist_foreshadow_verification(self.context, verification)
        else:
            await self.context.write_text(target_path, content.rstrip() + "\n")

        output = {
            "chapter_number": chapter_number,
            "target_path": target_path,
            "characters": len(content),
            "summary": f"第 {chapter_number} 章已写入：{target_path}",
            "prompt_packs": prompt_pack_metadata,
            "context": context_metadata,
            "foreshadow_actions": applied_actions,
            "fact_records": applied_facts,
            "foreshadow_verification": verification,
            "warnings": warnings,
            "change_set_id": change_set_id,
        }
        self.store.update_step(
            run_id,
            step.step_id,
            WorkflowStepUpdate(status="completed", output=output, output_path=target_path, error=None),
        )
        return self.store.advance_to_next_step(run_id, step.step_id)

    async def _run_plan_step(self, run_id: str, step: WorkflowStepRecord) -> WorkflowRunRecord:
        run = self.store.load(run_id)
        self.store.update_step(run_id, step.step_id, WorkflowStepUpdate(status="running"))
        llm = self._llm(step)
        prompt, prompt_pack_metadata = await self._build_plan_prompt(run, step)
        response = await llm.chat(ChatRequest(messages=[{"role": "user", "content": prompt}], stream=False))
        output = {"content": response.text.strip(), "prompt_packs": prompt_pack_metadata}
        self.store.update_step(run_id, step.step_id, WorkflowStepUpdate(status="completed", output=output))
        return self.store.advance_to_next_step(run_id, step.step_id)

    async def _run_draft_step(self, run_id: str, step: WorkflowStepRecord) -> WorkflowRunRecord:
        run = self.store.load(run_id)
        self.store.update_step(run_id, step.step_id, WorkflowStepUpdate(status="running"))
        llm = self._llm(step)
        prompt, prompt_pack_metadata = await self._build_draft_prompt(run, step)
        response = await llm.chat(ChatRequest(messages=[{"role": "user", "content": prompt}], stream=False))
        content, foreshadow_actions, fact_records = self._parse_draft_response(response.text)
        output_path = step.output_path or f"temp/drafts/{run.run_id}.md"
        if output_path.endswith("/"):
            output_path = f"{output_path.rstrip('/')}/{run.run_id}.md"
        if not output_path.startswith("temp/drafts/") or not output_path.endswith(".md"):
            output_path = f"temp/drafts/{run.run_id}.md"
        await self.context.write_text(output_path, content + "\n")
        self.store.update_step(
            run_id,
            step.step_id,
            WorkflowStepUpdate(
                status="completed",
                output={
                    "content": content,
                    "prompt_packs": prompt_pack_metadata,
                    "foreshadow_actions": foreshadow_actions,
                    "fact_records": fact_records,
                },
                output_path=output_path,
            ),
        )
        return self.store.advance_to_next_step(run_id, step.step_id)

    async def _build_plan_prompt(self, run: WorkflowRunRecord, step: WorkflowStepRecord) -> tuple[str, dict[str, Any]]:
        context = self._workflow_context_text(run)
        extra_prompt = self._step_extra_prompt(step)
        prompt_pack_block, prompt_pack_metadata = await self._prompt_pack_block(step, "chapter_plan")
        prompt = (
            "请为长篇小说章节生成可执行的章节计划。\n"
            "要求：输出 Markdown；包含章节目标、场景顺序、人物状态、伏笔处理、风险点；不要直接写正文。\n\n"
            f"工作流标题：{run.title}\n"
            f"任务摘要：{run.input_summary}\n\n"
            f"{extra_prompt}\n\n"
            f"{prompt_pack_block}\n\n"
            f"{context}"
        )
        prompt_pack_metadata["extra_prompt_included"] = bool(extra_prompt.strip())
        prompt_pack_metadata["extra_prompt_chars"] = len(extra_prompt)
        prompt_pack_metadata["prompt_chars"] = len(prompt)
        return prompt, prompt_pack_metadata

    async def _build_draft_prompt(self, run: WorkflowRunRecord, step: WorkflowStepRecord) -> tuple[str, dict[str, Any]]:
        context = self._workflow_context_text(run)
        plan = self._latest_step_output(run, "plan")
        extra_prompt = self._step_extra_prompt(step)
        stage: PromptPackStage = "revision" if step.kind == "revise" else "chapter_draft"
        prompt_pack_block, prompt_pack_metadata = await self._prompt_pack_block(step, stage)
        prompt = (
            "请根据章节计划撰写章节草稿。\n"
            "要求：输出结构化 JSON，对象包含 content（完整 Markdown 正文）、foreshadow_actions（伏笔动作数组）"
            "和 fact_records（本章结束后的长期事实快照）；不要调用工具。"
            "foreshadow_actions 使用 plant、advance、payoff、none；plant 必须包含 title 和 summary，advance/payoff 必须使用已有 foreshadow_id。\n\n"
            "fact_records 最多 12 条，只记录可跨章节复用的身份、状态、关系、位置、持有物、时间点和世界规则；"
            "字段为 category、subject、predicate、value、evidence、certainty，可选 time 和 tags；没有长期事实时返回空数组。\n\n"
            f"工作流标题：{run.title}\n"
            f"任务摘要：{run.input_summary}\n\n"
            f"章节计划：\n{plan or '暂无显式计划，请根据任务摘要和上下文生成草稿。'}\n\n"
            f"{extra_prompt}\n\n"
            f"{prompt_pack_block}\n\n"
            f"{context}"
        )
        prompt_pack_metadata["extra_prompt_included"] = bool(extra_prompt.strip())
        prompt_pack_metadata["extra_prompt_chars"] = len(extra_prompt)
        prompt_pack_metadata["prompt_chars"] = len(prompt)
        return prompt, prompt_pack_metadata

    async def _build_chapter_prompt(
        self,
        run: WorkflowRunRecord,
        step: WorkflowStepRecord,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        chapter_number = self._chapter_number(step)
        volume = normalize_volume(str(step.input.get("volume") or "vol-01"))
        target_characters = max(500, min(int(step.input.get("target_characters") or 3000), 20000))
        requirements = str(step.input.get("requirements") or "").strip()
        query = f"第 {chapter_number} 章 {requirements or run.input_summary}".strip()
        try:
            vector_context = await self.vector_store.query(query, top_k=6)
        except Exception:
            vector_context = []
        try:
            foreshadow_context = await foreshadow_context_for_prompt(self.context, query, limit=6)
        except Exception:
            foreshadow_context = ""

        previous_path = chapter_path(volume, chapter_number - 1) if chapter_number > 1 else ""
        previous_tail = ""
        previous_facts: list[dict[str, Any]] = []
        if previous_path and await self.context.exists(previous_path):
            previous_content = await self.context.read_text(previous_path)
            previous_tail = previous_content[-4000:]
            previous_facts = await load_chapter_facts(self.context, previous_path)

        context_lines: list[str] = []
        for item in vector_context[:6]:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            score = item.get("score")
            content = str(item.get("content") or "")[:700]
            context_lines.append(f"- {path}（{score}）\n{content}")
        prompt_pack_block, prompt_pack_metadata = await self._prompt_pack_block(step, "chapter_draft")
        extra_prompt = self._step_extra_prompt(step)
        prompt = (
            f"请撰写长篇小说第 {chapter_number} 章并保持与项目设定连续。\n"
            f"目标长度约 {target_characters} 个中文字符，可按情节需要小幅浮动。\n"
            "只完成本章，不续写下一章，不输出任务说明或创作分析。\n"
            "输出结构化 JSON，对象包含 content（完整 Markdown 正文）、foreshadow_actions（伏笔动作数组）"
            "和 fact_records（本章结束后的长期事实快照）；不要调用工具。\n"
            "foreshadow_actions 使用 plant、advance、payoff、none；plant 必须包含 title 和 summary，"
            "advance/payoff 必须使用已有 foreshadow_id。\n"
            "fact_records 最多 12 条，仅记录可跨章节复用的事实；字段为 category、subject、predicate、value、"
            "evidence、certainty，可选 time 和 tags。没有长期事实时返回空数组。\n\n"
            f"工作流：{run.title}\n"
            f"总体任务：{run.input_summary}\n"
            f"本章要求：{requirements or '遵循项目大纲与已有设定自然推进。'}\n\n"
            f"前一章正文尾部：\n{previous_tail or '没有可用的前章正文。'}\n\n"
            "前一章长期事实：\n"
            f"{json.dumps(previous_facts, ensure_ascii=False, indent=2) if previous_facts else '没有可用的前章事实。'}\n\n"
            f"相关项目片段：\n{chr(10).join(context_lines) if context_lines else '暂无相关检索片段。'}\n\n"
            f"相关活跃伏笔：\n{foreshadow_context or '暂无相关伏笔。'}\n\n"
            f"{extra_prompt}\n\n"
            f"{prompt_pack_block}"
        )
        prompt_pack_metadata["extra_prompt_included"] = bool(extra_prompt)
        prompt_pack_metadata["extra_prompt_chars"] = len(extra_prompt)
        prompt_pack_metadata["prompt_chars"] = len(prompt)
        context_metadata = {
            "query": query,
            "vector_matches": len(context_lines),
            "foreshadows_included": bool(foreshadow_context),
            "previous_chapter_path": previous_path if previous_tail else None,
            "previous_tail_characters": len(previous_tail),
            "previous_fact_count": len(previous_facts),
        }
        return prompt, prompt_pack_metadata, context_metadata

    def _parse_draft_response(
        self,
        text: str,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]] | None]:
        raw = text.strip()
        candidates = [raw]
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL | re.IGNORECASE)
        if fenced:
            candidates.insert(0, fenced.group(1))
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or not isinstance(data.get("content"), str):
                continue
            actions = data.get("foreshadow_actions")
            facts = data.get("fact_records")
            return (
                data["content"].strip(),
                actions if isinstance(actions, list) else [],
                facts if isinstance(facts, list) else None,
            )
        return raw, [], None

    async def _prompt_pack_block(
        self,
        step: WorkflowStepRecord,
        stage: PromptPackStage,
    ) -> tuple[str, dict[str, Any]]:
        mode = "stage_default"
        if step.prompt_pack_ids:
            mode = "step_selected"
            packs = []
            seen: set[str] = set()
            for pack_id in step.prompt_pack_ids:
                if pack_id in seen:
                    continue
                pack = prompt_pack_store.get(pack_id)
                if pack and pack.content.strip():
                    packs.append(pack)
                    seen.add(pack.id)
        else:
            packs = await enabled_prompt_packs_for_project_stages(self.context, [stage])
        metadata = {
            "mode": mode,
            "stage": stage,
            "count": len(packs),
            "ids": [pack.id for pack in packs],
            "names": [pack.name for pack in packs],
            "categories": [pack.category for pack in packs],
        }
        return render_prompt_pack_block_from_packs(packs), metadata

    def _workflow_context_text(self, run: WorkflowRunRecord) -> str:
        context_step = next((step for step in run.steps if step.kind == "context" and step.output), None)
        if not context_step:
            return "项目上下文：暂无自动检索结果。"
        output = context_step.output
        lines: list[str] = ["项目上下文："]
        vector_context = output.get("vector_context") if isinstance(output, dict) else None
        if isinstance(vector_context, list) and vector_context:
            lines.append("相关片段：")
            for item in vector_context[:6]:
                if not isinstance(item, dict):
                    continue
                lines.append(f"- {item.get('path')}（{item.get('score')}）\n{item.get('content')}")
        foreshadow_context = output.get("foreshadow_context") if isinstance(output, dict) else ""
        if foreshadow_context:
            lines.append(f"相关伏笔：\n{foreshadow_context}")
        return "\n\n".join(lines)

    def _latest_step_output(self, run: WorkflowRunRecord, kind: str) -> str:
        for step in reversed(run.steps):
            if step.kind == kind and isinstance(step.output, dict):
                content = step.output.get("content")
                if content:
                    return str(content)
        return ""

    def _latest_draft_path(self, run: WorkflowRunRecord) -> str:
        for step in reversed(run.steps):
            if step.kind in {"draft", "revise"} and step.output_path:
                return step.output_path
        return ""

    def _step_extra_prompt(self, step: WorkflowStepRecord | None) -> str:
        if not step:
            return ""
        value = step.input.get("extra_prompt") if isinstance(step.input, dict) else ""
        text = str(value or "").strip()
        if not text:
            return ""
        return f"本步骤额外要求：\n{text}"

    def _chapter_number(self, step: WorkflowStepRecord) -> int:
        try:
            value = int(step.input.get("chapter_number"))
        except (TypeError, ValueError) as exc:
            raise ValueError("连续章节步骤缺少有效章节号") from exc
        if value < 1 or value > 9999:
            raise ValueError("连续章节步骤的章节号超出范围")
        return value

    def _current_or_next_step(self, run: WorkflowRunRecord) -> WorkflowStepRecord | None:
        if run.current_step_id:
            step = self._step_by_id(run, run.current_step_id)
            if step.status not in {"completed", "skipped"}:
                return step
        for step in run.steps:
            if step.status in {"pending", "running", "waiting_user"}:
                return step
        return None

    def _step_by_id(self, run: WorkflowRunRecord, step_id: str) -> WorkflowStepRecord:
        for step in run.steps:
            if step.step_id == step_id:
                return step
        raise ValueError(f"Workflow step not found: {step_id}")

    def _llm(self, step: WorkflowStepRecord) -> LLMClient:
        preset = preset_store.get(step.preset_id) if step.preset_id else None
        if preset:
            return create_llm_client_from_preset(preset.llm)
        return create_llm_client(settings)
