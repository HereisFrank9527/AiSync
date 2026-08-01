from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.agent import discard_cached_agents_for_project
from app.core.config import settings
from app.core.system_rules import (
    ProjectSystemRules,
    ProjectSystemRulesUpdate,
    load_project_system_rules,
    save_project_system_rules,
)
from app.projects.context import ProjectContext

router = APIRouter(prefix="/system-rules", tags=["system-rules"])


def project_context(project_path: str) -> ProjectContext:
    return ProjectContext(settings.project_path(project_path=project_path))


@router.get("")
async def get_project_system_rules(project_path: str = Query(...)) -> ProjectSystemRules:
    return await load_project_system_rules(project_context(project_path))


@router.put("")
async def update_project_system_rules(body: ProjectSystemRulesUpdate) -> ProjectSystemRules:
    context = project_context(body.project_path)
    saved = await save_project_system_rules(
        context,
        body.mode,
        body.content,
    )
    discard_cached_agents_for_project(str(context.root))
    return saved
