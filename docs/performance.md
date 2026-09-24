# Load-readiness notes

## Database pool

Each API process uses one SQLAlchemy async engine and session factory. The
default pool has 10 persistent connections, allows 20 temporary overflow
connections, waits up to 30 seconds for a checkout, enables `pool_pre_ping`, and
recycles connections after 1,800 seconds. Requests borrow a pooled connection;
they do not create a new connection per location.

These values are a reasonable local and single-process starting point. A maximum
of 30 database connections permits useful concurrency without immediately
overwhelming a default PostgreSQL instance. They should not be increased based
only on the 10,000-device count: update frequency, query latency, PostgreSQL
capacity, and API worker count determine the needed pool. Every additional API
process has its own pool, so deployment sizing must account for the sum of all
workers.

## Request path and transaction lifetime

The location path is fully asynchronous and performs an atomic PostgreSQL
upsert. Accepted events commit before geofence matching. The read transaction
started by `ST_DWithin` is explicitly closed before WebSocket I/O, so a slow
client cannot retain a database connection. Duplicate and stale events commit
and return without matching or broadcasting.

There is no synchronous database access, blocking file/network I/O, Python
distance calculation, or scan of all geozones in application code. Iteration is
limited to the already matched rows needed to build alert messages.

## PostGIS plan

The matching query filters by `user_id` and executes `ST_DWithin` on
`Geography(Point, 4326)`, so radii are meters. Both the `user_id` B-tree index
and `center` GiST index are present.

On a local 10,000-zone dataset split evenly over 100 users, `EXPLAIN ANALYZE`
selected `ix_geozones_user_id`, reduced the candidates to 100 rows, and applied
the variable per-row radius as a PostGIS filter. A constant-radius control query
used `ix_geozones_center_gist` through its bounding-box index condition. The
production query's radius comes from each row, so PostgreSQL cannot derive one
constant GiST search bound. This is acceptable while zones per user remain
small; unusually large per-user zone sets should be measured before introducing
additional radius metadata or a more complex two-stage query.

## Local concurrency benchmark

The opt-in test `tests/test_load_integration.py` sent 500 simultaneous in-process
ASGI requests across 100 devices to the real Docker PostgreSQL/PostGIS database.
On the development machine used for Phase 9 it recorded:

- 500 successful requests
- 0 HTTP, database, pool-timeout, or client errors
- 2.021 seconds elapsed
- 247.5 requests/second

The race test concurrently submitted older, identical, and newer timestamps for
one device; every response succeeded and the final row contained the newest
timestamp. This local benchmark validates concurrency behavior, not production
capacity for 10,000 devices. It excludes real network and reverse-proxy overhead
and uses one machine with an emulated amd64 PostGIS container.

## WebSocket backpressure

Sockets receive each event's messages in order, while different sockets are
served concurrently. Each socket has a configurable five-second send timeout;
timed-out or broken sockets are removed without affecting healthy sockets. No
database transaction is active during fan-out.

Direct request processing is sufficient for the current take-home workload and
preserves immediate, post-commit alerts. A queue is not currently justified.
Adding one would bound HTTP-side pressure and decouple slow fan-out, but it would
introduce operational complexity, eventual alert delivery, retry/idempotency
requirements, and a period where the accepted HTTP response precedes alert
processing. Those trade-offs should be accepted only after production metrics
show sustained pool saturation or unacceptable request latency.

## Generator validation

The Phase 10 generator was run through the published Docker API endpoint, not
the in-process ASGI test transport. A 100-device, one-second interval run for 10
seconds completed 1,000 requests with 1,000 successes, no errors, 99.6
requests/second, and 319.9 ms average latency.

One complete 10,000-device cycle with concurrency 100 completed all 10,000
requests with HTTP 201, no network/HTTP/database errors, 317.7 requests/second,
312.6 ms average latency, and 31.5 seconds elapsed. PostgreSQL contained exactly
10,000 rows for that generator user afterward. The requested three-second
interval offers 3,333 requests/second, but this local Docker environment did not
sustain that rate; bounded backpressure prevented overlapping cycles. This is a
development-machine observation, not a production capacity result.
