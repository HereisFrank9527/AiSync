"""Preset data models and JSON-file storage layer.

A *preset* bundles LLM parameters + agent behaviour into a named profile
that can be switched at runtime without restarting the backend.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Data models ──────────────────────────────────────────────────────


class LLMParams(BaseModel):
    provider: Literal["anthropic", "openai", "custom"] = "anthropic"
    api_key: str | None = None
    api_key_env: str = "ANTHROPIC_API_KEY"
    api_base: str | None = None
    model_name: str = "claude-opus-4-7"
    max_tokens: int = 16000
    request_timeout: int = 120
    context_window: Literal["economy", "standard", "long", "maximum"] = "standard"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    enable_thinking: bool = True
    prompt_cache: bool = True
    native_web_search: bool = False
    web_search_provider: Literal["auto", "tavily", "bing", "native"] = "auto"
    tavily_api_key: str | None = None
    tavily_api_key_env: str = "TAVILY_API_KEY"
    tavily_search_depth: Literal["basic", "advanced"] = "basic"
    web_search_max_results: int = Field(default=5, ge=1, le=20)
    tavily_include_raw_content: bool = False


class AgentBehavior(BaseModel):
    system_prompt: str | None = None
    enabled_tools: list[str] | None = None  # None = all tools


class Preset(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    llm: LLMParams = Field(default_factory=LLMParams)
    behavior: AgentBehavior = Field(default_factory=AgentBehavior)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── API request / response helpers ───────────────────────────────────


class PresetCreate(BaseModel):
    name: str
    llm: LLMParams | None = None
    behavior: AgentBehavior | None = None


class PresetCopy(BaseModel):
    name: str | None = None


class PresetUpdate(BaseModel):
    name: str | None = None
    llm: LLMParams | None = None
    behavior: AgentBehavior | None = None


# ── Built-in presets (read-only) ─────────────────────────────────────

BUILTIN_PRESETS: list[Preset] = [
    Preset(
        id="default",
        name="默认",
        llm=LLMParams(),
        behavior=AgentBehavior(),
    ),
]


# ── JSON file storage ────────────────────────────────────────────────

_DEFAULT_STORE_PATH = Path.home() / ".aisync" / "presets.json"


class PresetStore:
    """Simple JSON-file backed preset storage."""

    def __init__(self, path: Path = _DEFAULT_STORE_PATH) -> None:
        self._path = path
        self._cache: dict[str, Preset] = {}
        self._load()

    def list_all(self) -> list[Preset]:
        return [*BUILTIN_PRESETS, *self._cache.values()]

    def get(self, preset_id: str) -> Preset | None:
        for bp in BUILTIN_PRESETS:
            if bp.id == preset_id:
                return bp
        return self._cache.get(preset_id)

    def create(self, data: PresetCreate) -> Preset:
        preset = Preset(
            name=data.name,
            llm=data.llm or LLMParams(),
            behavior=data.behavior or AgentBehavior(),
        )
        self._cache[preset.id] = preset
        self._save()
        return preset

    def copy(self, preset_id: str, name: str | None = None) -> Preset | None:
        source = self.get(preset_id)
        if not source:
            return None
        preset = Preset(
            name=name or f"{source.name} 副本",
            llm=source.llm.model_copy(deep=True),
            behavior=source.behavior.model_copy(deep=True),
        )
        self._cache[preset.id] = preset
        self._save()
        return preset

    def update(self, preset_id: str, data: PresetUpdate) -> Preset | None:
        for bp in BUILTIN_PRESETS:
            if bp.id == preset_id:
                return None
        preset = self._cache.get(preset_id)
        if not preset:
            return None
        if data.name is not None:
            preset.name = data.name
        if data.llm is not None:
            preset.llm = data.llm
        if data.behavior is not None:
            preset.behavior = data.behavior
        preset.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()
        return preset

    def delete(self, preset_id: str) -> bool:
        if preset_id in {bp.id for bp in BUILTIN_PRESETS}:
            return False
        if preset_id not in self._cache:
            return False
        del self._cache[preset_id]
        self._save()
        return True

    # ── persistence ──────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for item in raw:
                preset = Preset.model_validate(item)
                self._cache[preset.id] = preset
        except json.JSONDecodeError as exc:
            logger.warning("presets.json is corrupted, starting fresh: %s", exc)
        except Exception as exc:
            logger.warning("Failed to load presets: %s", exc)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [p.model_dump() for p in self._cache.values()]
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# Module-level singleton
preset_store = PresetStore()
