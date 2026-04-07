"""SMS template management API — CRUD for editable appointment reminder templates."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.models import SmsTemplate
from middleware.auth import require_auth

logger = logging.getLogger("falconconnect.sms_templates")

router = APIRouter()


class TemplateOut(BaseModel):
    template_key: str
    body: str
    updated_at: str | None = None


class TemplateUpdateIn(BaseModel):
    body: str


@router.get("/sms-templates", response_model=list[TemplateOut])
async def list_templates(
    user=Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    """Return all SMS templates."""
    result = await session.execute(
        select(SmsTemplate).order_by(SmsTemplate.template_key)
    )
    templates = result.scalars().all()
    return [
        TemplateOut(
            template_key=t.template_key,
            body=t.body,
            updated_at=t.updated_at.isoformat() if t.updated_at else None,
        )
        for t in templates
    ]


@router.put("/sms-templates/{key}", response_model=TemplateOut)
async def update_template(
    key: str,
    data: TemplateUpdateIn,
    user=Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    """Update an SMS template body."""
    if key not in ("confirmation", "reminder_24hr", "reminder_1hr", "r1_done", "r2_done", "r3_done"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid template key: {key}",
        )

    result = await session.execute(
        select(SmsTemplate).where(SmsTemplate.template_key == key)
    )
    template = result.scalar_one_or_none()

    if not template:
        # Create if it doesn't exist yet
        template = SmsTemplate(template_key=key, body=data.body)
        session.add(template)
    else:
        template.body = data.body
        template.updated_at = datetime.now(timezone.utc)

    await session.flush()

    logger.info("SMS template '%s' updated by user %s", key, user.get("sub", "unknown"))

    return TemplateOut(
        template_key=template.template_key,
        body=template.body,
        updated_at=template.updated_at.isoformat() if template.updated_at else None,
    )
