from __future__ import annotations

from app.core.config import Settings
from app.core.presets import LLMParams
from app.llm.anthropic_client import AnthropicLLMClient
from app.llm.openai_client import OpenAICompatibleLLMClient
from app.llm.types import LLMClient


def create_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "anthropic":
        return AnthropicLLMClient(settings)
    if settings.llm_provider in {"openai", "custom"}:
        return OpenAICompatibleLLMClient(settings)
    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")


def settings_from_preset(llm: LLMParams, base: Settings | None = None) -> Settings:
    """Build a Settings object with LLM fields overridden by preset params."""
    from app.core.config import settings as default_settings

    src = base or default_settings
    overrides = {
        "llm_provider": llm.provider,
        "llm_api_key": llm.api_key,
        "llm_api_key_env": llm.api_key_env,
        "llm_api_base": llm.api_base,
        "llm_model_name": llm.model_name,
        "llm_max_tokens": llm.max_tokens,
        "llm_effort": llm.effort,
        "llm_enable_thinking": llm.enable_thinking,
        "llm_prompt_cache": llm.prompt_cache,
    }
    return src.model_copy(update=overrides)


def create_llm_client_from_preset(llm: LLMParams) -> LLMClient:
    """Create an LLM client configured by preset LLM params."""
    s = settings_from_preset(llm)
    return create_llm_client(s)
