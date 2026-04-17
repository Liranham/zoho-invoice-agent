"""
Gmail label watcher for Wise transfer notifications.

Monitors the "Pacific wise transfers" label and processes new emails.
"""

import base64
import logging
from typing import Optional

from gmail.auth import GmailAuth
from gmail.parser import WiseEmailParser, WireTransfer

logger = logging.getLogger(__name__)


class GmailWatcher:
    """Watch Gmail label for new Wise transfer emails."""

    def __init__(self, auth: GmailAuth, label_name: str = "Pacific wise transfers"):
        """
        Initialize watcher.

        Args:
            auth: GmailAuth instance
            label_name: Gmail label to monitor
        """
        self.auth = auth
        self.label_name = label_name
        self.service = None
        self._label_id: Optional[str] = None
        self._processed_label_id: Optional[str] = None  # "Invoice Created" label

    def initialize(self):
        """Build Gmail service and find label ID."""
        self.service = self.auth.build_service()
        self._label_id = self._get_label_id()
        if not self._label_id:
            raise ValueError(f"Label '{self.label_name}' not found in Gmail")
        logger.info(f"Watching label: {self.label_name} (ID: {self._label_id})")

        # Get or create "Invoice Created" label for tracking
        self._processed_label_id = self._get_or_create_label("Invoice Created")
        logger.info(f"Tracking processed emails with label: Invoice Created (ID: {self._processed_label_id})")

    def _get_label_id(self) -> Optional[str]:
        """Find label ID by name."""
        try:
            labels = self.service.users().labels().list(userId="me").execute()
            for label in labels.get("labels", []):
                if label["name"] == self.label_name:
                    return label["id"]
        except Exception as e:
            logger.error(f"Failed to get labels: {e}")
        return None

    def _get_or_create_label(self, label_name: str) -> str:
        """Get or create a Gmail label, return its ID."""
        try:
            # Check if label exists
            labels = self.service.users().labels().list(userId="me").execute()
            for label in labels.get("labels", []):
                if label["name"] == label_name:
                    return label["id"]

            # Create label if it doesn't exist
            label_object = {
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show"
            }
            created = self.service.users().labels().create(userId="me", body=label_object).execute()
            logger.info(f"Created label: {label_name} (ID: {created['id']})")
            return created["id"]

        except Exception as e:
            logger.error(f"Failed to get/create label '{label_name}': {e}")
            raise

    def mark_as_processed(self, message_id: str) -> bool:
        """
        Mark a message as processed by adding the 'Invoice Created' label.

        Args:
            message_id: Gmail message ID

        Returns:
            True if successful
        """
        try:
            self.service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [self._processed_label_id]}
            ).execute()
            logger.info(f"Marked message {message_id} as processed")
            return True
        except Exception as e:
            logger.error(f"Failed to mark message {message_id} as processed: {e}")
            return False

    def setup_push_notifications(self, webhook_url: str, topic_name: str):
        """
        Set up Gmail push notifications via Pub/Sub.

        Args:
            webhook_url: Your webhook endpoint URL
            topic_name: GCP Pub/Sub topic name (e.g., "projects/myproject/topics/gmail")

        Note: Requires GCP Pub/Sub topic configured to push to webhook_url
        """
        try:
            request = {
                "labelIds": [self._label_id],
                "topicName": topic_name,
            }
            self.service.users().watch(userId="me", body=request).execute()
            logger.info(f"Push notifications enabled for label {self.label_name}")
        except Exception as e:
            logger.error(f"Failed to enable push notifications: {e}")
            raise

    def get_message(self, message_id: str) -> Optional[WireTransfer]:
        """
        Fetch and parse a specific message.

        Args:
            message_id: Gmail message ID

        Returns:
            Parsed WireTransfer or None
        """
        try:
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            # Extract email body
            body = self._extract_body(msg)
            if not body:
                logger.warning(f"No body found in message {message_id}")
                return None

            # Extract date
            headers = msg.get("payload", {}).get("headers", [])
            date = next((h["value"] for h in headers if h["name"].lower() == "date"), None)

            # Parse wire transfer
            transfer = WiseEmailParser.parse(body, date)
            if transfer:
                transfer.message_id = message_id  # Store message ID for tracking
            return transfer

        except Exception as e:
            logger.error(f"Failed to get message {message_id}: {e}")
            return None

    def _extract_body(self, message: dict) -> Optional[str]:
        """Extract plain text body from Gmail message."""
        payload = message.get("payload", {})

        # Check if body is directly in payload
        if "body" in payload and payload["body"].get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")

        # Check multipart
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")

            # Check nested parts
            if "parts" in part:
                for subpart in part["parts"]:
                    if (
                        subpart.get("mimeType") == "text/plain"
                        and subpart.get("body", {}).get("data")
                    ):
                        return base64.urlsafe_b64decode(subpart["body"]["data"]).decode(
                            "utf-8"
                        )

        return None

    def poll_recent_messages(self, max_results: int = 10) -> list:
        """
        Poll for recent messages in the label (for testing/manual trigger).
        Only returns unprocessed messages (without "Invoice Created" label).

        Args:
            max_results: Number of recent messages to check

        Returns:
            List of WireTransfer objects
        """
        try:
            # Build query to exclude processed messages
            query = f"label:{self.label_name} -label:Invoice-Created"

            results = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )

            messages = results.get("messages", [])
            transfers = []

            logger.info(f"Found {len(messages)} unprocessed messages")

            for msg_ref in messages:
                transfer = self.get_message(msg_ref["id"])
                if transfer:
                    transfers.append(transfer)

            return transfers

        except Exception as e:
            logger.error(f"Failed to poll messages: {e}")
            return []
