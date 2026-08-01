import asyncio

from fastapi import FastAPI
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.api.agent import router as agent_router
from app.api.agent import settings as agent_settings
from app.api.websocket import ConnectionManager


def test_agent_websocket_heartbeat_is_not_a_chat_event(tmp_path, monkeypatch):
    monkeypatch.setattr(
        type(agent_settings),
        "project_path",
        lambda self, project_path=None, project_id=None: tmp_path,
    )
    app = FastAPI()
    app.include_router(agent_router)

    with TestClient(app) as client:
        with client.websocket_connect("/agent/current/ws?project_path=isolated") as websocket:
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {"type": "pong"}


def test_broadcast_removes_disconnected_socket_without_interrupting_healthy_clients():
    class FakeWebSocket:
        def __init__(self, disconnected: bool = False):
            self.disconnected = disconnected
            self.messages: list[dict] = []

        async def accept(self):
            return None

        async def send_json(self, message: dict):
            if self.disconnected:
                raise WebSocketDisconnect(code=1001)
            self.messages.append(message)

    async def scenario():
        manager = ConnectionManager()
        stale = FakeWebSocket(disconnected=True)
        healthy = FakeWebSocket()
        await manager.connect("project", stale)  # type: ignore[arg-type]
        await manager.connect("project", healthy)  # type: ignore[arg-type]

        await manager.broadcast("project", {"type": "stream", "content": "hello"})

        assert healthy.messages == [{"type": "stream", "content": "hello"}]
        assert stale not in manager._connections["project"]
        assert healthy in manager._connections["project"]

    asyncio.run(scenario())
