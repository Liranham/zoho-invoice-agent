"""
Parse Wise transfer notification emails to extract invoice data.

Email format:
    "You received 2,793.89 USD from GILAD WEINBERG &."
"""

import re
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class WireTransfer:
    """Parsed wire transfer data."""

    amount: float
    currency: str
    sender_name: str
    date: str  # YYYY-MM-DD
    message_id: str = ""  # Gmail message ID for tracking


class WiseEmailParser:
    """Parse Wise transfer notification emails."""

    # Pattern: "You received 2,793.89 USD from GILAD WEINBERG &."
    AMOUNT_PATTERN = re.compile(
        r"You received\s+([\d,]+\.?\d*)\s+([A-Z]{3})\s+from\s+(.+?)\."
    )

    @classmethod
    def parse(cls, email_body: str, email_date: str = None) -> Optional[WireTransfer]:
        """
        Parse Wise transfer email.

        Args:
            email_body: Email text content
            email_date: Email date (RFC 2822 format or epoch ms)

        Returns:
            WireTransfer object or None if parsing fails
        """
        # Extract amount, currency, and sender
        match = cls.AMOUNT_PATTERN.search(email_body)
        if not match:
            logger.warning("No wire transfer pattern found in email")
            return None

        amount_str = match.group(1).replace(",", "")
        currency = match.group(2)
        sender_raw = match.group(3).strip()

        # Clean sender name (remove trailing &, punctuation)
        sender_name = sender_raw.rstrip("& .")

        # Parse date
        if email_date:
            try:
                # Try epoch milliseconds first
                if email_date.isdigit():
                    dt = datetime.fromtimestamp(int(email_date) / 1000)
                else:
                    # Try RFC 2822 format
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(email_date)
                date = dt.strftime("%Y-%m-%d")
            except Exception as e:
                logger.warning(f"Failed to parse date '{email_date}': {e}")
                date = datetime.now().strftime("%Y-%m-%d")
        else:
            date = datetime.now().strftime("%Y-%m-%d")

        try:
            amount = float(amount_str)
        except ValueError:
            logger.error(f"Invalid amount: {amount_str}")
            return None

        return WireTransfer(
            amount=amount,
            currency=currency,
            sender_name=sender_name,
            date=date,
        )
