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

    async def list_files(self, relative_dir: str | Path = ".") -> list[str]:
        directory = self.resolve_path(relative_dir)
        async with self._lock:
            def scan() -> list[str]:
                if not directory.exists():
                    return []
                return [str(path.relative_to(self.root)) for path in directory.rglob("*") if path.is_file()]

            return await asyncio.to_thread(scan)
