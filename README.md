# Real-Time Geo-Tracking Service

An asynchronous FastAPI backend for receiving device coordinates, storing the
latest position of each device, matching positions against user-owned geozones
in PostgreSQL/PostGIS, and delivering live location updates and geofence alerts
over WebSockets.

This repository is a take-home implementation. `X-User-Id` is deliberately used
as mock authentication; it is not a production authentication scheme.

## Architecture

```text
Device
  |
  v
POST /locations
  |
  v
Location Service
  |
  v
PostgreSQL/PostGIS
  |
  v
GeofenceService / ST_DWithin
  |
  v
WebSocketManager
  |
  v
Connected user clients
```

| Component | Responsibility |
| --- | --- |
| API layer | Validates HTTP/WebSocket input, resolves the current user, and delegates work to services. |
| Location service | Atomically persists the newest device position and orchestrates matching and broadcasting after commit. |
| Geofence service | Builds and executes the user-scoped `ST_DWithin` query in PostGIS. |
| WebSocket manager | Registers per-user sockets, serializes each user's broadcasts, sends to that user's sockets concurrently, and removes failed connections. |
| PostgreSQL/PostGIS | Stores current locations and geozones, enforces constraints, and performs geography distance filtering. |

All database access uses SQLAlchemy's async engine and `AsyncSession` with the
`asyncpg` driver. WebSocket I/O happens after the persistence transaction has
committed and after the matching read transaction has been closed.

## Project Structure

```text
app/
  api/             FastAPI routes and dependencies
  core/            environment-backed application settings
  db/              async engine, session factory, and spatial helpers
  models/          SQLAlchemy domain models
  schemas/         Pydantic request, response, and message schemas
  services/        geozone, location, and geofence operations
  websocket/       in-memory WebSocket connection manager
  main.py           application factory and lifespan handling
generator.py        async device/load simulator
docker-compose.yml  API and PostGIS services
Dockerfile          Python 3.10 API image
migrations/         Alembic environment and revisions
tests/              unit, integration, WebSocket, migration, and load tests
```

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/kerch228/geo-tracking.git
cd geo-tracking
```

The repository is private, so the clone command requires authorized GitHub
credentials.

### 2. Create local environment configuration

```bash
cp .env.example .env
```

Replace `POSTGRES_PASSWORD=change-me` in `.env` with a local development
password. Do not commit `.env`.

### 3. Start the stack and apply migrations

```bash
docker compose up --build -d
docker compose exec api alembic upgrade head
```

Compose starts the `api` container and a `postgis/postgis:16-3.4` database. It
waits for PostgreSQL's healthcheck before starting the API; the application also
performs its own retrying database readiness check.

### 4. Verify health

```bash
curl http://localhost:8000/health
```

```json
{"status":"ok"}
```

### 5. Create a geozone

```bash
curl -X POST http://localhost:8000/geozones \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: user-123' \
  -d '{
    "name": "Office",
    "center_lat": 50.4501,
    "center_lng": 30.5234,
    "radius_meters": 500
  }'
```

The response contains the generated numeric `id`, owner, coordinates, radius,
and timestamps.

### 6. Connect a WebSocket client

Connect with a WebSocket-capable client (for example, a browser console):

```js
const socket = new WebSocket("ws://localhost:8000/ws?user_id=user-123");
socket.onmessage = (event) => console.log(JSON.parse(event.data));
```

Keep the connection open for the next step.

### 7. Send a location

```bash
curl -X POST http://localhost:8000/locations \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: user-123' \
  -d '{
    "device_id": "device-1",
    "latitude": 50.4501,
    "longitude": 30.5234,
    "timestamp": "2026-09-24T12:00:00Z"
  }'
```

```json
{
  "status": "accepted",
  "device_id": "device-1",
  "timestamp": "2026-09-24T12:00:00Z"
}
```

### 8. Observe live messages

The connected client receives a `location` message followed by an `alert`
because the sample coordinate is inside the sample geozone.

## API

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`
while the application is running.

### Health

| Method | Path | Authentication | Success |
| --- | --- | --- | --- |
| `GET` | `/health` | None | `200 OK` with `{"status":"ok"}` |

