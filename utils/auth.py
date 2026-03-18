"""Authentication and authorization utilities."""

import hmac
import logging
from typing import Optional

from fastapi import Header, HTTPException, status

from config import get_settings

logger = logging.getLogger("falconconnect.auth")


async def verify_webhook_secret(
    x_ghl_webhook_secret: Optional[str] = Header(None, alias="X-GHL-Webhook-Secret"),
) -> str:
    """FastAPI dependency — verify the GHL webhook shared secret header.

    Raises 401 if the header is missing or doesn't match.
    """
    settings = get_settings()
    expected = settings.ghl_webhook_secret

    if not expected:
        logger.warning("GHL_WEBHOOK_SECRET not configured — rejecting all webhooks")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook secret not configured on server",
        )

    if not x_ghl_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-GHL-Webhook-Secret header",
        )

    if not hmac.compare_digest(x_ghl_webhook_secret, expected):
        logger.warning("Webhook secret mismatch — rejecting request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret",
        )

    return x_ghl_webhook_secret


def verify_calendar_token(token: Optional[str]) -> None:
    """Verify the iCal feed token query parameter.

    Raises 403 if token is missing or doesn't match CALENDAR_SECRET.
    """
    settings = get_settings()

    if not settings.calendar_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Calendar secret not configured",
        )

    if not token or not hmac.compare_digest(token, settings.calendar_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing calendar token",
        )
