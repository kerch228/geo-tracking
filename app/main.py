from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.db.session import close_database, wait_for_database


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await wait_for_database()
    try:
        yield
    finally:
        await close_database()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )
    application.include_router(api_router)
    application.mount(
        "/demo",
        StaticFiles(directory=Path(__file__).parent.parent / "web", html=True),
        name="demo",
    )
    return application


app = create_app()