### Geozones

All geozone endpoints require `X-User-Id`. The header is the sole source of the
owner identity; `user_id` is not accepted in a request body. Reads, updates, and
deletes include the owner in their database predicate. A geozone owned by a
different user is returned as `404 Not Found` rather than exposed.

| Method | Path | Success response |
| --- | --- | --- |
| `POST` | `/geozones` | `201 Created` with the created geozone |
| `GET` | `/geozones` | `200 OK` with the current user's geozones |
| `GET` | `/geozones/{id}` | `200 OK`, or `404` when unavailable to the user |
| `PUT` | `/geozones/{id}` | `200 OK` with the replaced geozone, or `404` |
| `DELETE` | `/geozones/{id}` | `204 No Content`, or `404` |

Create and update body:

```json
{
  "name": "Office",
  "center_lat": 50.4501,
  "center_lng": 30.5234,
  "radius_meters": 500
}
```

Response:

```json
{
  "id": 1,
  "user_id": "user-123",
  "name": "Office",
  "center_lat": 50.4501,
  "center_lng": 30.5234,
  "radius_meters": 500.0,
  "created_at": "2026-09-24T12:00:00Z",
  "updated_at": "2026-09-24T12:00:00Z"
}
```

Validation requires a non-blank name of at most 255 characters, latitude in
`[-90, 90]`, longitude in `[-180, 180]`, and a finite positive radius. The user
header is trimmed and must contain 1-128 characters.

### Location ingestion

`POST /locations` requires `X-User-Id` and this body:

```json
{
  "device_id": "device-1",
  "latitude": 50.4501,
  "longitude": 30.5234,
  "timestamp": "2026-09-24T12:00:00Z"
}
```

`device_id` must be non-blank and at most 128 characters, coordinates must be
valid, and `timestamp` must be timezone-aware. The response body always echoes
the device and submitted timestamp:

| Condition | HTTP status | Response `status` |
| --- | --- | --- |
| First event or timestamp newer than stored state | `201 Created` | `accepted` |
| Timestamp identical to stored state | `200 OK` | `duplicate` |
| Timestamp older than stored state | `200 OK` | `ignored_stale` |

Persistence uses one atomic PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` for
the `(user_id, device_id)` key. The update predicate only allows a greater
timestamp, so concurrent writes preserve the newest event. Duplicate and stale
events do not change coordinates and stop before geofence matching or WebSocket
broadcasting. The table stores only the latest known position, not location
history.

### WebSocket

```text
WS /ws?user_id=user-123
```

The non-blank `user_id` query parameter identifies the connection for this
take-home implementation. It is not real authentication. The manager maintains
the equivalent of:

```python
dict[user_id, set[WebSocket]]
```

This supports multiple tabs, devices, or sessions for one user. Connections are
registered after acceptance and removed on disconnect. Empty user entries are
cleaned up. Broadcasts for a user are serialized to preserve event ordering,
while sends to that user's sockets run concurrently. Each socket has a
configurable send timeout (five seconds by default); timed-out or broken sockets
are removed, and one failure does not prevent healthy sockets from receiving the
messages.

## WebSocket Messages

Accepted locations produce a location message:

```json
{
  "type": "location",
  "device_id": "device-1",
  "lat": 50.4501,
  "lng": 30.5234,
  "timestamp": "2026-09-24T12:00:00Z"
}
```

Each matching geozone produces one alert:

```json
{
  "type": "alert",
  "device_id": "device-1",
  "zone_id": "1",
  "zone_name": "Office",
  "lat": 50.4501,
  "lng": 30.5234
}
```

## PostGIS Geofences

Geozone centers and device points use `Geography(Point, 4326)`. Incoming API
coordinates are converted to PostGIS points in `longitude latitude` order; no
duplicate latitude/longitude columns are stored. Geography makes the radius and
`ST_DWithin` distance argument meters.

The geofence query includes both predicates:

```sql
WHERE user_id = :user_id
  AND ST_DWithin(center, :device_point, radius_meters)
