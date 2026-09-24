import asyncio
import random
from datetime import datetime, timezone

import httpx
import pytest

from generator import (
    GeneratorConfig,
    RuntimeStats,
    create_devices,
    dispatch_updates,
    move_devices,
    parse_args,
    utc_timestamp,
)


def test_cli_parsing() -> None:
    config = parse_args(
        [
            "--url",
            "http://example.test/locations",
            "--devices",
            "10000",
            "--interval",
            "3",
            "--concurrency",
            "100",
            "--duration",
            "10",
            "--timeout",
            "2.5",
            "--user-id",
            "demo-user",
            "--seed",
            "7",
        ]
    )

    assert config.url == "http://example.test/locations"
    assert config.devices == 10_000
    assert config.interval == 3
    assert config.concurrency == 100
    assert config.duration == 10
    assert config.timeout == 2.5
    assert config.user_id == "demo-user"
    assert config.seed == 7


@pytest.mark.parametrize("option", ["--devices", "--interval", "--concurrency", "--timeout"])
def test_cli_rejects_non_positive_values(option: str) -> None:
    with pytest.raises(SystemExit):
        parse_args([option, "0"])


def test_device_ids_and_initial_coordinates_are_deterministic() -> None:
    first = create_devices(10_000, seed=42)
    second = create_devices(10_000, seed=42)

    assert first[0].device_id == "device-00001"
    assert first[-1].device_id == "device-10000"
    assert [(device.latitude, device.longitude) for device in first] == [
        (device.latitude, device.longitude) for device in second
    ]
    assert len({(device.latitude, device.longitude) for device in first}) > 9_900
    assert all(-90 <= device.latitude <= 90 for device in first)
    assert all(-180 <= device.longitude <= 180 for device in first)


def test_movement_is_small_valid_and_reproducible() -> None:
    first = create_devices(5, seed=11)
    second = create_devices(5, seed=11)
    before = [(device.latitude, device.longitude) for device in first]
    timestamp = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

    first_updates = move_devices(first, rng=random.Random(12), timestamp=timestamp)
    second_updates = move_devices(second, rng=random.Random(12), timestamp=timestamp)

    assert first_updates == second_updates
    assert all(update.timestamp == timestamp for update in first_updates)
    for old, update in zip(before, first_updates, strict=True):
        assert abs(update.latitude - old[0]) <= 0.0003
        assert abs(update.longitude - old[1]) <= 0.0003
        assert -90 <= update.latitude <= 90
        assert -180 <= update.longitude <= 180


def test_generated_timestamp_is_timezone_aware_utc() -> None:
    timestamp = utc_timestamp()

    assert timestamp.tzinfo is timezone.utc
    assert timestamp.utcoffset() is not None


def test_dispatch_limits_concurrent_requests_and_reuses_client() -> None:
    async def scenario() -> None:
        active = 0
        maximum_active = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal active, maximum_active
            assert request.headers["X-User-Id"] == "test-user"
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return httpx.Response(201, json={"status": "accepted"})

        config = GeneratorConfig(
            url="http://test/locations",
            devices=20,
            concurrency=3,
            user_id="test-user",
        )
        devices = create_devices(config.devices, seed=1)
        updates = move_devices(
            devices,
            rng=random.Random(2),
            timestamp=datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
        )
        stats = RuntimeStats()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await dispatch_updates(client, updates, config=config, stats=stats)

        assert maximum_active == config.concurrency
        assert stats.total_requests == 20
        assert stats.successful_requests == 20
        assert stats.failed_requests == 0
        assert stats.status_counts == {201: 20}

    asyncio.run(scenario())


def test_network_failure_is_counted_without_retrying() -> None:
    async def scenario() -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ConnectError("unavailable", request=request)

        config = GeneratorConfig(
            url="http://test/locations",
            devices=1,
            concurrency=1,
        )
        updates = move_devices(
            create_devices(1, seed=1),
            rng=random.Random(2),
            timestamp=datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
        )
        stats = RuntimeStats()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await dispatch_updates(client, updates, config=config, stats=stats)

        assert calls == 1
        assert stats.total_requests == 1
        assert stats.successful_requests == 0
        assert stats.failed_requests == 1
        assert stats.error_counts == {"ConnectError": 1}

    asyncio.run(scenario())
