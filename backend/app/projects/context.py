from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import yaml


class ProjectContext:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self._lock = asyncio.Lock()

    def resolve_path(self, relative_path: str | Path) -> Path:
        path = (self.root / relative_path).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError(f"Path escapes project root: {relative_path}")
        return path

    async def read_text(self, relative_path: str | Path) -> str:
        path = self.resolve_path(relative_path)
        async with self._lock:
            return await asyncio.to_thread(path.read_text, encoding="utf-8")

    async def write_text(self, relative_path: str | Path, content: str) -> None:
        path = self.resolve_path(relative_path)
        async with self._lock:
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_text, content, encoding="utf-8")

    async def move_file(self, source: str | Path, target: str | Path) -> None:
        source_path = self.resolve_path(source)
        target_path = self.resolve_path(target)
        async with self._lock:
            if not await asyncio.to_thread(source_path.is_file):
                raise FileNotFoundError(str(source))
            if await asyncio.to_thread(target_path.exists):
                raise FileExistsError(str(target))
            await asyncio.to_thread(target_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(source_path.rename, target_path)

    async def delete_file(self, relative_path: str | Path) -> None:
        path = self.resolve_path(relative_path)
        async with self._lock:
            if not await asyncio.to_thread(path.is_file):
                raise FileNotFoundError(str(relative_path))
            await asyncio.to_thread(path.unlink)

    async def read_json(self, relative_path: str | Path) -> Any:
        return json.loads(await self.read_text(relative_path))

    async def write_json(self, relative_path: str | Path, data: Any) -> None:
        content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        await self.write_text(relative_path, content)

    async def read_yaml(self, relative_path: str | Path) -> Any:
        return yaml.safe_load(await self.read_text(relative_path))

    async def write_yaml(self, relative_path: str | Path, data: Any) -> None:
        content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        await self.write_text(relative_path, content)

    async def exists(self, relative_path: str | Path) -> bool:
        path = self.resolve_path(relative_path)
        async with self._lock:
            return await asyncio.to_thread(path.exists)

    async def ensure_dir(self, relative_path: str | Path) -> None:
        """Create directory if it doesn't exist."""
        path = self.resolve_path(relative_path)
        async with self._lock:
            await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)

    async def list_files(self, relative_dir: str | Path = ".") -> list[str]:
        directory = self.resolve_path(relative_dir)
        async with self._lock:
            def scan() -> list[str]:
                if not directory.exists():
                    return []
                return [str(path.relative_to(self.root)) for path in directory.rglob("*") if path.is_file()]

            return await asyncio.to_thread(scan)

    async def init_structure(self) -> list[str]:
        """Initialize the standard project directory structure. Returns list of created paths."""
        created: list[str] = []

        dirs = [
            "world",
            "characters",
            "plot/arcs",
            "chapters/vol-01",
            "assets",
            "temp/inbox",
            "temp/drafts",
            "temp/exports",
            "temp/notes",
            ".aisync/conversations",
        ]
        for d in dirs:
            await self.ensure_dir(d)

        initial_files: dict[str, str] = {
            "project.yaml": (
                "name: \"未命名项目\"\n"
                "model:\n"
                "  provider: anthropic\n"
                "  api_base: null\n"
                "  api_key_env: \"\"\n"
                "  model_name: claude-sonnet-4-6\n"
                "  parameters:\n"
                "    temperature: 0.7\n"
                "    max_tokens: 8192\n"
            ),
            "world/overview.md": "# 世界观概述\n\n",
            "world/magic-system.md": "# 力量体系\n\n",
            "world/geography.md": "# 地理\n\n",
            "world/history.md": "# 历史\n\n",
            "world/rules.yaml": "# 世界规则\n",
            "characters/index.yaml": "schema_version: 1\ncharacters: []\n",
            "characters/relationships.json": "[]\n",
            "plot/outline.md": "# 大纲\n\n",
            "plot/timeline.json": "[]\n",
            "assets/name-dictionary.yaml": "# 命名词典\n",
            "assets/style-guide.md": "# 风格指南\n\n",
            "temp/.aisync-temp.json": json.dumps(
                {
                    "version": 1,
                    "items": [],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            "operation.log": "",
        }

        for rel_path, content in initial_files.items():
            if not await self.exists(rel_path):
                await self.write_text(rel_path, content)
                created.append(rel_path)

        return created
