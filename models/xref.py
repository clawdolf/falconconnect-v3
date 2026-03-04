"""Pydantic read-model for LeadXref (API responses, not ORM)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class LeadXrefRead(BaseModel):
    """Serializable view of a lead cross-reference record."""

    id: int
    ghl_contact_id: str
    notion_page_id: str
    phone: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
