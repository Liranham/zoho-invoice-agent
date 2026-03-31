"""
Simple Telegram notifications.

Sends messages to a Telegram chat via HTTP API.
"""

import logging
import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send Telegram notifications."""

    def __init__(self, bot_token: str, chat_id: str):
        """
        Initialize notifier.

        Args:
            bot_token: Telegram bot token
            chat_id: Telegram chat ID to send messages to
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}"

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Send a text message.

        Args:
            text: Message text
            parse_mode: Message formatting (Markdown or HTML)

        Returns:
            True if sent successfully
        """
        try:
            response = requests.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
                timeout=10,
            )
            response.raise_for_status()
            logger.debug(f"Sent Telegram message: {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
