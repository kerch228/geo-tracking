from datetime import datetime

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement, WKTElement
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Geozone(Base):
    __tablename__ = "geozones"
    __table_args__ = (
        CheckConstraint("radius_meters > 0", name="ck_geozones_radius_positive"),
        CheckConstraint("char_length(btrim(user_id)) > 0", name="ck_geozones_user_id_not_empty"),
        Index("ix_geozones_user_id", "user_id"),
        Index("ix_geozones_center_gist", "center", postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    center: Mapped[WKBElement | WKTElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    radius_meters: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
