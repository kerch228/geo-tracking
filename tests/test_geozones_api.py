from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.db.session import get_db_session
from app.main import app
from app.schemas.geozone import GeozoneCreate, GeozoneRead
from app.services import geozones as geozone_service

USER_A = "user-a"
USER_B = "user-b"


@pytest.fixture
def geozone_payload() -> dict[str, Any]:
    return {
        "name": "Office",
        "center_lat": 50.4501,
        "center_lng": 30.5234,
        "radius_meters": 500.0,
    }


@pytest.fixture
def geozone() -> GeozoneRead:
    timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    return GeozoneRead(
        id=1,
        user_id=USER_A,
        name="Office",
        center_lat=50.4501,
        center_lng=30.5234,
        radius_meters=500.0,
        created_at=timestamp,
        updated_at=timestamp,
    )


@pytest.fixture
def client(monkeypatch: MonkeyPatch) -> Iterator[tuple[TestClient, AsyncMock]]:
    session = AsyncMock()

    async def override_session() -> Any:
        yield session

    monkeypatch.setattr("app.main.wait_for_database", AsyncMock())
    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as test_client:
            yield test_client, session
    finally:
        app.dependency_overrides.clear()


def test_create_geozone(
    client: tuple[TestClient, AsyncMock],
    monkeypatch: MonkeyPatch,
    geozone_payload: dict[str, Any],
    geozone: GeozoneRead,
) -> None:
    test_client, session = client
    create = AsyncMock(return_value=geozone)
    monkeypatch.setattr(geozone_service, "create_geozone", create)

    response = test_client.post(
        "/geozones",
        headers={"X-User-Id": USER_A},
        json=geozone_payload,
    )

    assert response.status_code == 201
    assert response.json()["user_id"] == USER_A
    assert response.json()["center_lat"] == 50.4501
    create.assert_awaited_once()
    create_call = create.await_args
    assert create_call is not None
    assert create_call.args[0] is session
    assert create_call.kwargs["user_id"] == USER_A
    assert "user_id" not in create_call.kwargs["data"].model_fields_set


def test_get_users_geozones(
    client: tuple[TestClient, AsyncMock],
    monkeypatch: MonkeyPatch,
    geozone: GeozoneRead,
) -> None:
    test_client, session = client
    list_geozones = AsyncMock(return_value=[geozone])
    monkeypatch.setattr(geozone_service, "list_geozones", list_geozones)

    response = test_client.get("/geozones", headers={"X-User-Id": USER_A})

    assert response.status_code == 200
    assert response.json()[0]["id"] == geozone.id
    list_geozones.assert_awaited_once_with(session, user_id=USER_A)


def test_get_one_geozone(
    client: tuple[TestClient, AsyncMock],
    monkeypatch: MonkeyPatch,
    geozone: GeozoneRead,
) -> None:
    test_client, session = client
    get_geozone = AsyncMock(return_value=geozone)
    monkeypatch.setattr(geozone_service, "get_geozone", get_geozone)

    response = test_client.get("/geozones/1", headers={"X-User-Id": USER_A})

    assert response.status_code == 200
    assert response.json()["id"] == 1
    get_geozone.assert_awaited_once_with(session, geozone_id=1, user_id=USER_A)


