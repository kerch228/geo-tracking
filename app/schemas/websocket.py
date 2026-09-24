from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class LocationMessage(BaseModel):
    type: Literal["location"] = "location"
    device_id: str
    lat: float
    lng: float
    timestamp: datetime
