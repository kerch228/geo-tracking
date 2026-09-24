from typing import Annotated

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.websocket.manager import connection_manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: Annotated[str, Query(min_length=1, max_length=128)],
) -> None:
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await connection_manager.connect(normalized_user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.disconnect(normalized_user_id, websocket)