```

Matching therefore considers only the location user's geozones. PostgreSQL has
a B-tree index on `user_id` and a GiST spatial index on `center`. All spatial
filtering runs in PostGIS; the application does not load every zone or calculate
Haversine distances in Python.

The radius is finite and greater than zero at both validation and database
constraint levels.

## Alert Flow

```text
accepted location
  -> atomic location upsert and commit
  -> PostGIS ST_DWithin query
  -> matching zones
  -> one location WebSocket message
  -> one alert WebSocket message per matching zone
```

The database commit happens before matching and broadcasting. A location outside
all zones still generates its location message. Multiple matches generate
multiple alerts in geozone ID order. Duplicate and stale events generate neither
location messages nor alerts, and another user's zones are never considered.
This implementation reports a match for every accepted event inside a zone; it
does not track geofence enter/exit state.

## Device Generator

The generator is an asynchronous client-side simulator:

```bash
python generator.py \
  --url http://localhost:8000/locations \
  --devices 10000 \
  --interval 3 \
  --concurrency 100
```

Defaults and useful options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--url` | `http://localhost:8000/locations` | Ingestion endpoint |
| `--devices` | `10000` | Number of simulated devices |
| `--interval` | `3` | Seconds between cycle starts |
| `--concurrency` | `100` | Maximum workers and HTTP connections |
| `--duration` | unset | Optional run duration in seconds |
| `--timeout` | `10` | Per-request HTTP timeout in seconds |
| `--user-id` | `generator-user` | Shared `X-User-Id` for generated devices |
| `--seed` | `42` | Reproducible position and movement seed |
| `--report-interval` | `5` | Statistics output interval in seconds |

IDs are deterministic (`device-00001` through `device-10000` for the default
count). Seeded initial coordinates are distributed around Kyiv, and each cycle
applies a small seeded movement while keeping coordinates valid. Updates use
timezone-aware UTC timestamps.

One shared `httpx.AsyncClient` is reused. A bounded worker queue and bounded HTTP
connection pool prevent 10,000 unrestricted tasks or connections. Statistics
report totals, successes, failures, status counts, errors, throughput, and
average/minimum/maximum latency without logging every device. HTTP/network
errors are counted without automatic retries, avoiding a retry storm. `SIGINT`,
`SIGTERM`, and Ctrl+C stop scheduling work, cancel the active bounded cycle when
appropriate, close the HTTP client, and print a final summary.

If the backend is slower than the requested interval, the next cycle waits for
the bounded current cycle rather than accumulating an unlimited backlog. The
offered rate and achieved rate are therefore distinct.

## Performance Results

These are local Docker benchmark results and are **not a claim of production
capacity**.

| Run | Result |
| --- | --- |
| 500 concurrent location requests | 500 successful, 0 errors, approximately 247.5 requests/second |
| One 10,000-device generator cycle | 10,000 requests, 10,000 successful, 0 failed, approximately 317.7 requests/second, approximately 312.6 ms average latency |

After the 10,000-device run, PostgreSQL contained 10,000 resulting current
location rows. No database/pool timeout or connection errors were observed.

The nominal offered rate for 10,000 devices sending every three seconds is:

```text
10,000 / 3 = approximately 3,333 requests/second
```

The local environment achieved approximately 317.7 requests/second. The result
demonstrates correctness and bounded behavior under the tested workload, not
that this machine or architecture sustains the nominal production-scale rate.
Additional benchmark context is in [`docs/performance.md`](docs/performance.md).

## Docker and Configuration

```bash
docker compose up --build
```

The stack contains:

- `api`: the non-root Python 3.10/FastAPI container running Uvicorn.
- `db`: PostgreSQL 16 with PostGIS 3.4, a persistent volume, and `pg_isready`
  healthcheck.

Configuration comes from environment variables. Copy `.env.example` to `.env`
for local use; the example contains placeholders, not real credentials. Compose
requires `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`. It also exposes
pool sizing, readiness retry, port, and WebSocket send-timeout settings.

The default SQLAlchemy pool per API process keeps 10 connections, allows 20
temporary overflow connections, waits 30 seconds for checkout, enables
`pool_pre_ping`, and recycles connections after 1,800 seconds. Requests borrow
connections from this bounded pool rather than opening a new connection each
time. Every additional API worker would own another pool and must be included in
database capacity planning.

