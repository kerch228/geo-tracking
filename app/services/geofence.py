from geoalchemy2 import Geography
from sqlalchemy import Select, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.spatial import make_geography_point
from app.models import Geozone


class GeofenceService:
    @staticmethod
    def build_matching_zones_query(
        *,
        user_id: str,
        latitude: float,
        longitude: float,
    ) -> Select[tuple[Geozone]]:
        device_point = cast(
            make_geography_point(
                longitude=longitude,
                latitude=latitude,
            ),
            Geography(geometry_type="POINT", srid=4326),
        )
        return (
            select(Geozone)
            .where(
                Geozone.user_id == user_id,
                func.ST_DWithin(
                    Geozone.center,
                    device_point,
                    Geozone.radius_meters,
                ),
            )
            .order_by(Geozone.id)
        )

    @classmethod
    async def find_matching_zones(
        cls,
        session: AsyncSession,
        *,
        user_id: str,
        latitude: float,
        longitude: float,
    ) -> list[Geozone]:
        query = cls.build_matching_zones_query(
            user_id=user_id,
            latitude=latitude,
            longitude=longitude,
        )
        result = await session.scalars(query)
        return list(result.all())
