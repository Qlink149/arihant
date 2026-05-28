import uuid

from pydantic import BaseModel, Field


class AssignmentRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    rule_type: str
    config: dict = {}
    is_active: bool = True
