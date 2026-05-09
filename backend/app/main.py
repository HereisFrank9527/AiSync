from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent import router as agent_router
from app.api.config import router as config_router
from app.api.conversations import router as conversations_router
from app.api.presets import router as presets_router
from app.api.projects import router as projects_router
from app.api.story import router as story_router
from app.api.tools import router as tools_router
from app.api.vector import router as vector_router
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(projects_router, prefix="/api")
    app.include_router(agent_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(conversations_router, prefix="/api")
    app.include_router(presets_router, prefix="/api")
    app.include_router(tools_router, prefix="/api")
    app.include_router(vector_router, prefix="/api")
    app.include_router(story_router, prefix="/api")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
