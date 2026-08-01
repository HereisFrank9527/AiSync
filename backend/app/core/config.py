from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AiSync Backend"
    projects_root: str = str(Path.home() / ".aisync" / "projects")

    llm_provider: Literal["anthropic", "openai", "custom"] = "anthropic"
    llm_api_key: str | None = None
    llm_api_key_env: str = "ANTHROPIC_API_KEY"
    llm_api_base: str | None = None
    llm_model_name: str = "claude-opus-4-7"
    llm_max_tokens: int = 16000
    llm_request_timeout: int = 120
    llm_context_window: Literal["economy", "standard", "long", "maximum"] = "standard"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    llm_enable_thinking: bool = True
    llm_prompt_cache: bool = True
    llm_native_web_search: bool = False
    web_search_provider: Literal["auto", "tavily", "bing", "native"] = "auto"
    tavily_api_key: str | None = None
    tavily_api_key_env: str = "TAVILY_API_KEY"
    tavily_search_depth: Literal["basic", "advanced"] = "basic"
    web_search_max_results: int = Field(default=5, ge=1, le=20)
    tavily_include_raw_content: bool = False
    embedding_model_name: str | None = None
    vector_backend: Literal["local", "chroma"] = "local"
    chroma_persist_path: str = ".vectordb/chroma"
    chroma_collection_name: str = "aisync_chunks"

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:1420",
            "http://localhost:5173",
        ]
    )

    def project_path(self, project_id: str | None = None, project_path: str | None = None) -> Path:
        if project_path:
            return Path(project_path).expanduser().resolve()
        if not project_id:
            project_id = "demo"
        return (Path(self.projects_root) / project_id).resolve()


settings = Settings()
