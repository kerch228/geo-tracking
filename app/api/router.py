from fastapi import APIRouter

from app.api.routes.geozones import router as geozones_router
from app.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(geozones_router)
