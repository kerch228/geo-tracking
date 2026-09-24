import asyncio
import os
from collections.abc import Coroutine
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

from app.db.session import async_session_factory, engine
from app.schemas.geozone import GeozoneCreate, GeozoneUpdate
from app.services import geozones as geozone_service

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


def run_async(coroutine: Coroutine[Any, Any, None]) -> None:
    async def run_and_close_pool() -> None:
        try:
            await coroutine
        finally:
            await engine.dispose()

    asyncio.run(run_and_close_pool())


def test_geozone_crud_and_user_isolation() -> None:
    async def scenario() -> None:
        user_a = f"user-a-{uuid4()}"
        user_b = f"user-b-{uuid4()}"
        create_data = GeozoneCreate(
            name="Office",
            center_lat=50.4501,
            center_lng=30.5234,
            radius_meters=500,
        )

        async with async_session_factory() as session:
            zone_a = await geozone_service.create_geozone(
                session,
                user_id=user_a,
                data=create_data,
            )
            zone_b = await geozone_service.create_geozone(
                session,
                user_id=user_b,
                data=create_data,
            )

            user_a_zones = await geozone_service.list_geozones(session, user_id=user_a)
            assert [zone.id for zone in user_a_zones] == [zone_a.id]
            assert await geozone_service.get_geozone(
                session,
                geozone_id=zone_b.id,
                user_id=user_a,
            ) is None

            update_data = GeozoneUpdate(
                name="Updated office",
                center_lat=49.8397,
                center_lng=24.0297,
                radius_meters=750,
            )
            assert await geozone_service.update_geozone(
                session,
                geozone_id=zone_b.id,
                user_id=user_a,
                data=update_data,
            ) is None
            assert not await geozone_service.delete_geozone(
                session,
                geozone_id=zone_b.id,
                user_id=user_a,
            )

            updated = await geozone_service.update_geozone(
                session,
                geozone_id=zone_a.id,
                user_id=user_a,
                data=update_data,
            )
            assert updated is not None
            assert updated.name == "Updated office"
            assert updated.center_lat == pytest.approx(49.8397)
            assert updated.center_lng == pytest.approx(24.0297)

            assert await geozone_service.delete_geozone(
                session,
                geozone_id=zone_a.id,
                user_id=user_a,
            )
            assert await geozone_service.delete_geozone(
                session,
                geozone_id=zone_b.id,
                user_id=user_b,
            )

    run_async(scenario())
