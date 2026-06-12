"""
Simple Telegram notifications.

Sends messages to a Telegram chat via HTTP API. All outbound text flows
through utils.telegram_format so any LLM-style markdown (`**bold**`,
`# Heading`, pipe tables, `[label](url)`) renders as proper HTML instead
of arriving as literal characters in the Telegram client.
"""

import logging
import requests

from utils.telegram_format import telegram_format

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

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Send a text message.

        Args:
            text: Message text (markdown or plain — runs through
                telegram_format so LLM-style markdown converts cleanly).
            parse_mode: Message formatting. Defaults to "HTML" because
                telegram_format emits HTML; pass "Markdown" only if you
                want to bypass the formatter (legacy behaviour).

        Returns:
            True if sent successfully.
        """
        try:
            body = telegram_format(text or "") if parse_mode == "HTML" else text
            response = requests.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": body,
                    "parse_mode": parse_mode,
                },
                timeout=10,
            )
            response.raise_for_status()
            logger.debug(f"Sent Telegram message: {body[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def send_message_with_buttons(self, text: str, buttons: list[list[dict]]) -> bool:
        """Send a message with an inline keyboard.

        Args:
            text: Message text (plain — no parse_mode to keep callbacks robust).
            buttons: 2D list of {text, callback_data} dicts forming the keyboard.

        Returns:
            True on success.
        """
        try:
            response = requests.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "reply_markup": {"inline_keyboard": buttons},
                },
                timeout=10,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message with buttons: {e}")
            return False

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> bool:
        """Acknowledge a button press so the user's UI updates."""
        try:
            response = requests.post(
                f"{self.api_url}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": text},
                timeout=10,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to answer callback query: {e}")
            return False

    def edit_message_text(self, chat_id: int, message_id: int, text: str) -> bool:
        """Edit the original message after a button is pressed (clears keyboard)."""
        try:
            response = requests.post(
                f"{self.api_url}/editMessageText",
                json={"chat_id": chat_id, "message_id": message_id, "text": text},
                timeout=10,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to edit Telegram message: {e}")
            return False
