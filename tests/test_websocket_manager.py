import asyncio
from typing import Any, cast

from fastapi import WebSocket

from app.websocket.manager import WebSocketManager


class FakeWebSocket:
    def __init__(self, *, broken: bool = False) -> None:
        self.accepted = False
        self.broken = broken
        self.messages: list[dict[str, Any]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict[str, Any]) -> None:
        if self.broken:
            raise RuntimeError("connection closed")
        self.messages.append(message)


def as_websocket(socket: FakeWebSocket) -> WebSocket:
    return cast(WebSocket, cast(object, socket))


def test_connect_and_disconnect_manage_user_connections() -> None:
    async def scenario() -> None:
        manager = WebSocketManager()
        first = FakeWebSocket()
        second = FakeWebSocket()

        await manager.connect("user-123", as_websocket(first))
        await manager.connect("user-123", as_websocket(second))
        assert first.accepted and second.accepted
        assert await manager.connection_count("user-123") == 2

        await manager.disconnect("user-123", as_websocket(first))
        assert await manager.connection_count("user-123") == 1
        await manager.disconnect("user-123", as_websocket(second))
        assert await manager.connection_count("user-123") == 0

    asyncio.run(scenario())


def test_broadcast_reaches_every_connection_for_only_one_user() -> None:
    async def scenario() -> None:
        manager = WebSocketManager()
        first = FakeWebSocket()
        second = FakeWebSocket()
        other = FakeWebSocket()
        await manager.connect("user-123", as_websocket(first))
        await manager.connect("user-123", as_websocket(second))
        await manager.connect("user-456", as_websocket(other))

        message = {"type": "location", "device_id": "device-1"}
        await manager.broadcast("user-123", message)

        assert first.messages == [message]
        assert second.messages == [message]
        assert other.messages == []

    asyncio.run(scenario())


def test_broken_connection_is_removed_without_blocking_healthy_socket() -> None:
    async def scenario() -> None:
        manager = WebSocketManager()
        broken = FakeWebSocket(broken=True)
        healthy = FakeWebSocket()
        await manager.connect("user-123", as_websocket(broken))
        await manager.connect("user-123", as_websocket(healthy))

        messages = [
            {"type": "location", "device_id": "device-1"},
            {"type": "alert", "device_id": "device-1", "zone_id": "1"},
        ]
        await manager.broadcast_many("user-123", messages)

        assert healthy.messages == messages
        assert await manager.connection_count("user-123") == 1

    asyncio.run(scenario())
