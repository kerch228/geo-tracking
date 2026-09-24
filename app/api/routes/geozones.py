from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_id
from app.db.session import get_db_session
from app.schemas.geozone import GeozoneCreate, GeozoneRead, GeozoneUpdate
from app.services import geozones as geozone_service

router = APIRouter(prefix="/geozones", tags=["geozones"])

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
GeozoneId = Annotated[int, Path(gt=0)]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Geozone not found",
    )


@router.post("", response_model=GeozoneRead, status_code=status.HTTP_201_CREATED)
async def create_geozone(
    data: GeozoneCreate,
    session: DatabaseSession,
    user_id: CurrentUserId,
) -> GeozoneRead:
    return await geozone_service.create_geozone(session, user_id=user_id, data=data)


@router.get("", response_model=list[GeozoneRead])
async def list_geozones(
    session: DatabaseSession,
    user_id: CurrentUserId,
) -> list[GeozoneRead]:
    return await geozone_service.list_geozones(session, user_id=user_id)


@router.get("/{geozone_id}", response_model=GeozoneRead)
async def get_geozone(
    geozone_id: GeozoneId,
    session: DatabaseSession,
    user_id: CurrentUserId,
) -> GeozoneRead:
    geozone = await geozone_service.get_geozone(
        session,
        geozone_id=geozone_id,
        user_id=user_id,
    )
    if geozone is None:
        raise _not_found()
    return geozone


@router.put("/{geozone_id}", response_model=GeozoneRead)
async def update_geozone(
    geozone_id: GeozoneId,
    data: GeozoneUpdate,
    session: DatabaseSession,
    user_id: CurrentUserId,
) -> GeozoneRead:
    geozone = await geozone_service.update_geozone(
        session,
        geozone_id=geozone_id,
        user_id=user_id,
        data=data,
    )
    if geozone is None:
        raise _not_found()
    return geozone


@router.delete("/{geozone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_geozone(
    geozone_id: GeozoneId,
    session: DatabaseSession,
    user_id: CurrentUserId,
) -> Response:
    deleted = await geozone_service.delete_geozone(
        session,
        geozone_id=geozone_id,
        user_id=user_id,
    )
    if not deleted:
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