## Database Migrations

Apply all revisions with:

```bash
docker compose exec api alembic upgrade head
```

For a locally configured Python environment, `alembic upgrade head` is
equivalent. The current chain is:

1. `20260924_01`: enable PostGIS and create the spatial domain tables and indexes.
2. `20260924_02`: change device locations to one latest row per user/device.
3. `20260924_03`: enforce finite geozone radii.

The chain has been tested on a clean PostGIS database with
upgrade/downgrade/upgrade. This is evidence for the tested schema path, not a
general guarantee for every production dataset or deployment procedure.

## Testing and Verification

The completed repository passes **82 tests**, including real PostgreSQL/PostGIS
model and geofence integration tests, REST isolation tests, location race and
idempotency tests, WebSocket integration tests, migration tests, generator unit
tests, and opt-in local concurrency tests.

Core checks:

```bash
pytest
ruff check .
mypy --strict app tests generator.py migrations/env.py migrations/versions
python -m compileall -q app tests generator.py migrations
git diff --check
docker compose config
alembic check
```

Database integration and load tests are explicitly enabled against a configured
PostGIS database:

```bash
RUN_DATABASE_INTEGRATION_TESTS=true pytest
RUN_DATABASE_INTEGRATION_TESTS=true RUN_LOAD_TESTS=true pytest
```

Final verification also covered a clean Alembic upgrade, downgrade, and repeat
upgrade. Integration tests exercise the real spatial types, constraints,
`ST_DWithin`, GiST index presence, REST behavior, WebSocket fan-out, and
concurrent newest-wins updates.

## Design Decisions and Trade-offs

- **PostGIS Geography:** WGS84 geography points provide appropriate geodetic
  distance semantics and meter-based radii without an application-level
  projection or approximation.
- **Database spatial filtering:** `ST_DWithin` keeps filtering in PostGIS and can
  use spatial/database indexes; Python does not transfer and scan all zones.
- **Bounded connection pool:** a finite per-process pool provides concurrency
  while placing an explicit upper bound on PostgreSQL connections.
- **In-memory WebSocket state:** it is sufficient for this single-process
  take-home and keeps delivery direct, but it cannot coordinate multiple API
  processes.
- **No Redis or shared pub/sub:** cross-process fan-out is not required by the
  current deployment, so the additional infrastructure and failure modes were
  not introduced.
- **No background queue:** direct async processing keeps accepted writes and
  alerts easy to reason about. A queue would add eventual delivery, retry, and
  idempotency concerns and is not justified by the measured local workload.
- **Commit before broadcast:** database state remains authoritative even when a
  socket is slow or fails; no transaction or pooled connection is held during
  WebSocket sends.
- **Latest location only:** the assignment needs current device state and
  idempotent newest-wins ingestion. Avoiding unlimited history keeps the write
  model bounded, at the cost of no historical tracking.

## Known Limitations and Production Considerations

- The WebSocket registry is process-local. Multiple API workers or instances
  would require shared pub/sub to route events to connections in other
  processes.
- A failure after the database commit but before broadcasting can theoretically
  lose a live event. A transactional outbox with reliable consumers is a common
  production approach when guaranteed delivery is required.
- `X-User-Id` and the WebSocket `user_id` query parameter are mock identity
  mechanisms, not authentication or authorization suitable for production.
- Only the latest location is stored; historical location tracking is not
  implemented.
- Geofence enter/exit state is not tracked. Every accepted location inside a
  zone generates an alert.
- The local benchmark does not prove production capacity and does not sustain
  the nominal 3,333 requests/second offered rate.
- Because each row has its own `radius_meters`, PostgreSQL may not derive one
  constant GiST search bound for the full query. The user index narrows the
  candidate set, but very large numbers of zones for one user require dedicated
  measurement and may need a more specialized search strategy.

## Code Quality

The implementation uses async HTTP, database, and WebSocket I/O; separates API,
service, persistence, spatial, and connection-management responsibilities; and
uses typed Python with strict MyPy checks. Pydantic and database constraints
validate external and persisted state. Alembic migrations, Dockerized services,
and real PostGIS integration tests make the main behavior reproducible.
