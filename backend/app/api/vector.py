from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.config import settings
from app.projects.context import ProjectContext
from app.vector.store import ProjectVectorStore

router = APIRouter(prefix="/vector", tags=["vector"])


class VectorSearchRequest(BaseModel):
    project_path: str | None = None
    query: str
    collections: list[str] | None = None
    top_k: int = 10


def project_context(project_path: str | None) -> ProjectContext:
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path is required")
    return ProjectContext(settings.project_path(project_path=project_path))


@router.post("/rebuild")
async def rebuild_vector_index(project_path: str = Query(...)) -> dict[str, Any]:
    store = ProjectVectorStore(project_context(project_path))
    index = await store.rebuild()
    return {
        "status": "rebuilt",
        "files": len(index.get("files", [])),
        "chunks": len(index.get("chunks", [])),
    }


@router.get("/status")
async def vector_index_status(project_path: str = Query(...)) -> dict[str, Any]:
    store = ProjectVectorStore(project_context(project_path))
    return await store.status()


@router.post("/search")
async def search_vector_index(request: VectorSearchRequest) -> dict[str, Any]:
    store = ProjectVectorStore(project_context(request.project_path))
    results = await store.query(
        request.query,
        collections=request.collections,
        top_k=max(1, min(request.top_k, 50)),
    )
    return {"items": results}
