import asyncio
import os
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db.session import async_session_factory, engine
from app.db.spatial import make_geography_point
from app.models import DeviceLocation, Geozone

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


def test_geozone_can_be_persisted_with_geography_point() -> None:
    async def scenario() -> None:
        async with async_session_factory() as session:
            geozone = Geozone(
                user_id=f"user-{uuid4()}",
                name="Office",
                center=make_geography_point(longitude=30.5234, latitude=50.4501),
                radius_meters=250.0,
            )
            session.add(geozone)
            await session.flush()

            persisted = await session.scalar(select(Geozone).where(Geozone.id == geozone.id))
            assert persisted is not None
            assert persisted.center is not None
            await session.rollback()

    run_async(scenario)


def test_device_location_can_be_persisted() -> None:
    async def scenario() -> None:
        device_id = f"device-{uuid4()}"
        timestamp = datetime.now(timezone.utc)
        async with async_session_factory() as session:
            location = DeviceLocation(
                device_id=device_id,
                timestamp=timestamp,
                point=make_geography_point(longitude=30.5234, latitude=50.4501),
            )
            session.add(location)
            await session.flush()

            persisted = await session.get(DeviceLocation, (device_id, timestamp))
            assert persisted is not None
            assert persisted.point is not None
            await session.rollback()

    run_async(scenario)


@pytest.mark.parametrize(
    "invalid_model",
    [
        Geozone(
            user_id="user",
            name="Invalid radius",
            center=make_geography_point(longitude=30.5, latitude=50.4),
            radius_meters=0,
        ),
        Geozone(
            user_id=" ",
            name="Invalid user",
            center=make_geography_point(longitude=30.5, latitude=50.4),
            radius_meters=10,
        ),
        Geozone(
            user_id="user",
            name="x" * 256,
            center=make_geography_point(longitude=30.5, latitude=50.4),
            radius_meters=10,
        ),
        DeviceLocation(
            device_id=" ",
            timestamp=datetime.now(timezone.utc),
            point=make_geography_point(longitude=30.5, latitude=50.4),
        ),
    ],
    ids=["radius", "user-id", "name-length", "device-id"],
)
def test_database_constraints_reject_invalid_values(invalid_model: object) -> None:
    async def scenario() -> None:
        async with async_session_factory() as session:
            session.add(invalid_model)
            with pytest.raises(DBAPIError):
                await session.flush()
            await session.rollback()

    run_async(scenario)


def test_postgis_extension_and_spatial_index_exist() -> None:
    async def scenario() -> None:
        async with async_session_factory() as session:
            extension = await session.scalar(
                text("SELECT extname FROM pg_extension WHERE extname = 'postgis'")
            )
            index_definition = await session.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = 'geozones' "
                    "AND indexname = 'ix_geozones_center_gist'"
                )
            )

            assert extension == "postgis"
            assert index_definition is not None
            assert "USING gist" in index_definition

    run_async(scenario)