def test_update_geozone(
    client: tuple[TestClient, AsyncMock],
    monkeypatch: MonkeyPatch,
    geozone_payload: dict[str, Any],
    geozone: GeozoneRead,
) -> None:
    test_client, session = client
    updated = geozone.model_copy(update={"name": "Warehouse"})
    update_geozone = AsyncMock(return_value=updated)
    monkeypatch.setattr(geozone_service, "update_geozone", update_geozone)
    geozone_payload["name"] = "Warehouse"

    response = test_client.put(
        "/geozones/1",
        headers={"X-User-Id": USER_A},
        json=geozone_payload,
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Warehouse"
    update_call = update_geozone.await_args
    assert update_call is not None
    assert update_call.args[0] is session
    assert update_call.kwargs["geozone_id"] == 1
    assert update_call.kwargs["user_id"] == USER_A


def test_delete_geozone(
    client: tuple[TestClient, AsyncMock],
    monkeypatch: MonkeyPatch,
) -> None:
    test_client, session = client
    delete_geozone = AsyncMock(return_value=True)
    monkeypatch.setattr(geozone_service, "delete_geozone", delete_geozone)

    response = test_client.delete("/geozones/1", headers={"X-User-Id": USER_A})

    assert response.status_code == 204
    assert response.content == b""
    delete_geozone.assert_awaited_once_with(session, geozone_id=1, user_id=USER_A)


def test_user_cannot_read_another_users_geozone(
    client: tuple[TestClient, AsyncMock],
    monkeypatch: MonkeyPatch,
) -> None:
    test_client, session = client
    get_geozone = AsyncMock(return_value=None)
    monkeypatch.setattr(geozone_service, "get_geozone", get_geozone)

    response = test_client.get("/geozones/1", headers={"X-User-Id": USER_B})

    assert response.status_code == 404
    get_geozone.assert_awaited_once_with(session, geozone_id=1, user_id=USER_B)


def test_user_cannot_update_another_users_geozone(
    client: tuple[TestClient, AsyncMock],
    monkeypatch: MonkeyPatch,
    geozone_payload: dict[str, Any],
) -> None:
    test_client, session = client
    update_geozone = AsyncMock(return_value=None)
    monkeypatch.setattr(geozone_service, "update_geozone", update_geozone)

    response = test_client.put(
        "/geozones/1",
        headers={"X-User-Id": USER_B},
        json=geozone_payload,
    )

    assert response.status_code == 404
    update_call = update_geozone.await_args
    assert update_call is not None
    assert update_call.args[0] is session
    assert update_call.kwargs["user_id"] == USER_B


def test_user_cannot_delete_another_users_geozone(
    client: tuple[TestClient, AsyncMock],
    monkeypatch: MonkeyPatch,
) -> None:
    test_client, session = client
    delete_geozone = AsyncMock(return_value=False)
    monkeypatch.setattr(geozone_service, "delete_geozone", delete_geozone)

    response = test_client.delete("/geozones/1", headers={"X-User-Id": USER_B})

    assert response.status_code == 404
    delete_geozone.assert_awaited_once_with(session, geozone_id=1, user_id=USER_B)


def test_invalid_latitude(
    client: tuple[TestClient, AsyncMock],
    geozone_payload: dict[str, Any],
) -> None:
    test_client, _ = client
    geozone_payload["center_lat"] = 90.1

    response = test_client.post(
        "/geozones",
        headers={"X-User-Id": USER_A},
        json=geozone_payload,
    )

    assert response.status_code == 422


def test_invalid_longitude(
    client: tuple[TestClient, AsyncMock],
    geozone_payload: dict[str, Any],
) -> None:
    test_client, _ = client
    geozone_payload["center_lng"] = -180.1

    response = test_client.post(
        "/geozones",
        headers={"X-User-Id": USER_A},
        json=geozone_payload,
    )

    assert response.status_code == 422


def test_invalid_radius(
    client: tuple[TestClient, AsyncMock],
    geozone_payload: dict[str, Any],
) -> None:
    test_client, _ = client
    geozone_payload["radius_meters"] = 0

    response = test_client.post(
        "/geozones",
        headers={"X-User-Id": USER_A},
        json=geozone_payload,
    )

    assert response.status_code == 422


@pytest.mark.parametrize("radius", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_radius_is_rejected(radius: float) -> None:
    with pytest.raises(ValidationError, match="finite number"):
        GeozoneCreate(
            name="Office",
            center_lat=50.4501,
            center_lng=30.5234,
            radius_meters=radius,
        )


def test_missing_user_header(
    client: tuple[TestClient, AsyncMock],
    geozone_payload: dict[str, Any],
) -> None:
    test_client, _ = client

    response = test_client.post("/geozones", json=geozone_payload)

    assert response.status_code == 422


def test_empty_user_header(
    client: tuple[TestClient, AsyncMock],
    geozone_payload: dict[str, Any],
) -> None:
    test_client, _ = client

    response = test_client.post(
        "/geozones",
        headers={"X-User-Id": "   "},
        json=geozone_payload,
    )

    assert response.status_code == 422
