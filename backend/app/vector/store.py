from __future__ import annotations

from app.projects.context import ProjectContext


class NullVectorStore:
    async def query(self, text: str, collections: list[str] | None = None, top_k: int = 10) -> list[dict]:
        return []

    async def index_file(self, file_path: str) -> None:
        return None

    async def check_consistency(self, new_content: str) -> list[dict]:
        return []


class ProjectVectorStore(NullVectorStore):
    def __init__(self, context: ProjectContext) -> None:
        self.context = context
