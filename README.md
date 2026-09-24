# Real-Time Geo-Tracking Service

Phase 1 provides the FastAPI project foundation, async SQLAlchemy setup, Alembic
configuration, PostgreSQL/PostGIS infrastructure, and a health endpoint. Domain
models and business logic are intentionally deferred.

## Requirements

- Python 3.10+
- Docker and Docker Compose

## Run with Docker

```bash
cp .env.example .env
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

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Verification

```bash
pytest
ruff check .
mypy app tests generator.py
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
