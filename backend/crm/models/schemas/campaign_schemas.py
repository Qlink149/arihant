from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class CampaignBase(BaseModel):
    name: str
    agent_type: str
    agent_prompt: Optional[str] = None
    filters: dict = {}
    lead_count: int = 0


class CampaignCreate(CampaignBase):
    lead_ids: List[str] = []


class CampaignResponse(CampaignBase):
    model_config = ConfigDict(extra="ignore")
    id: str
    status: str = "draft"
    created_at: datetime
    leads: List[dict] = []
    stats: dict = {}
