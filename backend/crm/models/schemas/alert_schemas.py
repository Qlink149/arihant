import uuid
from typing import List

from pydantic import BaseModel, Field


class AlertConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    alert_type: str
    threshold_hours: int = 24
    notification_channels: List[str] = ["email"]
    is_active: bool = True
