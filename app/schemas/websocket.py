from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class LocationMessage(BaseModel):
    type: Literal["location"] = "location"
    device_id: str
    lat: float
    lng: float
    timestamp: datetime


class AlertMessage(BaseModel):
    type: Literal["alert"] = "alert"
    device_id: str
    zone_id: str
    zone_name: str
    lat: float
    lng: float
