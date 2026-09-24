import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any, cast
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


def create_zone(
    client: TestClient,
    *,
    user_id: str,
    name: str,
    latitude: float = 50.4501,
    longitude: float = 30.5234,
    radius_meters: float = 500,
) -> dict[str, Any]:
    response = client.post(
        "/geozones",
        headers={"X-User-Id": user_id},
        json={
            "name": name,
            "center_lat": latitude,
            "center_lng": longitude,
            "radius_meters": radius_meters,
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


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
    zone = create_zone(client, user_id=user_id, name="Office")

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
        first_alert = first.receive_json()
        second_message = second.receive_json()
        second_alert = second.receive_json()

    assert first_message == second_message
    assert first_alert == second_alert
    assert first_message == {
        "type": "location",
        "device_id": device_id,
        "lat": 50.4501,
        "lng": 30.5234,
        "timestamp": "2026-09-24T12:00:00Z",
    }
    assert first_alert == {
        "type": "alert",
        "device_id": device_id,
        "zone_id": str(zone["id"]),
        "zone_name": "Office",
        "lat": 50.4501,
        "lng": 30.5234,
    }


def test_location_outside_zone_sends_location_only(client: TestClient) -> None:
    user_id = f"outside-{uuid4()}"
    device_id = f"device-{uuid4()}"
    timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    create_zone(
        client,
        user_id=user_id,
        name="Far away",
        latitude=40,
        longitude=20,
        radius_meters=100,
    )

    with client.websocket_connect(f"/ws?user_id={user_id}") as websocket:
        post_location(
            client,
            user_id=user_id,
            device_id=device_id,
            timestamp=timestamp,
        )
        first = websocket.receive_json()
        post_location(
            client,
            user_id=user_id,
            device_id=device_id,
            timestamp=timestamp + timedelta(minutes=1),
        )
        second = websocket.receive_json()

    assert first["type"] == "location"
    assert second["type"] == "location"


def test_location_inside_multiple_zones_sends_one_alert_per_zone(
    client: TestClient,
) -> None:
    user_id = f"zones-{uuid4()}"
    device_id = f"device-{uuid4()}"
    timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    first_zone = create_zone(client, user_id=user_id, name="Office", radius_meters=100)
    second_zone = create_zone(client, user_id=user_id, name="Campus", radius_meters=1_000)

    with client.websocket_connect(f"/ws?user_id={user_id}") as websocket:
        post_location(
            client,
            user_id=user_id,
            device_id=device_id,
            timestamp=timestamp,
        )
        messages = [websocket.receive_json() for _ in range(3)]

    assert messages[0]["type"] == "location"
    assert [message["zone_id"] for message in messages[1:]] == [
        str(first_zone["id"]),
        str(second_zone["id"]),
    ]
    assert [message["zone_name"] for message in messages[1:]] == ["Office", "Campus"]


def test_other_users_zone_does_not_generate_alert(client: TestClient) -> None:
    user_id = f"owner-{uuid4()}"
    other_user = f"other-{uuid4()}"
    device_id = f"device-{uuid4()}"
    timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    create_zone(client, user_id=other_user, name="Private zone")

    with client.websocket_connect(f"/ws?user_id={user_id}") as websocket:
        post_location(
            client,
            user_id=user_id,
            device_id=device_id,
            timestamp=timestamp,
        )
        first = websocket.receive_json()
        own_zone = create_zone(client, user_id=user_id, name="Own zone")
        post_location(
            client,
            user_id=user_id,
            device_id=device_id,
            timestamp=timestamp + timedelta(minutes=1),
        )
        second = websocket.receive_json()
        alert = websocket.receive_json()

    assert first["type"] == "location"
    assert second["type"] == "location"
    assert alert["zone_id"] == str(own_zone["id"])
    assert alert["zone_name"] == "Own zone"


def test_newer_location_moving_into_zone_generates_alert(client: TestClient) -> None:
    user_id = f"moving-{uuid4()}"
    device_id = f"device-{uuid4()}"
    timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    zone = create_zone(client, user_id=user_id, name="Destination")

    with client.websocket_connect(f"/ws?user_id={user_id}") as websocket:
        outside = client.post(
            "/locations",
            headers={"X-User-Id": user_id},
            json=location_payload(
                device_id=device_id,
                timestamp=timestamp,
                latitude=40,
                longitude=20,
            ),
        )
        assert outside.status_code == 201
        assert websocket.receive_json()["type"] == "location"

        post_location(
            client,
            user_id=user_id,
            device_id=device_id,
            timestamp=timestamp + timedelta(minutes=1),
        )
        location = websocket.receive_json()
        alert = websocket.receive_json()

    assert location["type"] == "location"
    assert alert["zone_id"] == str(zone["id"])


def test_user_does_not_receive_another_users_locations(client: TestClient) -> None:
    user_a = f"user-a-{uuid4()}"
    user_b = f"user-b-{uuid4()}"
    device_a = f"device-a-{uuid4()}"
    device_b = f"device-b-{uuid4()}"
    timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    zone_b = create_zone(client, user_id=user_b, name="User B zone")

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
        assert socket_b.receive_json()["zone_id"] == str(zone_b["id"])

        post_location(
            client,
            user_id=user_a,
            device_id=device_a,
            timestamp=timestamp + timedelta(minutes=1),
        )
        assert socket_a.receive_json()["type"] == "location"

        post_location(
            client,
            user_id=user_b,
            device_id=device_b,
            timestamp=timestamp + timedelta(minutes=1),
        )
        assert socket_b.receive_json()["type"] == "location"
        assert socket_b.receive_json()["zone_id"] == str(zone_b["id"])


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
