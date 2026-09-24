import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout_seconds,
    pool_recycle=settings.db_pool_recycle_seconds,
)
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def wait_for_database() -> None:
    last_error: SQLAlchemyError | None = None

    for attempt in range(1, settings.db_connect_max_attempts + 1):
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            logger.info("Database connection established")
            return
        except SQLAlchemyError as error:
            last_error = error
            logger.warning(
                "Database is not ready (attempt %s/%s)",
                attempt,
                settings.db_connect_max_attempts,
            )
            if attempt < settings.db_connect_max_attempts:
                await asyncio.sleep(settings.db_connect_retry_seconds)

    raise RuntimeError("Database did not become ready in time") from last_error


async def close_database() -> None:
    await engine.dispose()
