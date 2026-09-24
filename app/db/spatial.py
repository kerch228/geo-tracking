from geoalchemy2.elements import WKTElement


def make_geography_point(*, longitude: float, latitude: float) -> WKTElement:
    """Create a WGS84 point; PostGIS point coordinates are longitude, latitude."""
    return WKTElement(f"POINT({longitude!r} {latitude!r})", srid=4326)
