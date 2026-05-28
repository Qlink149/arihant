from typing import List, Optional

from pydantic import BaseModel


class WhatsAppMessage(BaseModel):
    destination: str
    message_type: str = "text"
    text: Optional[str] = None
    template_id: Optional[str] = None
    template_params: Optional[List[str]] = None
    media_url: Optional[str] = None
    media_filename: Optional[str] = None


class WhatsAppMessageResponse(BaseModel):
    status: str
    message_id: Optional[str] = None
    error: Optional[str] = None
