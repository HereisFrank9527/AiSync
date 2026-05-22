from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


PromptPackCategory = Literal["style", "writing", "planning", "revision", "check", "special", "custom"]
PromptPackScope = Literal["global", "project"]
PromptPackStage = Literal["chat", "chapter_plan", "chapter_draft", "revision", "check", "special"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PromptPack(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    category: PromptPackCategory = "custom"
    scope: PromptPackScope = "global"
    stages: list[PromptPackStage] = Field(default_factory=lambda: ["chat"])
    content: str = ""
    enabled: bool = True
    description: str = ""
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class PromptPackCreate(BaseModel):
    name: str
    category: PromptPackCategory = "custom"
    scope: PromptPackScope = "global"
    stages: list[PromptPackStage] = Field(default_factory=lambda: ["chat"])
    content: str = ""
    enabled: bool = True
    description: str = ""


class PromptPackUpdate(BaseModel):
    name: str | None = None
    category: PromptPackCategory | None = None
    scope: PromptPackScope | None = None
    stages: list[PromptPackStage] | None = None
    content: str | None = None
    enabled: bool | None = None
    description: str | None = None


class PromptPackCopy(BaseModel):
    name: str | None = None


_DEFAULT_STORE_PATH = Path.home() / ".aisync" / "prompt_packs.json"


class PromptPackStore:
    def __init__(self, path: Path = _DEFAULT_STORE_PATH) -> None:
        self._path = path
        self._cache: dict[str, PromptPack] = {}
        self._load()

    def list_all(self) -> list[PromptPack]:
        return sorted(self._cache.values(), key=lambda item: (item.category, item.name))

    def enabled_for_stage(self, stage: PromptPackStage) -> list[PromptPack]:
        return [
            pack
            for pack in self.list_all()
            if pack.enabled and stage in pack.stages and pack.content.strip()
        ]

    def get(self, pack_id: str) -> PromptPack | None:
        return self._cache.get(pack_id)

    def create(self, data: PromptPackCreate) -> PromptPack:
        pack = PromptPack(
            name=data.name.strip() or "未命名提示词",
            category=data.category,
            scope=data.scope,
            stages=self._normalize_stages(data.stages),
            content=data.content,
            enabled=data.enabled,
            description=data.description,
        )
        self._cache[pack.id] = pack
        self._save()
        return pack

    def copy(self, pack_id: str, name: str | None = None) -> PromptPack | None:
        source = self.get(pack_id)
        if not source:
            return None
        pack = PromptPack(
            name=(name or f"{source.name} 副本").strip(),
            category=source.category,
            scope=source.scope,
            stages=list(source.stages),
            content=source.content,
            enabled=source.enabled,
            description=source.description,
        )
        self._cache[pack.id] = pack
        self._save()
        return pack

    def update(self, pack_id: str, data: PromptPackUpdate) -> PromptPack | None:
        pack = self._cache.get(pack_id)
        if not pack:
            return None
        if data.name is not None:
            pack.name = data.name.strip() or pack.name
        if data.category is not None:
            pack.category = data.category
        if data.scope is not None:
            pack.scope = data.scope
        if data.stages is not None:
            pack.stages = self._normalize_stages(data.stages)
        if data.content is not None:
            pack.content = data.content
        if data.enabled is not None:
            pack.enabled = data.enabled
        if data.description is not None:
            pack.description = data.description
        pack.updated_at = utc_now()
        self._save()
        return pack

    def delete(self, pack_id: str) -> bool:
        if pack_id not in self._cache:
            return False
        del self._cache[pack_id]
        self._save()
        return True

    def _normalize_stages(self, stages: list[PromptPackStage]) -> list[PromptPackStage]:
        unique = []
        for stage in stages or ["chat"]:
            if stage not in unique:
                unique.append(stage)
        return unique or ["chat"]

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for item in raw:
                pack = PromptPack.model_validate(item)
                self._cache[pack.id] = pack
        except json.JSONDecodeError as exc:
            logger.warning("prompt_packs.json is corrupted, starting fresh: %s", exc)
        except Exception as exc:
            logger.warning("Failed to load prompt packs: %s", exc)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [pack.model_dump() for pack in self._cache.values()]
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


prompt_pack_store = PromptPackStore()
