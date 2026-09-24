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

## Next phases

- Implement the 10,000-device asynchronous generator.
