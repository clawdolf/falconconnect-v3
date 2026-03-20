"""Telegram alert service — sends operational alerts to Seb.

Used for critical system notifications (GCal failures, webhook issues, etc.)
NOT for user-facing messages. This is an internal ops alerting channel.

Required env vars:
  TELEGRAM_BOT_TOKEN  — Bot API token (from @BotFather)
  TELEGRAM_CHAT_ID    — Chat ID for alerts (default: 1766688081)
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("falconconnect.telegram_alerts")

# Seb's Telegram chat ID for ops alerts
DEFAULT_CHAT_ID = "1766688081"


async def send_telegram_alert(
    message: str,
    *,
    chat_id: Optional[str] = None,
    thread_id: Optional[int] = None,
) -> bool:
    """Send an alert message via Telegram bot.

    Args:
        message: Alert text (supports Telegram MarkdownV2 or plain text).
        chat_id: Override chat ID (defaults to TELEGRAM_CHAT_ID env or Seb's DM).
        thread_id: Optional message_thread_id for topic-based groups.

    Returns True if sent successfully, False otherwise.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not configured — cannot send alert")
        return False

    target_chat = chat_id or os.environ.get("TELEGRAM_CHAT_ID", DEFAULT_CHAT_ID)

    payload: dict = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": "HTML",
    }
    if thread_id:
        payload["message_thread_id"] = thread_id

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json=payload,
            )
            if resp.status_code == 200:
                logger.info("Telegram alert sent to %s", target_chat)
                return True
            else:
                logger.error(
                    "Telegram alert failed: %s %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
    except Exception as exc:
        logger.error("Telegram alert send error: %s", exc)
        return False
