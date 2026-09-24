import asyncio
from typing import Any, cast

from fastapi import WebSocket

from app.websocket.manager import WebSocketManager


class FakeWebSocket:
    def __init__(self, *, broken: bool = False, delay_seconds: float = 0) -> None:
        self.accepted = False
        self.broken = broken
        self.delay_seconds = delay_seconds
        self.messages: list[dict[str, Any]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict[str, Any]) -> None:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.broken:
            raise RuntimeError("connection closed")
        self.messages.append(message)


class ConcurrentSendWebSocket(FakeWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.sending = False
        self.concurrent_send_detected = False

    async def send_json(self, message: dict[str, Any]) -> None:
        if self.sending:
            self.concurrent_send_detected = True
            raise RuntimeError("concurrent send")
        self.sending = True
        try:
            await asyncio.sleep(0.01)
            self.messages.append(message)
        finally:
            self.sending = False


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


def test_slow_connection_times_out_without_blocking_healthy_socket() -> None:
    async def scenario() -> None:
        manager = WebSocketManager(send_timeout_seconds=0.01)
        slow = FakeWebSocket(delay_seconds=1)
        healthy = FakeWebSocket()
        await manager.connect("user-123", as_websocket(slow))
        await manager.connect("user-123", as_websocket(healthy))

        message = {"type": "location", "device_id": "device-1"}
        await manager.broadcast("user-123", message)

        assert healthy.messages == [message]
        assert await manager.connection_count("user-123") == 1

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


def test_concurrent_broadcasts_are_serialized_per_user() -> None:
    async def scenario() -> None:
        manager = WebSocketManager()
        socket = ConcurrentSendWebSocket()
        await manager.connect("user-123", as_websocket(socket))

        first = [{"type": "location", "device_id": "device-1"}]
        second = [{"type": "location", "device_id": "device-2"}]
        await asyncio.gather(
            manager.broadcast_many("user-123", first),
            manager.broadcast_many("user-123", second),
        )

        assert not socket.concurrent_send_detected
        assert socket.messages == first + second
        assert await manager.connection_count("user-123") == 1

    asyncio.run(scenario())
