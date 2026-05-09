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
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    llm_enable_thinking: bool = True
    llm_prompt_cache: bool = True
    embedding_model_name: str | None = None
    vector_backend: Literal["local", "chroma"] = "local"
    chroma_persist_path: str = ".vectordb/chroma"
    chroma_collection_name: str = "aisync_chunks"

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:1420",
            "http://localhost:5173",
            "tauri://localhost",
            "http://tauri.localhost",
        ]
    )

    def project_path(self, project_id: str | None = None, project_path: str | None = None) -> Path:
        if project_path:
            return Path(project_path).expanduser().resolve()
        if not project_id:
            project_id = "demo"
        return (Path(self.projects_root) / project_id).resolve()


settings = Settings()
