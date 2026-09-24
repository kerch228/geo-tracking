import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.websocket.manager import connection_manager

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_INTEGRATION_TESTS", "").lower() != "true",
        reason="requires a real PostgreSQL/PostGIS database",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def apply_migrations() -> None:
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def location_payload(
    *,
    device_id: str,
    timestamp: datetime,
    latitude: float = 50.4501,
    longitude: float = 30.5234,
) -> dict[str, Any]:
    return {
        "device_id": device_id,
        "latitude": latitude,
        "longitude": longitude,
        "timestamp": timestamp.isoformat(),
    }


def post_location(
    client: TestClient,
    *,
    user_id: str,
    device_id: str,
    timestamp: datetime,
) -> None:
    response = client.post(
        "/locations",
        headers={"X-User-Id": user_id},
        json=location_payload(device_id=device_id, timestamp=timestamp),
    )
    assert response.status_code == 201


def test_websocket_connects_and_disconnects(client: TestClient) -> None:
    user_id = f"connect-{uuid4()}"
    portal = client.portal
    assert portal is not None

    with client.websocket_connect(f"/ws?user_id={user_id}") as websocket:
        websocket.send_text("connected")
        assert portal.call(connection_manager.connection_count, user_id) == 1

    assert portal.call(connection_manager.connection_count, user_id) == 0


def test_empty_user_id_is_rejected(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?user_id=%20%20%20"):
            pass


def test_multiple_connections_receive_same_location(client: TestClient) -> None:
    user_id = f"multi-{uuid4()}"
    device_id = f"device-{uuid4()}"
    timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

    with (
        client.websocket_connect(f"/ws?user_id={user_id}") as first,
        client.websocket_connect(f"/ws?user_id={user_id}") as second,
    ):
        post_location(
            client,
            user_id=user_id,
            device_id=device_id,
            timestamp=timestamp,
        )
        first_message = first.receive_json()
        second_message = second.receive_json()

    assert first_message == second_message
    assert first_message == {
        "type": "location",
        "device_id": device_id,
        "lat": 50.4501,
        "lng": 30.5234,
        "timestamp": "2026-09-24T12:00:00Z",
    }


def test_user_does_not_receive_another_users_locations(client: TestClient) -> None:
    user_a = f"user-a-{uuid4()}"
    user_b = f"user-b-{uuid4()}"
    device_a = f"device-a-{uuid4()}"
    device_b = f"device-b-{uuid4()}"
    timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

    with (
        client.websocket_connect(f"/ws?user_id={user_a}") as socket_a,
        client.websocket_connect(f"/ws?user_id={user_b}") as socket_b,
    ):
        post_location(
            client,
            user_id=user_b,
            device_id=device_b,
            timestamp=timestamp,
        )
        post_location(
            client,
            user_id=user_a,
            device_id=device_a,
            timestamp=timestamp,
        )
        assert socket_a.receive_json()["device_id"] == device_a
        assert socket_b.receive_json()["device_id"] == device_b

        post_location(
            client,
            user_id=user_b,
            device_id=device_b,
            timestamp=timestamp + timedelta(minutes=1),
        )
        assert socket_b.receive_json()["device_id"] == device_b


def test_duplicate_and_stale_do_not_broadcast_but_newer_does(client: TestClient) -> None:
    user_id = f"ordering-{uuid4()}"
    device_id = f"device-{uuid4()}"
    initial = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

    with client.websocket_connect(f"/ws?user_id={user_id}") as websocket:
        post_location(
            client,
            user_id=user_id,
            device_id=device_id,
            timestamp=initial,
        )
        assert websocket.receive_json()["timestamp"] == "2026-09-24T12:00:00Z"

        duplicate = client.post(
            "/locations",
            headers={"X-User-Id": user_id},
            json=location_payload(device_id=device_id, timestamp=initial),
        )
        stale = client.post(
            "/locations",
            headers={"X-User-Id": user_id},
            json=location_payload(
                device_id=device_id,
                timestamp=initial - timedelta(minutes=1),
            ),
        )
        assert duplicate.json()["status"] == "duplicate"
        assert stale.json()["status"] == "ignored_stale"

        newer = initial + timedelta(minutes=1)
        post_location(
            client,
            user_id=user_id,
            device_id=device_id,
            timestamp=newer,
        )
        message = websocket.receive_json()

    assert message["device_id"] == device_id
    assert message["timestamp"] == "2026-09-24T12:01:00Z"
