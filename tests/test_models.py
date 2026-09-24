from typing import cast

from geoalchemy2 import Geography
from sqlalchemy import Table

from app.db.base import Base
from app.db.spatial import make_geography_point
from app.models import DeviceLocation, Geozone


def test_spatial_columns_use_wgs84_geography_points() -> None:
    geozone_type = Geozone.__table__.c.center.type
    location_type = DeviceLocation.__table__.c.point.type

    assert isinstance(geozone_type, Geography)
    assert isinstance(location_type, Geography)
    assert geozone_type.geometry_type == "POINT"
    assert location_type.geometry_type == "POINT"
    assert geozone_type.srid == 4326
    assert location_type.srid == 4326


def test_geozone_declares_only_required_indexes() -> None:
    table = cast(Table, Geozone.__table__)
    indexes = {index.name: index for index in table.indexes}
    spatial_index = next(
        index for index in table.indexes if index.name == "ix_geozones_center_gist"
    )

    assert set(indexes) == {"ix_geozones_center_gist", "ix_geozones_user_id"}
    assert spatial_index.dialect_options["postgresql"]["using"] == "gist"


def test_device_location_primary_key_supports_device_time_queries() -> None:
    primary_key_columns = [column.name for column in DeviceLocation.__table__.primary_key]
    table = cast(Table, DeviceLocation.__table__)

    assert primary_key_columns == ["device_id", "timestamp"]
    assert not table.indexes


def test_models_are_registered_in_shared_metadata() -> None:
    assert set(Base.metadata.tables) == {"device_locations", "geozones"}


def test_make_geography_point_uses_longitude_latitude_order() -> None:
    point = make_geography_point(longitude=30.5234, latitude=50.4501)

    assert str(point) == "POINT(30.5234 50.4501)"
    assert point.srid == 4326
