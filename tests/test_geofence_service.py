from app.services.geofence import GeofenceService


def test_matching_query_compiles_to_postgis_st_dwithin() -> None:
    query = GeofenceService.build_matching_zones_query(
        user_id="user-123",
        latitude=50.4501,
        longitude=30.5234,
    )

    sql = str(query)

    assert "ST_DWithin" in sql
    assert "geozones.user_id" in sql
    assert "geozones.radius_meters" in sql
    assert "geography(POINT,4326)" in sql
