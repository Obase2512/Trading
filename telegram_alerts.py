"""Secure Telegram delivery for Trading Sentinel research/paper alerts.

Never log a bot token, Telegram URL, or sensitive API response.
"""
import os

import requests


def send_telegram(message, token=None, chat_id=None):
    """Send plain-text Telegram alert. Raises sanitized errors."""
    token = token if token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise ValueError("Telegram configuration missing: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
    try:
        response = requests.post(
            "https://api.telegram.org/bot" + token + "/sendMessage",
            data={"chat_id": str(chat_id), "text": str(message)[:4000],
                  "disable_web_page_preview": "true"},
            timeout=20,
        )
    except requests.RequestException:
        # requests errors may expose URLs, including tokens. Do not propagate.
        raise RuntimeError("Telegram network request failed; verify connectivity.") from None
    if response.status_code != 200:
        raise RuntimeError(
            "Telegram API returned HTTP " + str(response.status_code)
            + "; confirm token, chat ID, and press Start in the bot chat."
        )
    try:
        result = response.json()
    except ValueError:
        raise RuntimeError("Telegram returned a malformed response.") from None
    if result.get("ok") is not True:
        raise RuntimeError("Telegram rejected the message; check bot setup.")
    return True
