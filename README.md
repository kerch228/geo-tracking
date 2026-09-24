# Real-Time Geo-Tracking Service

Phases 1 and 2 provide the FastAPI project foundation, async SQLAlchemy setup,
Alembic configuration, PostgreSQL/PostGIS infrastructure, database readiness
handling, spatial domain models, and a health endpoint. API business logic is
intentionally deferred.

## Requirements

- Python 3.10+
- Docker and Docker Compose

## Run with Docker

```bash
cp .env.example .env
# Replace POSTGRES_PASSWORD in .env before starting the stack.
docker compose up --build
```

The API is available at `http://localhost:8000`. Check it with:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

Geozone requests use the simplified assignment identity header:

```bash
curl -H "X-User-Id: user-123" http://localhost:8000/geozones
```

Location ingestion uses the same identity header and stores one current location
per user/device pair:

```bash
curl -X POST -H "Content-Type: application/json" -H "X-User-Id: user-123" \
  http://localhost:8000/locations \
  -d '{"device_id":"device-1","latitude":50.4501,"longitude":30.5234,"timestamp":"2026-09-24T12:00:00Z"}'
```

The first event and events newer than the stored timestamp return `201` with
`status: "accepted"`. A replay with the same timestamp is idempotent and returns
`200` with `status: "duplicate"`; an older event returns `200` with
`status: "ignored_stale"`. Replayed and stale events do not replace current
coordinates or trigger geofence matching.

Live location updates are available over WebSocket:

```text
ws://localhost:8000/ws?user_id=user-123
```

Every active connection registered for that user receives accepted location
events as `{"type":"location","device_id":"device-1","lat":50.4501,
"lng":30.5234,"timestamp":"2026-09-24T12:00:00Z"}`. If PostGIS finds matching
geozones, the location message is followed by one alert per zone containing its
ID and name. Duplicate and stale events produce no WebSocket messages.
Connections are held in process memory, so this phase supports one API process;
cross-process fan-out is intentionally deferred until a shared broker is
introduced.

Compose waits for the PostgreSQL healthcheck before starting the API. The API
also retries its own `SELECT 1` readiness check before accepting requests.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

For local development, keep `DB_HOST=localhost`. Docker Compose overrides it to
the internal service hostname `db`.

## Verification

```bash
pytest
ruff check .
mypy app tests generator.py
python -m compileall -q app tests generator.py
alembic upgrade head --sql
```

Run the PostGIS integration tests against a disposable configured database with:

```bash
RUN_DATABASE_INTEGRATION_TESTS=true pytest tests/test_postgis_integration.py
```

The opt-in local concurrency benchmark is documented in
[`docs/performance.md`](docs/performance.md) and can be run with:

```bash
RUN_LOAD_TESTS=true pytest -s tests/test_load_integration.py
```

## Device generator

`generator.py` is an asynchronous client-side simulator. The default command
creates deterministic IDs from `device-00001` through `device-10000`, spreads
their initial positions around Kyiv, and applies small reproducible movements
before each update cycle:

```bash
python generator.py --devices 10000 --interval 3 --concurrency 100
```

Useful options:

```text
--url                 ingestion URL (default http://localhost:8000/locations)
--devices             simulated device count (default 10000)
--interval            seconds between cycle starts (default 3)
--concurrency         maximum simultaneous requests (default 100)
--duration            optional total runtime in seconds
--timeout             HTTP timeout in seconds (default 10)
--user-id             X-User-Id shared by generated devices (default generator-user)
--seed                reproducible position/movement seed (default 42)
--report-interval     statistics interval in seconds (default 5)
```

One `httpx.AsyncClient` and a bounded worker queue are reused for the whole run.
Network and HTTP failures are counted without retries. Statistics aggregate
request totals, successes/failures, status codes, throughput, and average,
minimum, and maximum latency. Press Ctrl+C to stop and print the final summary.
`--duration` stops scheduling new cycles at the deadline and lets the current
bounded cycle finish, so a saturated final cycle may extend wall-clock runtime.

At 10,000 devices and a three-second interval, the offered simulation rate is
approximately 3,333 requests/second. This is an offered rate, not a guarantee
that the backend or development machine can sustain it. If a cycle takes longer
than its interval, the generator starts the next cycle immediately after the
current bounded queue finishes instead of building an unbounded backlog.

## Database migrations

Create a migration after adding domain models:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

The first migration enables PostGIS and creates `geozones` and
`device_locations`. Coordinates are stored as WGS84 geography points; the point
order is longitude followed by latitude.

`GeofenceService.find_matching_zones` performs user-scoped containment matching
inside PostGIS with `ST_DWithin(center, device_point, radius_meters)`. Geography
distance arguments are interpreted in meters.
