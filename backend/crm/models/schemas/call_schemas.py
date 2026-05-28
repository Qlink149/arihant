from typing import List, Optional

from pydantic import BaseModel


class CallSummary(BaseModel):
    lead_id: str
    transcript: str
    summary: Optional[str] = None
    intent_level: str = "neutral"
    key_points: List[str] = []
    next_steps: Optional[str] = None
