"""
Automated invoice creation from Gmail notifications.

Connects Gmail watcher to Zoho invoice templates.
"""

import logging
from typing import Optional

from gmail.watcher import GmailWatcher, WireTransfer
from invoice_templates import InvoiceGenerator
from zoho.invoices import InvoiceService

logger = logging.getLogger(__name__)


# Client name mapping (for fuzzy matching)
CLIENT_MAPPING = {
    "GILAD WEINBERG": "8399034000000100025",  # Zoho customer ID
    "AMZEXPERTGLOBALL": "8399034000000100007",  # Amz-expert global ltd
    "AMZ-EXPERT": "8399034000000100007",  # Alternative matching
}


class InvoiceAutomation:
    """Automate invoice creation from wire transfer emails."""

    def __init__(
        self,
        watcher: GmailWatcher,
        invoice_service: InvoiceService,
        telegram_notifier=None,
    ):
        """
        Initialize automation.

        Args:
            watcher: GmailWatcher instance
            invoice_service: InvoiceService instance
            telegram_notifier: Optional Telegram notifier for confirmations
        """
        self.watcher = watcher
        self.invoice_service = invoice_service
        self.telegram = telegram_notifier

    def process_transfer(self, transfer: WireTransfer) -> bool:
        """
        Process a wire transfer and create invoice.

        Args:
            transfer: WireTransfer object

        Returns:
            True if invoice created successfully
        """
        logger.info(
            f"Processing transfer: ${transfer.amount:.2f} from {transfer.sender_name}"
        )

        # Match to client
        customer_id = self._match_client(transfer.sender_name)
        if not customer_id:
            logger.error(f"No client match for sender: {transfer.sender_name}")
            if self.telegram:
                self.telegram.send_message(
                    f"⚠️ Unknown sender: {transfer.sender_name}\n"
                    f"Amount: ${transfer.amount:.2f}\n"
                    f"Cannot auto-create invoice."
                )
            return False

        # Generate invoice data
        try:
            invoice_data = InvoiceGenerator.generate_invoice_data(
                client_name=transfer.sender_name,
                wire_amount=transfer.amount,
                wire_date=transfer.date,
                customer_id=customer_id,
            )
        except ValueError as e:
            logger.error(f"No template for client {transfer.sender_name}: {e}")
            if self.telegram:
                self.telegram.send_message(
                    f"⚠️ No invoice template for: {transfer.sender_name}\n"
                    f"Amount: ${transfer.amount:.2f}"
                )
            return False

        # Create invoice
        try:
            invoice = self.invoice_service.create_invoice(**invoice_data)
            logger.info(
                f"Created invoice: {invoice.invoice_number} | ${invoice.total:.2f}"
            )

            # Mark email as processed to prevent duplicates
            if transfer.message_id:
                self.watcher.mark_as_processed(transfer.message_id)

            # Send confirmation
            if self.telegram:
                self.telegram.send_message(
                    f"✅ Invoice created!\n"
                    f"Number: {invoice.invoice_number}\n"
                    f"Client: {transfer.sender_name}\n"
                    f"Amount: ${invoice.total:.2f}\n"
                    f"Status: {invoice.status}"
                )

            return True

        except Exception as e:
            logger.exception(f"Failed to create invoice: {e}")
            if self.telegram:
                self.telegram.send_message(
                    f"❌ Failed to create invoice\n"
                    f"Client: {transfer.sender_name}\n"
                    f"Amount: ${transfer.amount:.2f}\n"
                    f"Error: {str(e)}"
                )
            return False

    def process_message(self, message_id: str) -> bool:
        """
        Process a single Gmail message and create invoice.

        Args:
            message_id: Gmail message ID

        Returns:
            True if invoice created successfully
        """
        logger.info(f"Processing message {message_id}")

        # Get and parse message
        transfer = self.watcher.get_message(message_id)
        if not transfer:
            logger.warning(f"Failed to parse message {message_id}")
            return False

        return self.process_transfer(transfer)

    def _match_client(self, sender_name: str) -> Optional[str]:
        """
        Match sender name to Zoho customer ID.

        Args:
            sender_name: Sender name from email

        Returns:
            Zoho customer ID or None
        """
        normalized = sender_name.upper().strip()

        # Exact match
        if normalized in CLIENT_MAPPING:
            return CLIENT_MAPPING[normalized]

        # Partial match
        for key, customer_id in CLIENT_MAPPING.items():
            if key in normalized or normalized in key:
                return customer_id

        return None
