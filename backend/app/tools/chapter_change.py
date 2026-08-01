from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.change_sets import ChangeSetRecord, ProposedFileChange, create_change_set
from app.projects.context import ProjectContext
from app.projects.facts import chapter_fact_document, chapter_fact_path, normalize_fact_records
from app.projects.foreshadows import FORESHADOW_PATH, apply_foreshadow_actions, load_foreshadows


@dataclass(slots=True)
class ChapterChangeProposal:
    record: ChangeSetRecord
    foreshadow_actions: list[dict[str, Any]]
    fact_records: list[dict[str, Any]]
    warnings: list[str]


async def create_chapter_change_set(
    context: ProjectContext,
    *,
    path: str,
    content: str,
    actions: list[dict[str, Any]],
    fact_records: list[Any] | None,
    title: str,
    force_proposal: bool = False,
) -> ChapterChangeProposal | None:
    meaningful_actions = [
        item
        for item in actions
        if str(item.get("action") or "none").strip().lower() != "none"
    ]
    fact_path = chapter_fact_path(path)
    facts = normalize_fact_records(fact_records, path) if fact_records is not None else []
    update_facts = fact_records is not None and (bool(facts) or await context.exists(fact_path))
    if not meaningful_actions and not update_facts and not force_proposal:
        return None

    applied_actions: list[dict[str, Any]] = []
    action_warnings: list[str] = []
    changes = [ProposedFileChange(path=path, new_content=content, reason="写入章节正文")]
    if meaningful_actions:
        current_items = await load_foreshadows(context)
        updated_items = current_items
        for index, action in enumerate(meaningful_actions, start=1):
            try:
                updated_items, applied = apply_foreshadow_actions(updated_items, [action], path)
            except ValueError as exc:
                action_name = str(action.get("action") or "unknown").strip() or "unknown"
                action_warnings.append(f"伏笔动作 {index}（{action_name}）已跳过：{exc}")
                continue
            applied_actions.extend(applied)
        if applied_actions:
            changes.append(
                ProposedFileChange(
                    path=FORESHADOW_PATH,
                    new_content=json.dumps({"items": updated_items}, ensure_ascii=False, indent=2) + "\n",
                    reason="登记本章伏笔动作：" + ", ".join(item["title"] for item in applied_actions),
                )
            )
    if update_facts:
        changes.append(
            ProposedFileChange(
                path=fact_path,
                new_content=json.dumps(chapter_fact_document(path, facts), ensure_ascii=False, indent=2) + "\n",
                reason=f"更新本章长期事实快照：{len(facts)} 条",
            )
        )
    record = await create_change_set(
        context,
        title=title,
        summary=(
            "章节正文、长期事实快照和有效伏笔动作将一起写入，应用前可在差异预览中确认。"
            + (f" {len(action_warnings)} 条无效伏笔动作已跳过，不影响章节正文。" if action_warnings else "")
        ),
        changes=changes,
    )
    return ChapterChangeProposal(
        record=record,
        foreshadow_actions=applied_actions,
        fact_records=facts,
        warnings=action_warnings,
    )
