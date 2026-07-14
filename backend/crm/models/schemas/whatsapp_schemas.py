from typing import List, Optional

from pydantic import BaseModel


class WhatsAppMessage(BaseModel):
    destination: str
    message_type: str = "text"  # text | template | document
    text: Optional[str] = None

    # Legacy Gupshup fields (kept for backward compat — not used when provider=wati)
    template_id: Optional[str] = None
    template_params: Optional[List[str]] = None

    # WATI fields
    # template_name: WATI elementName (e.g. "welcome_v1"); required for out-of-session sends
    template_name: Optional[str] = None
    # template_parameters: list of {name, value} dicts matching WATI ParametersModel
    template_parameters: Optional[List[dict]] = None
    # broadcast_name: label for WATI broadcast tracking (defaults to "arihant_crm" if not set)
    broadcast_name: Optional[str] = None

    # Media (shared Gupshup/WATI)
    media_url: Optional[str] = None
    media_filename: Optional[str] = None


class WhatsAppMessageResponse(BaseModel):
    status: str
    message_id: Optional[str] = None
    error: Optional[str] = None
