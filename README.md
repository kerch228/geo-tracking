# Real-Time Geo-Tracking Service

Phases 1 and 2 provide the FastAPI project foundation, async SQLAlchemy setup,
Alembic configuration, PostgreSQL/PostGIS infrastructure, database readiness
handling, and a health endpoint. Domain models and business logic are
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

## Database migrations

Create a migration after adding domain models:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

## Next phases

- Add user-scoped geozone and device-location models.
- Add geozone CRUD and coordinate ingestion endpoints.
- Add PostGIS proximity queries and indexes.
- Add WebSocket connection management and real-time broadcasts.
- Implement the 10,000-device asynchronous generator.
