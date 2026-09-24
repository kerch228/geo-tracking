import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class _UserConnections:
    sockets: set[WebSocket] = field(default_factory=set)
    broadcast_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active_broadcasts: int = 0


class WebSocketManager:
    def __init__(self, *, send_timeout_seconds: float = 5.0) -> None:
        self._connections: dict[str, _UserConnections] = {}
        self._lock = asyncio.Lock()
        self._send_timeout_seconds = send_timeout_seconds

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            state = self._connections.setdefault(user_id, _UserConnections())
            state.sockets.add(websocket)

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            state = self._connections.get(user_id)
            if state is None:
                return
            state.sockets.discard(websocket)
            if not state.sockets and state.active_broadcasts == 0:
                self._connections.pop(user_id, None)

    async def broadcast(self, user_id: str, message: dict[str, Any]) -> None:
        await self.broadcast_many(user_id, [message])

    async def broadcast_many(
        self,
        user_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        async with self._lock:
            state = self._connections.get(user_id)
            if state is None or not state.sockets or not messages:
                return
            state.active_broadcasts += 1

        try:
            async with state.broadcast_lock:
                async with self._lock:
                    connections = tuple(state.sockets)

                async def send_messages(websocket: WebSocket) -> None:
                    for message in messages:
                        await websocket.send_json(message)

                results = await asyncio.gather(
                    *(
                        asyncio.wait_for(
                            send_messages(websocket),
                            timeout=self._send_timeout_seconds,
                        )
                        for websocket in connections
                    ),
                    return_exceptions=True,
                )
                failed = [
                    websocket
                    for websocket, result in zip(connections, results, strict=True)
                    if isinstance(result, BaseException)
                ]
                for websocket in failed:
                    logger.debug("Removing failed WebSocket connection for user %s", user_id)
                    await self.disconnect(user_id, websocket)
        finally:
            async with self._lock:
                state.active_broadcasts -= 1
                if not state.sockets and state.active_broadcasts == 0:
                    self._connections.pop(user_id, None)

    async def connection_count(self, user_id: str) -> int:
        async with self._lock:
            state = self._connections.get(user_id)
            return len(state.sockets) if state is not None else 0


connection_manager = WebSocketManager(
    send_timeout_seconds=settings.websocket_send_timeout_seconds,
)
