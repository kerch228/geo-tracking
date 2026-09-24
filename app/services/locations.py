from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.spatial import make_geography_point
from app.models import DeviceLocation
from app.schemas.location import LocationCreate
from app.schemas.websocket import AlertMessage, LocationMessage
from app.services.geofence import GeofenceService
from app.websocket.manager import connection_manager

IngestionStatus = Literal["accepted", "duplicate", "ignored_stale"]


async def ingest_location(
    session: AsyncSession,
    *,
    user_id: str,
    data: LocationCreate,
) -> IngestionStatus:
    point = make_geography_point(longitude=data.longitude, latitude=data.latitude)
    statement = (
        insert(DeviceLocation)
        .values(
            user_id=user_id,
            device_id=data.device_id,
            timestamp=data.timestamp,
            point=point,
        )
        .on_conflict_do_update(
            index_elements=[DeviceLocation.user_id, DeviceLocation.device_id],
            set_={"timestamp": data.timestamp, "point": point},
            where=DeviceLocation.timestamp < data.timestamp,
        )
        .returning(DeviceLocation.timestamp)
    )
    stored_timestamp = await session.scalar(statement)

    if stored_timestamp is None:
        current_timestamp = await session.scalar(
            select(DeviceLocation.timestamp).where(
                DeviceLocation.user_id == user_id,
                DeviceLocation.device_id == data.device_id,
            )
        )
        status: IngestionStatus = (
            "duplicate" if current_timestamp == data.timestamp else "ignored_stale"
        )
    await session.commit()
    if stored_timestamp is None:
        return status

    matching_zones = await GeofenceService.find_matching_zones(
        session,
        user_id=user_id,
        latitude=data.latitude,
        longitude=data.longitude,
    )
    location_message = LocationMessage(
        device_id=data.device_id,
        lat=data.latitude,
        lng=data.longitude,
        timestamp=data.timestamp,
    )
    messages = [location_message.model_dump(mode="json")]
    messages.extend(
        AlertMessage(
            device_id=data.device_id,
            zone_id=str(zone.id),
            zone_name=zone.name,
            lat=data.latitude,
            lng=data.longitude,
        ).model_dump(mode="json")
        for zone in matching_zones
    )
    await session.rollback()
    await connection_manager.broadcast_many(user_id, messages)
    return "accepted"
