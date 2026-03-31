import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class ZohoAuthSettings:
    """Zoho OAuth2 configuration."""

    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    accounts_url: str = "https://accounts.zoho.com"
    api_base_url: str = "https://www.zohoapis.com/books/v3"
    organization_id: str = ""

    def __post_init__(self):
        self.client_id = os.getenv("ZOHO_CLIENT_ID", "")
        self.client_secret = os.getenv("ZOHO_CLIENT_SECRET", "")
        self.refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "")
        self.accounts_url = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com")
        self.api_base_url = os.getenv(
            "ZOHO_API_BASE_URL", "https://www.zohoapis.com/books/v3"
        )
        self.organization_id = os.getenv("ZOHO_ORGANIZATION_ID", "")


@dataclass
class InvoiceDefaults:
    """Default values for invoice creation."""

    default_customer_id: str = ""
    default_item_id: str = ""
    payment_terms: int = 30

    def __post_init__(self):
        self.default_customer_id = os.getenv("ZOHO_DEFAULT_CUSTOMER_ID", "")
        self.default_item_id = os.getenv("ZOHO_DEFAULT_ITEM_ID", "")
        self.payment_terms = int(os.getenv("ZOHO_PAYMENT_TERMS", "30"))


@dataclass
class SchedulerSettings:
    """Scheduled job configuration."""

    enabled: bool = False
    recurring_cron: str = ""

    def __post_init__(self):
        self.enabled = os.getenv("SCHEDULER_ENABLED", "false").lower() == "true"
        self.recurring_cron = os.getenv("SCHEDULER_RECURRING_CRON", "")


@dataclass
class GmailSettings:
    """Gmail API configuration for email monitoring."""

    enabled: bool = False
    credentials_b64: str = ""
    token_b64: str = ""
    label_name: str = "Pacific wise transfers"
    pubsub_topic: str = ""

    def __post_init__(self):
        self.enabled = os.getenv("GMAIL_ENABLED", "false").lower() == "true"
        self.credentials_b64 = os.getenv("GMAIL_CREDENTIALS_B64", "")
        self.token_b64 = os.getenv("GMAIL_TOKEN_B64", "")
        self.label_name = os.getenv("GMAIL_LABEL_NAME", "Pacific wise transfers")
        self.pubsub_topic = os.getenv("GMAIL_PUBSUB_TOPIC", "")


@dataclass
class TelegramSettings:
    """Telegram bot configuration for notifications."""

    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""

    def __post_init__(self):
        self.enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")


@dataclass
class Settings:
    """Root settings container."""

    zoho_auth: ZohoAuthSettings = field(default_factory=ZohoAuthSettings)
    invoice_defaults: InvoiceDefaults = field(default_factory=InvoiceDefaults)
    scheduler: SchedulerSettings = field(default_factory=SchedulerSettings)
    gmail: GmailSettings = field(default_factory=GmailSettings)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)

    def __post_init__(self):
        pass

    def validate(self):
        """Raise if required Zoho credentials are missing."""
        missing = []
        if not self.zoho_auth.client_id:
            missing.append("ZOHO_CLIENT_ID")
        if not self.zoho_auth.client_secret:
            missing.append("ZOHO_CLIENT_SECRET")
        if not self.zoho_auth.refresh_token:
            missing.append("ZOHO_REFRESH_TOKEN")
        if not self.zoho_auth.organization_id:
            missing.append("ZOHO_ORGANIZATION_ID")
        if missing:
            raise ValueError(f"Missing required env vars: {', '.join(missing)}")
