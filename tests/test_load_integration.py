import asyncio
import os
import random
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config

from app.db.session import async_session_factory, engine
from app.main import app
from app.models import DeviceLocation

pytestmark = [
    pytest.mark.integration,
    pytest.mark.load,
    pytest.mark.skipif(
        os.getenv("RUN_LOAD_TESTS", "").lower() != "true",
        reason="requires explicit opt-in for the local concurrency benchmark",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def apply_migrations() -> None:
    command.upgrade(Config("alembic.ini"), "head")


async def send_location(
    client: httpx.AsyncClient,
    *,
    user_id: str,
    device_id: str,
    timestamp: datetime,
) -> int:
    response = await client.post(
        "/locations",
        headers={"X-User-Id": user_id},
        json={
            "device_id": device_id,
            "latitude": 50.4501,
            "longitude": 30.5234,
            "timestamp": timestamp.isoformat(),
        },
    )
    return response.status_code


def test_500_concurrent_updates_across_100_devices() -> None:
    async def scenario() -> None:
        user_id = f"load-{uuid4()}"
        base_timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            timeout=60,
        ) as client:
            started = time.perf_counter()
            results = await asyncio.gather(
                *(
                    send_location(
                        client,
                        user_id=user_id,
                        device_id=f"device-{index % 100}",
                        timestamp=base_timestamp + timedelta(seconds=index // 100),
                    )
                    for index in range(500)
                ),
                return_exceptions=True,
            )
            elapsed = time.perf_counter() - started

        failures = [result for result in results if isinstance(result, BaseException)]
        statuses = [result for result in results if isinstance(result, int)]
        http_errors = [status for status in statuses if status >= 400]
        successful = len(statuses) - len(http_errors)
        throughput = successful / elapsed
        print(
            "LOAD_RESULT "
            f"requests=500 successful={successful} errors={len(failures) + len(http_errors)} "
            f"elapsed_seconds={elapsed:.3f} throughput_rps={throughput:.1f}"
        )

        assert failures == []
        assert http_errors == []
        assert successful == 500
        async with async_session_factory() as session:
            for device_index in range(100):
                location = await session.get(
                    DeviceLocation,
                    (user_id, f"device-{device_index}"),
                )
                assert location is not None
                assert location.timestamp == base_timestamp + timedelta(seconds=4)

        await engine.dispose()

    asyncio.run(scenario())


def test_concurrent_same_device_updates_keep_newest_timestamp() -> None:
    async def scenario() -> None:
        user_id = f"race-{uuid4()}"
        device_id = f"device-{uuid4()}"
        base_timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        timestamps = (
            [base_timestamp - timedelta(seconds=1)] * 20
            + [base_timestamp] * 20
            + [base_timestamp + timedelta(seconds=1)] * 20
        )
        random.Random(42).shuffle(timestamps)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            timeout=60,
        ) as client:
            statuses = await asyncio.gather(
                *(
                    send_location(
                        client,
                        user_id=user_id,
                        device_id=device_id,
                        timestamp=timestamp,
                    )
                    for timestamp in timestamps
                )
            )

        assert all(status in {200, 201} for status in statuses)
        async with async_session_factory() as session:
            location = await session.get(DeviceLocation, (user_id, device_id))
            assert location is not None
            assert location.timestamp == base_timestamp + timedelta(seconds=1)

        await engine.dispose()

    asyncio.run(scenario())
