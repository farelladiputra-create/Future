"""Telegram delivery.

Easiest channel to set up for a daily push to a phone: message @BotFather to
create a bot, then send it one message and read the chat id from
/getUpdates. No server, no OAuth.
"""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 20.0


def send(text: str, *, token: str | None = None, chat_id: str | None = None) -> bool:
    """Send one message. Returns False and logs rather than raising."""
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.info("telegram not configured, skipping")
        return False

    try:
        response = requests.post(
            API_URL.format(token=token),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        log.warning("telegram send failed: %s", exc)
        return False

    if response.status_code != 200:
        log.warning(
            "telegram rejected the message (%s): %s",
            response.status_code,
            response.text[:300],
        )
        return False
    return True
