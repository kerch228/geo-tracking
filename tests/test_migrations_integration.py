import asyncio
import os
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db.session import async_session_factory, engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_INTEGRATION_TESTS", "").lower() != "true",
        reason="requires a real PostgreSQL/PostGIS database",
    ),
]


def test_device_location_downgrade_handles_cross_user_key_collision() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

    async def seed_collision() -> None:
        async with async_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO device_locations (user_id, device_id, timestamp, point) "
                    "VALUES (:user_a, :device_id, :timestamp, "
                    "ST_SetSRID(ST_MakePoint(30.5234, 50.4501), 4326)::geography), "
                    "(:user_b, :device_id, :timestamp, "
                    "ST_SetSRID(ST_MakePoint(30.5234, 50.4501), 4326)::geography)"
                ),
                {
                    "user_a": "migration-user-a",
                    "user_b": "migration-user-b",
                    "device_id": "migration-collision-device",
                    "timestamp": timestamp,
                },
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(seed_collision())

    try:
        command.downgrade(config, "20260924_01")
        command.upgrade(config, "head")
    finally:
        command.upgrade(config, "head")

    async def verify_and_clean_up() -> None:
        async with async_session_factory() as session:
            count = await session.scalar(
                text(
                    "SELECT count(*) FROM device_locations "
                    "WHERE device_id = 'migration-collision-device'"
                )
            )
            assert count == 1
            await session.execute(
                text(
                    "DELETE FROM device_locations "
                    "WHERE device_id = 'migration-collision-device'"
                )
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(verify_and_clean_up())
