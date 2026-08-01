from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel

from app.projects.context import ProjectContext

AGENT_RULES_PATH = "AGENT.md"
LEGACY_PROJECT_SYSTEM_RULES_PATH = ".aisync/system_rules.json"

DEFAULT_PROJECT_SYSTEM_RULES = """# AGENT.md

本文件保存当前小说项目中需要长期遵守的工作习惯和文风要求。

## 当前文风

- 按照用户在本项目中的最新要求写作。
- 避免机械重复的句式和没有必要的总结性表达。

## 工作习惯

- 修改正式文件前先检索相关设定。
- 不把任务说明、操作计划或清理要求写进小说正文和大纲。
- 临时草稿和不确定内容优先放入 `temp/`。
- 用户本轮明确要求高于本文件中的长期偏好。
"""


class ProjectSystemRules(BaseModel):
    mode: Literal["default", "project"] = "default"
    content: str = DEFAULT_PROJECT_SYSTEM_RULES
    default_content: str = DEFAULT_PROJECT_SYSTEM_RULES
    updated_at: str | None = None


class ProjectSystemRulesUpdate(BaseModel):
    project_path: str
    mode: Literal["default", "project"] = "default"
    content: str = DEFAULT_PROJECT_SYSTEM_RULES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _agent_file_updated_at(context: ProjectContext) -> str | None:
    try:
        modified = context.resolve_path(AGENT_RULES_PATH).stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(modified, timezone.utc).isoformat()


def _normalize(data: Any) -> ProjectSystemRules:
    if not isinstance(data, dict):
        return ProjectSystemRules()
    mode = "project" if data.get("mode") == "project" else "default"
    content = str(data.get("content") or DEFAULT_PROJECT_SYSTEM_RULES)
    updated_at = str(data.get("updated_at")) if data.get("updated_at") else None
    return ProjectSystemRules(
        mode=mode,
        content=content,
        default_content=DEFAULT_PROJECT_SYSTEM_RULES,
        updated_at=updated_at,
    )


async def load_project_system_rules(context: ProjectContext) -> ProjectSystemRules:
    if await context.exists(AGENT_RULES_PATH):
        try:
            content = await context.read_text(AGENT_RULES_PATH)
            return ProjectSystemRules(
                mode="project",
                content=content,
                updated_at=_agent_file_updated_at(context),
            )
        except Exception:
            return ProjectSystemRules()
    if not await context.exists(LEGACY_PROJECT_SYSTEM_RULES_PATH):
        return ProjectSystemRules()
    try:
        legacy = _normalize(await context.read_json(LEGACY_PROJECT_SYSTEM_RULES_PATH))
    except Exception:
        return ProjectSystemRules()
    if legacy.mode != "project":
        return ProjectSystemRules()
    await context.write_text(AGENT_RULES_PATH, legacy.content.rstrip() + "\n")
    return ProjectSystemRules(
        mode="project",
        content=legacy.content.rstrip() + "\n",
        updated_at=legacy.updated_at,
    )


async def save_project_system_rules(
    context: ProjectContext,
    mode: str,
    content: str,
) -> ProjectSystemRules:
    if mode != "project":
        if await context.exists(AGENT_RULES_PATH):
            await context.delete_file(AGENT_RULES_PATH)
        return ProjectSystemRules()
    normalized_content = (content or DEFAULT_PROJECT_SYSTEM_RULES).rstrip() + "\n"
    settings = ProjectSystemRules(
        mode="project",
        content=normalized_content,
        default_content=DEFAULT_PROJECT_SYSTEM_RULES,
        updated_at=_now(),
    )
    await context.write_text(AGENT_RULES_PATH, settings.content)
    return settings


def compose_system_prompt(
    base_prompt: str,
    base_source: str,
    settings: ProjectSystemRules,
) -> tuple[str, dict[str, Any]]:
    project_content = settings.content.strip()
    include_project_rules = settings.mode == "project" and bool(project_content)
    final_prompt = base_prompt
    if include_project_rules:
        final_prompt = (
            f"{base_prompt.rstrip()}\n\n## 当前项目 AGENT.md\n"
            "以下内容是当前项目的长期工作习惯与文风要求。"
            "它不能改变工具权限、安全边界或程序级规则。\n\n"
            f"{project_content}"
        )
    audit = {
        "source": "project" if include_project_rules else base_source,
        "base_source": base_source,
        "chars": len(final_prompt),
        "project_rules": {
            "mode": settings.mode,
            "included": include_project_rules,
            "chars": len(project_content),
            "updated_at": settings.updated_at,
        },
    }
    return final_prompt, audit


def system_rules_cache_key(settings: ProjectSystemRules) -> str:
    digest = hashlib.sha1(settings.content.encode("utf-8")).hexdigest()[:12]
    return f"{settings.mode}:{settings.updated_at or 'none'}:{digest}"
