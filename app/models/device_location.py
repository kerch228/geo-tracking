from datetime import datetime

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DeviceLocation(Base):
    __tablename__ = "device_locations"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(device_id)) > 0",
            name="ck_device_locations_device_id_not_empty",
        ),
    )

    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
    )
    point: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
