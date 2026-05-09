from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, project_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[project_id].add(websocket)

    def disconnect(self, project_id: str, websocket: WebSocket) -> None:
        self._connections[project_id].discard(websocket)
        if not self._connections[project_id]:
            del self._connections[project_id]

    async def broadcast(
        self,
        project_id: str,
        message: dict[str, Any],
        exclude: WebSocket | None = None,
    ) -> None:
        stale: list[WebSocket] = []
        for websocket in self._connections.get(project_id, set()):
            if websocket is exclude:
                continue
            try:
                await websocket.send_json(message)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(project_id, websocket)
