"""Pydantic models for GHL webhook payloads."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class GHLWebhookPayload(BaseModel):
    """Incoming GHL webhook event payload.

    GHL sends varied shapes depending on event type.
    We capture the common fields and keep the rest in raw_data.
    """

    type: str = Field(..., description="Event type, e.g. 'appointment.booked'")
    locationId: Optional[str] = None
    contactId: Optional[str] = None
    appointmentId: Optional[str] = None
    opportunityId: Optional[str] = None
    calendarId: Optional[str] = None
    startTime: Optional[str] = None
    endTime: Optional[str] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    pipelineId: Optional[str] = None

    # Catch-all for any extra fields GHL sends
    raw_data: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "allow"
