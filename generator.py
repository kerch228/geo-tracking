"""Asynchronous client-side location generator."""

from __future__ import annotations

import argparse
import asyncio
import random
import signal
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

DEFAULT_URL = "http://localhost:8000/locations"


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


@dataclass(frozen=True)
class GeneratorConfig:
    url: str = DEFAULT_URL
    devices: int = 10_000
    interval: float = 3.0
    concurrency: int = 100
    duration: float | None = None
    timeout: float = 10.0
    user_id: str = "generator-user"
    seed: int = 42
    report_interval: float = 5.0


@dataclass
class Device:
    device_id: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class LocationUpdate:
    device_id: str
    latitude: float
    longitude: float
    timestamp: datetime


@dataclass
class RuntimeStats:
    started_at: float = field(default_factory=time.perf_counter)
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    status_counts: Counter[int] = field(default_factory=Counter)
    error_counts: Counter[str] = field(default_factory=Counter)
    total_latency_seconds: float = 0.0
    min_latency_seconds: float | None = None
    max_latency_seconds: float | None = None

    def record(
        self,
        *,
        latency_seconds: float,
        status_code: int | None,
        error_name: str | None = None,
    ) -> None:
        self.total_requests += 1
        self.total_latency_seconds += latency_seconds
        self.min_latency_seconds = (
            latency_seconds
            if self.min_latency_seconds is None
            else min(self.min_latency_seconds, latency_seconds)
        )
        self.max_latency_seconds = (
            latency_seconds
            if self.max_latency_seconds is None
            else max(self.max_latency_seconds, latency_seconds)
        )
        if status_code is not None:
            self.status_counts[status_code] += 1
        if error_name is not None:
            self.error_counts[error_name] += 1
        if status_code is not None and 200 <= status_code < 300:
            self.successful_requests += 1
        else:
            self.failed_requests += 1

    def summary(self) -> str:
        elapsed = max(time.perf_counter() - self.started_at, 1e-9)
        average_ms = (
            self.total_latency_seconds / self.total_requests * 1_000
            if self.total_requests
            else 0.0
        )
        minimum_ms = (self.min_latency_seconds or 0.0) * 1_000
        maximum_ms = (self.max_latency_seconds or 0.0) * 1_000
        statuses = ",".join(
            f"{status}:{count}" for status, count in sorted(self.status_counts.items())
        ) or "none"
        errors = ",".join(
            f"{error}:{count}" for error, count in sorted(self.error_counts.items())
        ) or "none"
        return (
            f"requests={self.total_requests} success={self.successful_requests} "
            f"failed={self.failed_requests} rps={self.total_requests / elapsed:.1f} "
            f"latency_ms(avg/min/max)={average_ms:.1f}/{minimum_ms:.1f}/{maximum_ms:.1f} "
            f"statuses={statuses} errors={errors} elapsed={elapsed:.1f}s"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Location ingestion URL")
    parser.add_argument("--devices", type=positive_int, default=10_000)
    parser.add_argument("--interval", type=positive_float, default=3.0)
    parser.add_argument("--concurrency", type=positive_int, default=100)
    parser.add_argument("--duration", type=positive_float, default=None)
    parser.add_argument("--timeout", type=positive_float, default=10.0)
    parser.add_argument("--user-id", default="generator-user")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--report-interval", type=positive_float, default=5.0)
    return parser


def parse_args(argv: Sequence[str] | None = None) -> GeneratorConfig:
    args = build_parser().parse_args(argv)
    user_id = str(args.user_id).strip()
    if not user_id:
        build_parser().error("--user-id must not be empty")
    return GeneratorConfig(
        url=str(args.url),
        devices=int(args.devices),
        interval=float(args.interval),
        concurrency=int(args.concurrency),
        duration=float(args.duration) if args.duration is not None else None,
        timeout=float(args.timeout),
        user_id=user_id,
        seed=int(args.seed),
        report_interval=float(args.report_interval),
    )


def create_devices(count: int, *, seed: int) -> list[Device]:
    rng = random.Random(seed)
    width = max(5, len(str(count)))
    return [
        Device(
            device_id=f"device-{index:0{width}d}",
            latitude=50.4501 + rng.uniform(-0.1, 0.1),
            longitude=30.5234 + rng.uniform(-0.15, 0.15),
        )
        for index in range(1, count + 1)
    ]


def utc_timestamp() -> datetime:
    return datetime.now(timezone.utc)


def move_devices(
    devices: list[Device],
    *,
    rng: random.Random,
    timestamp: datetime,
) -> list[LocationUpdate]:
    updates: list[LocationUpdate] = []
    for device in devices:
        device.latitude = min(90.0, max(-90.0, device.latitude + rng.uniform(-0.0003, 0.0003)))
        device.longitude = min(
            180.0,
            max(-180.0, device.longitude + rng.uniform(-0.0003, 0.0003)),
        )
        updates.append(
            LocationUpdate(
                device_id=device.device_id,
                latitude=device.latitude,
                longitude=device.longitude,
                timestamp=timestamp,
            )
        )
    return updates


async def send_update(
    client: httpx.AsyncClient,
    *,
    url: str,
    user_id: str,
    update: LocationUpdate,
    stats: RuntimeStats,
) -> None:
    started = time.perf_counter()
    status_code: int | None = None
    error_name: str | None = None
    try:
        response = await client.post(
            url,
            headers={"X-User-Id": user_id},
            json={
                "device_id": update.device_id,
                "latitude": update.latitude,
                "longitude": update.longitude,
                "timestamp": update.timestamp.isoformat(),
            },
        )
        status_code = response.status_code
    except asyncio.CancelledError:
        raise
    except httpx.HTTPError as error:
        error_name = type(error).__name__
    stats.record(
        latency_seconds=time.perf_counter() - started,
        status_code=status_code,
        error_name=error_name,
    )


async def dispatch_updates(
    client: httpx.AsyncClient,
    updates: Sequence[LocationUpdate],
    *,
    config: GeneratorConfig,
    stats: RuntimeStats,
) -> None:
    if not updates:
        return

    worker_count = min(config.concurrency, len(updates))
    queue: asyncio.Queue[LocationUpdate | None] = asyncio.Queue(
        maxsize=worker_count * 2
    )

    async def worker() -> None:
        while True:
            update = await queue.get()
            try:
                if update is None:
                    return
                await send_update(
                    client,
                    url=config.url,
                    user_id=config.user_id,
                    update=update,
                    stats=stats,
                )
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
    try:
        for update in updates:
            await queue.put(update)
        for _ in workers:
            await queue.put(None)
        await queue.join()
        await asyncio.gather(*workers)
    except asyncio.CancelledError:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise


async def report_periodically(
    stats: RuntimeStats,
    *,
    interval: float,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            print(f"stats {stats.summary()}", flush=True)


async def stop_after(duration: float, *, stop_event: asyncio.Event) -> None:
    await asyncio.sleep(duration)
    stop_event.set()


def install_signal_handlers(
    stop_event: asyncio.Event,
    cancel_event: asyncio.Event,
) -> None:
    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        stop_event.set()
        cancel_event.set()

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_number, request_shutdown)
        except NotImplementedError:
            pass


async def run_generator(
    config: GeneratorConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    handle_signals: bool = True,
) -> RuntimeStats:
    devices = create_devices(config.devices, seed=config.seed)
    movement_rng = random.Random(config.seed + 1)
    stats = RuntimeStats()
    stop_event = asyncio.Event()
    cancel_event = asyncio.Event()
    report_stop_event = asyncio.Event()
    if handle_signals:
        install_signal_handlers(stop_event, cancel_event)

    duration_task = (
        asyncio.create_task(stop_after(config.duration, stop_event=stop_event))
        if config.duration is not None
        else None
    )
    reporter = asyncio.create_task(
        report_periodically(
            stats,
            interval=config.report_interval,
            stop_event=report_stop_event,
        )
    )
    limits = httpx.Limits(
        max_connections=config.concurrency,
        max_keepalive_connections=config.concurrency,
    )
    print(
        f"starting devices={config.devices} interval={config.interval:g}s "
        f"concurrency={config.concurrency} offered_rps={config.devices / config.interval:.1f} "
        f"user_id={config.user_id}",
        flush=True,
    )

    try:
        async with httpx.AsyncClient(
            timeout=config.timeout,
            limits=limits,
            transport=transport,
        ) as client:
            next_cycle_at = time.perf_counter()
            deadline = (
                next_cycle_at + config.duration
                if config.duration is not None
                else None
            )
            while not stop_event.is_set() and (
                deadline is None or time.perf_counter() < deadline
            ):
                updates = move_devices(
                    devices,
                    rng=movement_rng,
                    timestamp=utc_timestamp(),
                )
                cycle_task = asyncio.create_task(
                    dispatch_updates(client, updates, config=config, stats=stats)
                )
                cancel_waiter = asyncio.create_task(cancel_event.wait())
                done, _ = await asyncio.wait(
                    {cycle_task, cancel_waiter},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_waiter in done:
                    cycle_task.cancel()
                    await asyncio.gather(cycle_task, return_exceptions=True)
                    break
                cancel_waiter.cancel()
                await asyncio.gather(cancel_waiter, return_exceptions=True)
                await cycle_task

                next_cycle_at += config.interval
                delay = next_cycle_at - time.perf_counter()
                if delay > 0:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=delay)
                    except TimeoutError:
                        pass
    finally:
        stop_event.set()
        report_stop_event.set()
        await reporter
        if duration_task is not None:
            duration_task.cancel()
            await asyncio.gather(duration_task, return_exceptions=True)

    print(f"final {stats.summary()}", flush=True)
    return stats


def main(argv: Sequence[str] | None = None) -> None:
    config = parse_args(argv)
    try:
        asyncio.run(run_generator(config))
    except KeyboardInterrupt:
        print("generator interrupted", flush=True)


if __name__ == "__main__":
    main()
