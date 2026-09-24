from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class GeozoneWrite(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    center_lat: float = Field(ge=-90, le=90)
    center_lng: float = Field(ge=-180, le=180)
    radius_meters: float = Field(gt=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("name must not be empty")
        return name


class GeozoneCreate(GeozoneWrite):
    pass


class GeozoneUpdate(GeozoneWrite):
    pass


class GeozoneRead(GeozoneWrite):
    id: int
    user_id: str
    created_at: datetime
    updated_at: datetime
