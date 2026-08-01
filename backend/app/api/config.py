from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(prefix="/config", tags=["config"])

# Fields that require LLM client recreation when changed.
_REBUILD_FIELDS = {"llm_provider", "llm_api_key_env", "llm_api_base", "llm_native_web_search"}


class LLMConfigResponse(BaseModel):
    llm_provider: str
    llm_api_key_env: str
    llm_api_base: str | None
    llm_model_name: str
    llm_max_tokens: int
    llm_request_timeout: int
    llm_context_window: str
    llm_effort: str
    llm_enable_thinking: bool
    llm_prompt_cache: bool
    llm_native_web_search: bool


class LLMConfigUpdate(BaseModel):
    llm_provider: Literal["anthropic", "openai", "custom"] | None = None
    llm_api_key_env: str | None = None
    llm_api_base: str | None = None
    llm_model_name: str | None = None
    llm_max_tokens: int | None = None
    llm_request_timeout: int | None = None
    llm_context_window: Literal["economy", "standard", "long", "maximum"] | None = None
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    llm_enable_thinking: bool | None = None
    llm_prompt_cache: bool | None = None
    llm_native_web_search: bool | None = None


def _current_llm_config() -> LLMConfigResponse:
    return LLMConfigResponse(
        llm_provider=settings.llm_provider,
        llm_api_key_env=settings.llm_api_key_env,
        llm_api_base=settings.llm_api_base,
        llm_model_name=settings.llm_model_name,
        llm_max_tokens=settings.llm_max_tokens,
        llm_request_timeout=settings.llm_request_timeout,
        llm_context_window=settings.llm_context_window,
        llm_effort=settings.llm_effort,
        llm_enable_thinking=settings.llm_enable_thinking,
        llm_prompt_cache=settings.llm_prompt_cache,
        llm_native_web_search=settings.llm_native_web_search,
    )


def _rebuild_all_agent_clients() -> int:
    """Recreate LLM clients on all cached agents. Returns count of rebuilt agents."""
    from app.api.agent import active_agents
    from app.llm.factory import create_llm_client

    count = 0
    for agent in active_agents.values():
        agent.llm = create_llm_client(settings)
        count += 1
    return count


@router.get("/llm")
async def get_llm_config() -> LLMConfigResponse:
    return _current_llm_config()


@router.put("/llm")
async def update_llm_config(body: LLMConfigUpdate) -> dict[str, Any]:
    provided = body.model_fields_set
    if not provided:
        return {"config": _current_llm_config(), "changed": [], "agents_rebuilt": 0}

    changed: list[str] = []
    needs_rebuild = False

    for field_name in provided:
        new_value = getattr(body, field_name)
        old_value = getattr(settings, field_name)
        if new_value != old_value:
            setattr(settings, field_name, new_value)
            changed.append(field_name)
            if field_name in _REBUILD_FIELDS:
                needs_rebuild = True

    agents_rebuilt = 0
    if needs_rebuild:
        agents_rebuilt = _rebuild_all_agent_clients()

    return {
        "config": _current_llm_config(),
        "changed": changed,
        "agents_rebuilt": agents_rebuilt,
    }
