from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_id
from app.db.session import get_db_session
from app.schemas.location import LocationAccepted, LocationCreate
from app.services import locations as location_service

router = APIRouter(prefix="/locations", tags=["locations"])

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUserId = Annotated[str, Depends(get_current_user_id)]


@router.post(
    "",
    response_model=LocationAccepted,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_location(
    data: LocationCreate,
    response: Response,
    session: DatabaseSession,
    user_id: CurrentUserId,
) -> LocationAccepted:
    ingestion_status = await location_service.ingest_location(
        session,
        user_id=user_id,
        data=data,
    )
    response.status_code = (
        status.HTTP_201_CREATED
        if ingestion_status == "accepted"
        else status.HTTP_200_OK
    )
    return LocationAccepted(
        status=ingestion_status,
        device_id=data.device_id,
        timestamp=data.timestamp,
    )
