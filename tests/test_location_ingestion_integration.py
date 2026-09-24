import asyncio
import os
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select

from app.db.session import async_session_factory, engine
from app.db.spatial import make_geography_point
from app.main import app
from app.models import DeviceLocation, Geozone
from app.schemas.location import LocationCreate
from app.services import locations as location_service
from app.services.geofence import GeofenceService
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


def run_async(test: Callable[[], Coroutine[Any, Any, None]]) -> None:
    async def run_and_close_pool() -> None:
        try:
            await test()
        finally:
            await engine.dispose()

    asyncio.run(run_and_close_pool())


async def post_location(
    *,
    user_id: str,
    device_id: str,
    latitude: float,
    longitude: float,
    timestamp: datetime,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/locations",
            headers={"X-User-Id": user_id},
            json={
                "device_id": device_id,
                "latitude": latitude,
                "longitude": longitude,
                "timestamp": timestamp.isoformat(),
            },
        )


def test_ingestion_persists_wgs84_geography_and_runs_geofence_match() -> None:
    async def scenario() -> None:
        user_id = f"ingest-{uuid4()}"
        device_id = f"device-{uuid4()}"
        timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        async with async_session_factory() as session:
            session.add(
                Geozone(
                    user_id=user_id,
                    name="Matching zone",
                    center=make_geography_point(longitude=30.5234, latitude=50.4501),
                    radius_meters=100,
                )
            )
            await session.commit()

        response = await post_location(
            user_id=user_id,
            device_id=device_id,
            latitude=50.4501,
            longitude=30.5234,
            timestamp=timestamp,
        )

        assert response.status_code == 201
        assert response.json()["status"] == "accepted"
        async with async_session_factory() as session:
            geometry = cast(DeviceLocation.point, Geometry(geometry_type="POINT", srid=4326))
            row = (
                await session.execute(
                    select(
                        DeviceLocation,
                        func.ST_Y(geometry),
                        func.ST_X(geometry),
                        func.ST_SRID(geometry),
                    ).where(
                        DeviceLocation.user_id == user_id,
                        DeviceLocation.device_id == device_id,
                    )
                )
            ).one()
            assert row[0].timestamp == timestamp
            assert row[1:] == pytest.approx((50.4501, 30.5234, 4326))
            matches = await GeofenceService.find_matching_zones(
                session,
                user_id=user_id,
                latitude=50.4501,
                longitude=30.5234,
            )
            assert [zone.name for zone in matches] == ["Matching zone"]

    run_async(scenario)


def test_replayed_event_is_idempotent() -> None:
    async def scenario() -> None:
        user_id = f"replay-{uuid4()}"
        device_id = f"device-{uuid4()}"
        timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        first = await post_location(
            user_id=user_id,
            device_id=device_id,
            latitude=50.0,
            longitude=30.0,
            timestamp=timestamp,
        )
        replay = await post_location(
            user_id=user_id,
            device_id=device_id,
            latitude=51.0,
            longitude=31.0,
            timestamp=timestamp,
        )

        assert first.status_code == 201
        assert replay.status_code == 200
        assert replay.json()["status"] == "duplicate"
        async with async_session_factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(DeviceLocation).where(
                    DeviceLocation.user_id == user_id,
                    DeviceLocation.device_id == device_id,
                )
            )
            assert count == 1

    run_async(scenario)


def test_older_event_does_not_replace_current_location() -> None:
    async def scenario() -> None:
        user_id = f"older-{uuid4()}"
        device_id = f"device-{uuid4()}"
        newer = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        await post_location(
            user_id=user_id,
            device_id=device_id,
            latitude=50.0,
            longitude=30.0,
            timestamp=newer,
        )
        response = await post_location(
            user_id=user_id,
            device_id=device_id,
            latitude=40.0,
            longitude=20.0,
            timestamp=newer - timedelta(minutes=1),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored_stale"
        async with async_session_factory() as session:
            stored = await session.get(DeviceLocation, (user_id, device_id))
            assert stored is not None
            assert stored.timestamp == newer

    run_async(scenario)


def test_newer_event_replaces_current_location() -> None:
    async def scenario() -> None:
        user_id = f"newer-{uuid4()}"
        device_id = f"device-{uuid4()}"
        older = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        newer = older + timedelta(minutes=1)
        await post_location(
            user_id=user_id,
            device_id=device_id,
            latitude=50.0,
            longitude=30.0,
            timestamp=older,
        )
        response = await post_location(
            user_id=user_id,
            device_id=device_id,
            latitude=51.0,
            longitude=31.0,
            timestamp=newer,
        )

        assert response.status_code == 201
        assert response.json()["status"] == "accepted"
        async with async_session_factory() as session:
            stored = await session.get(DeviceLocation, (user_id, device_id))
            assert stored is not None
            assert stored.timestamp == newer

    run_async(scenario)


def test_same_device_id_is_isolated_by_user() -> None:
    async def scenario() -> None:
        device_id = f"shared-{uuid4()}"
        timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        for user_id in (f"user-a-{uuid4()}", f"user-b-{uuid4()}"):
            response = await post_location(
                user_id=user_id,
                device_id=device_id,
                latitude=50.0,
                longitude=30.0,
                timestamp=timestamp,
            )
            assert response.status_code == 201

        async with async_session_factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(DeviceLocation).where(
                    DeviceLocation.device_id == device_id
                )
            )
            assert count == 2

    run_async(scenario)


def test_read_transaction_is_closed_before_websocket_broadcast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        user_id = f"transaction-{uuid4()}"
        device_id = f"device-{uuid4()}"
        timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        async with async_session_factory() as session:
            broadcast_called = False

            async def assert_no_transaction(
                broadcast_user_id: str,
                messages: list[dict[str, Any]],
            ) -> None:
                nonlocal broadcast_called
                broadcast_called = True
                assert broadcast_user_id == user_id
                assert messages[0]["type"] == "location"
                assert not session.in_transaction()

            monkeypatch.setattr(connection_manager, "broadcast_many", assert_no_transaction)
            result = await location_service.ingest_location(
                session,
                user_id=user_id,
                data=LocationCreate(
                    device_id=device_id,
                    latitude=50.4501,
                    longitude=30.5234,
                    timestamp=timestamp,
                ),
            )

            assert result == "accepted"
            assert broadcast_called

    run_async(scenario)
