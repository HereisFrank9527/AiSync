from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AiSync Backend"
    projects_root: str = "./projects"

    llm_provider: Literal["anthropic", "openai", "custom"] = "anthropic"
    llm_api_key: str | None = None
    llm_api_key_env: str = "ANTHROPIC_API_KEY"
    llm_api_base: str | None = None
    llm_model_name: str = "claude-opus-4-7"
    llm_max_tokens: int = 16000
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    llm_enable_thinking: bool = True
    llm_prompt_cache: bool = True

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:1420", "http://localhost:5173"])


settings = Settings()
