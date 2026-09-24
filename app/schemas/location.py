from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LocationCreate(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timestamp: datetime

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, value: str) -> str:
        device_id = value.strip()
        if not device_id:
            raise ValueError("device_id must not be empty")
        return device_id

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value


class LocationAccepted(BaseModel):
    status: Literal["accepted", "duplicate", "ignored_stale"]
    device_id: str
    timestamp: datetime
