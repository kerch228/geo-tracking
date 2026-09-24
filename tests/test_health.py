from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.main import app


def test_health(monkeypatch: MonkeyPatch) -> None:
    wait_for_database = AsyncMock()
    monkeypatch.setattr("app.main.wait_for_database", wait_for_database)

    with TestClient(app) as client:
        response = client.get("/health")

    wait_for_database.assert_awaited_once_with()
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
