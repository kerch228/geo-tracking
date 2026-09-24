from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.db.session import get_db_session
from app.main import app
from app.services import locations as location_service

USER_ID = "user-123"


@pytest.fixture
def payload() -> dict[str, Any]:
    return {
        "device_id": "device-1",
        "latitude": 50.4501,
        "longitude": 30.5234,
        "timestamp": "2026-09-24T12:00:00Z",
    }


@pytest.fixture
def client(monkeypatch: MonkeyPatch) -> Iterator[TestClient]:
    session = AsyncMock()

    async def override_session() -> Any:
        yield session

    monkeypatch.setattr("app.main.wait_for_database", AsyncMock())
    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_valid_location_is_accepted(
    client: TestClient,
    monkeypatch: MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    ingest = AsyncMock(return_value="accepted")
    monkeypatch.setattr(location_service, "ingest_location", ingest)

    response = client.post("/locations", headers={"X-User-Id": USER_ID}, json=payload)

    assert response.status_code == 201
    assert response.json() == {
        "status": "accepted",
        "device_id": "device-1",
        "timestamp": "2026-09-24T12:00:00Z",
    }
    ingest_call = ingest.await_args
    assert ingest_call is not None
    assert ingest_call.kwargs["user_id"] == USER_ID


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", 90.1),
        ("longitude", -180.1),
        ("device_id", "   "),
        ("timestamp", "not-a-timestamp"),
        ("timestamp", "2026-09-24T12:00:00"),
    ],
)
def test_invalid_location_is_rejected(
    client: TestClient,
    payload: dict[str, Any],
    field: str,
    value: object,
) -> None:
    payload[field] = value

    response = client.post("/locations", headers={"X-User-Id": USER_ID}, json=payload)

    assert response.status_code == 422


def test_location_requires_user_header(client: TestClient, payload: dict[str, Any]) -> None:
    response = client.post("/locations", json=payload)

    assert response.status_code == 422
