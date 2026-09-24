from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import RowMapping, Select, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.spatial import make_geography_point
from app.models import Geozone
from app.schemas.geozone import GeozoneCreate, GeozoneRead, GeozoneUpdate


def _geozone_projection() -> Select[Any]:
    geometry = cast(
        Geozone.center,
        Geometry(geometry_type="POINT", srid=4326),
    )
    return select(
        Geozone.id,
        Geozone.user_id,
        Geozone.name,
        func.ST_Y(geometry).label("center_lat"),
        func.ST_X(geometry).label("center_lng"),
        Geozone.radius_meters,
        Geozone.created_at,
        Geozone.updated_at,
    )


def _to_schema(row: RowMapping) -> GeozoneRead:
    return GeozoneRead.model_validate(dict(row))


async def _read_by_id(
    session: AsyncSession,
    *,
    geozone_id: int,
    user_id: str,
) -> GeozoneRead | None:
    result = await session.execute(
        _geozone_projection().where(
            Geozone.id == geozone_id,
            Geozone.user_id == user_id,
        )
    )
    row = result.mappings().one_or_none()
    return _to_schema(row) if row is not None else None


async def create_geozone(
    session: AsyncSession,
    *,
    user_id: str,
    data: GeozoneCreate,
) -> GeozoneRead:
    geozone = Geozone(
        user_id=user_id,
        name=data.name,
        center=make_geography_point(
            longitude=data.center_lng,
            latitude=data.center_lat,
        ),
        radius_meters=data.radius_meters,
    )
    session.add(geozone)
    await session.flush()

    response = await _read_by_id(session, geozone_id=geozone.id, user_id=user_id)
    if response is None:
        raise RuntimeError("Created geozone could not be loaded")
    await session.commit()
    return response


async def list_geozones(session: AsyncSession, *, user_id: str) -> list[GeozoneRead]:
    result = await session.execute(
        _geozone_projection().where(Geozone.user_id == user_id).order_by(Geozone.id)
    )
    return [_to_schema(row) for row in result.mappings()]


async def get_geozone(
    session: AsyncSession,
    *,
    geozone_id: int,
    user_id: str,
) -> GeozoneRead | None:
    return await _read_by_id(session, geozone_id=geozone_id, user_id=user_id)


async def update_geozone(
    session: AsyncSession,
    *,
    geozone_id: int,
    user_id: str,
    data: GeozoneUpdate,
) -> GeozoneRead | None:
    geozone = await session.scalar(
        select(Geozone)
        .where(Geozone.id == geozone_id, Geozone.user_id == user_id)
        .with_for_update()
    )
    if geozone is None:
        return None

    geozone.name = data.name
    geozone.center = make_geography_point(
        longitude=data.center_lng,
        latitude=data.center_lat,
    )
    geozone.radius_meters = data.radius_meters
    await session.flush()

    response = await _read_by_id(session, geozone_id=geozone.id, user_id=user_id)
    if response is None:
        raise RuntimeError("Updated geozone could not be loaded")
    await session.commit()
    return response


async def delete_geozone(
    session: AsyncSession,
    *,
    geozone_id: int,
    user_id: str,
) -> bool:
    geozone = await session.scalar(
        select(Geozone)
        .where(Geozone.id == geozone_id, Geozone.user_id == user_id)
        .with_for_update()
    )
    if geozone is None:
        return False

    await session.delete(geozone)
    await session.commit()
    return True
