import asyncio
import os
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db.session import async_session_factory, engine
from app.db.spatial import make_geography_point
from app.models import Geozone
from app.services.geofence import GeofenceService

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


def make_zone(
    *,
    user_id: str,
    name: str,
    latitude: float = 0.0,
    longitude: float = 0.0,
    radius_meters: float = 1_000.0,
) -> Geozone:
    return Geozone(
        user_id=user_id,
        name=name,
        center=make_geography_point(longitude=longitude, latitude=latitude),
        radius_meters=radius_meters,
    )


def test_point_clearly_inside_zone_is_returned() -> None:
    async def scenario() -> None:
        user_id = f"inside-{uuid4()}"
        async with async_session_factory() as session:
            zone = make_zone(user_id=user_id, name="Inside")
            session.add(zone)
            await session.flush()

            matches = await GeofenceService.find_matching_zones(
                session,
                user_id=user_id,
                latitude=0.0,
                longitude=0.001,
            )

            assert [match.id for match in matches] == [zone.id]
            await session.rollback()

    run_async(scenario)


def test_point_clearly_outside_zone_is_not_returned() -> None:
    async def scenario() -> None:
        user_id = f"outside-{uuid4()}"
        async with async_session_factory() as session:
            session.add(make_zone(user_id=user_id, name="Outside"))
            await session.flush()

            matches = await GeofenceService.find_matching_zones(
                session,
                user_id=user_id,
                latitude=0.0,
                longitude=0.02,
            )

            assert matches == []
            await session.rollback()

    run_async(scenario)


def test_points_near_zone_boundary_follow_radius() -> None:
    async def scenario() -> None:
        user_id = f"boundary-{uuid4()}"
        async with async_session_factory() as session:
            zone = make_zone(user_id=user_id, name="Boundary", radius_meters=1_000)
            session.add(zone)
            await session.flush()

            just_inside = await GeofenceService.find_matching_zones(
                session,
                user_id=user_id,
                latitude=0.0,
                longitude=0.00898,
            )
            just_outside = await GeofenceService.find_matching_zones(
                session,
                user_id=user_id,
                latitude=0.0,
                longitude=0.009,
            )

            assert [match.id for match in just_inside] == [zone.id]
            assert just_outside == []
            await session.rollback()

    run_async(scenario)


def test_all_matching_zones_are_returned() -> None:
    async def scenario() -> None:
        user_id = f"multiple-{uuid4()}"
        async with async_session_factory() as session:
            first = make_zone(user_id=user_id, name="First", radius_meters=1_000)
            second = make_zone(
                user_id=user_id,
                name="Second",
                longitude=0.005,
                radius_meters=1_000,
            )
            non_match = make_zone(
                user_id=user_id,
                name="Far away",
                longitude=0.03,
                radius_meters=500,
            )
            session.add_all([first, second, non_match])
            await session.flush()

            matches = await GeofenceService.find_matching_zones(
                session,
                user_id=user_id,
                latitude=0.0,
                longitude=0.004,
            )

            assert {match.id for match in matches} == {first.id, second.id}
            await session.rollback()

    run_async(scenario)


def test_matching_zones_are_isolated_by_user() -> None:
    async def scenario() -> None:
        user_a = f"user-a-{uuid4()}"
        user_b = f"user-b-{uuid4()}"
        async with async_session_factory() as session:
            zone_a = make_zone(user_id=user_a, name="User A")
            zone_b = make_zone(user_id=user_b, name="User B")
            session.add_all([zone_a, zone_b])
            await session.flush()

            matches = await GeofenceService.find_matching_zones(
                session,
                user_id=user_a,
                latitude=0.0,
                longitude=0.001,
            )

            assert [match.id for match in matches] == [zone_a.id]
            assert zone_b.id not in {match.id for match in matches}
            await session.rollback()

    run_async(scenario)


def test_coordinate_matching_no_zones_returns_empty_list() -> None:
    async def scenario() -> None:
        user_id = f"none-{uuid4()}"
        async with async_session_factory() as session:
            session.add(
                make_zone(
                    user_id=user_id,
                    name="Far",
                    latitude=40.0,
                    longitude=40.0,
                    radius_meters=100,
                )
            )
            await session.flush()

            matches = await GeofenceService.find_matching_zones(
                session,
                user_id=user_id,
                latitude=-40.0,
                longitude=-40.0,
            )

            assert matches == []
            await session.rollback()

    run_async(scenario)


def test_each_zones_radius_is_respected() -> None:
    async def scenario() -> None:
        user_id = f"radius-{uuid4()}"
        async with async_session_factory() as session:
            small = make_zone(user_id=user_id, name="Small", radius_meters=500)
            large = make_zone(user_id=user_id, name="Large", radius_meters=1_500)
            session.add_all([small, large])
            await session.flush()

            matches = await GeofenceService.find_matching_zones(
                session,
                user_id=user_id,
                latitude=0.0,
                longitude=0.009,
            )

            assert [match.id for match in matches] == [large.id]
            await session.rollback()

    run_async(scenario)


def test_spatial_index_exists_and_query_plan_contains_st_dwithin() -> None:
    async def scenario() -> None:
        async with async_session_factory() as session:
            index_definition = await session.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = 'public' "
                    "AND tablename = 'geozones' "
                    "AND indexname = 'ix_geozones_center_gist'"
                )
            )
            plan_rows = await session.execute(
                text(
                    "EXPLAIN (COSTS OFF) "
                    "SELECT id FROM geozones "
                    "WHERE user_id = :user_id "
                    "AND ST_DWithin("
                    "center, ST_GeogFromText(:device_point), radius_meters"
                    ")"
                ),
                {
                    "user_id": f"plan-{uuid4()}",
                    "device_point": "SRID=4326;POINT(0 0)",
                },
            )
            plan = "\n".join(str(row[0]) for row in plan_rows)

            assert index_definition is not None
            assert "USING gist" in index_definition
            assert "st_dwithin" in plan.lower()

    run_async(scenario)
