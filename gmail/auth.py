"""
Gmail OAuth2 authentication.

Handles token refresh and API client initialization.
"""

import base64
import json
import logging
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


class GmailAuth:
    """Gmail API authentication manager."""

    def __init__(
        self,
        credentials_b64: str,
        token_b64: str,
    ):
        """
        Initialize Gmail auth from base64-encoded credentials.

        Args:
            credentials_b64: Base64-encoded credentials.json
            token_b64: Base64-encoded token.json
        """
        self.credentials_b64 = credentials_b64
        self.token_b64 = token_b64
        self._creds: Optional[Credentials] = None

    def get_credentials(self) -> Credentials:
        """Get valid credentials, refreshing if needed."""
        if self._creds and self._creds.valid:
            return self._creds

        # Decode token
        token_json = base64.b64decode(self.token_b64).decode("utf-8")
        token_data = json.loads(token_json)

        # Create credentials
        self._creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes"),
        )

        # Refresh if expired
        if not self._creds.valid and self._creds.expired and self._creds.refresh_token:
            logger.info("Refreshing Gmail access token...")
            self._creds.refresh(Request())

        return self._creds

    def build_service(self):
        """Build Gmail API service."""
        creds = self.get_credentials()
        return build("gmail", "v1", credentials=creds)
