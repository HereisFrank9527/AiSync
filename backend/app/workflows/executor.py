from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.prompt_pack_rendering import enabled_prompt_packs_for_project_stages, render_prompt_pack_block_from_packs
from app.core.presets import preset_store
from app.llm.factory import create_llm_client, create_llm_client_from_preset
from app.llm.types import ChatRequest, LLMClient
from app.projects.context import ProjectContext
from app.projects.foreshadows import foreshadow_context_for_prompt
from app.vector.store import ProjectVectorStore
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

    async def _run_plan_step(self, run_id: str, step: WorkflowStepRecord) -> WorkflowRunRecord:
        run = self.store.load(run_id)
        self.store.update_step(run_id, step.step_id, WorkflowStepUpdate(status="running"))
        llm = self._llm(step)
        prompt = await self._build_plan_prompt(run)
        response = await llm.chat(ChatRequest(messages=[{"role": "user", "content": prompt}], stream=False))
        output = {"content": response.text.strip()}
        self.store.update_step(run_id, step.step_id, WorkflowStepUpdate(status="completed", output=output))
        return self.store.advance_to_next_step(run_id, step.step_id)

    async def _run_draft_step(self, run_id: str, step: WorkflowStepRecord) -> WorkflowRunRecord:
        run = self.store.load(run_id)
        self.store.update_step(run_id, step.step_id, WorkflowStepUpdate(status="running"))
        llm = self._llm(step)
        prompt = await self._build_draft_prompt(run)
        response = await llm.chat(ChatRequest(messages=[{"role": "user", "content": prompt}], stream=False))
        content = response.text.strip()
        output_path = step.output_path or f"temp/drafts/{run.run_id}.md"
        if output_path.endswith("/"):
            output_path = f"{output_path.rstrip('/')}/{run.run_id}.md"
        if not output_path.startswith("temp/drafts/") or not output_path.endswith(".md"):
            output_path = f"temp/drafts/{run.run_id}.md"
        await self.context.write_text(output_path, content + "\n")
        self.store.update_step(
            run_id,
            step.step_id,
            WorkflowStepUpdate(status="completed", output={"content": content}, output_path=output_path),
        )
        return self.store.advance_to_next_step(run_id, step.step_id)

    async def _build_plan_prompt(self, run: WorkflowRunRecord) -> str:
        context = self._workflow_context_text(run)
        prompt_pack_block = await self._prompt_pack_block("chapter_plan")
        return (
            "请为长篇小说章节生成可执行的章节计划。\n"
            "要求：输出 Markdown；包含章节目标、场景顺序、人物状态、伏笔处理、风险点；不要直接写正文。\n\n"
            f"工作流标题：{run.title}\n"
            f"任务摘要：{run.input_summary}\n\n"
            f"{prompt_pack_block}\n\n"
            f"{context}"
        )

    async def _build_draft_prompt(self, run: WorkflowRunRecord) -> str:
        context = self._workflow_context_text(run)
        plan = self._latest_step_output(run, "plan")
        prompt_pack_block = await self._prompt_pack_block("chapter_draft")
        return (
            "请根据章节计划撰写章节草稿。\n"
            "要求：输出完整 Markdown 正文；不要调用工具；不要写解释；如果信息不足，用自然叙事补足但不要改写既有项目事实。\n\n"
            f"工作流标题：{run.title}\n"
            f"任务摘要：{run.input_summary}\n\n"
            f"章节计划：\n{plan or '暂无显式计划，请根据任务摘要和上下文生成草稿。'}\n\n"
            f"{prompt_pack_block}\n\n"
            f"{context}"
        )

    async def _prompt_pack_block(self, stage: str) -> str:
        packs = await enabled_prompt_packs_for_project_stages(self.context, [stage])  # type: ignore[list-item]
        return render_prompt_pack_block_from_packs(packs)

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
