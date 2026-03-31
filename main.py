"""
Zoho Books Invoice Agent — Main entry point.

Server mode (default): health server + scheduler + HTTP API (for Render)
CLI mode (--cli):      run a single command and exit
"""

import argparse
import json
import logging
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-24s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# Global references for HTTP handler to use
_invoice_service = None
_gmail_automation = None


class _HealthHandler(BaseHTTPRequestHandler):
    """Health endpoint + lightweight HTTP API for remote triggering."""

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._json_response(200, {"status": "ok", "service": "zoho-invoice-agent"})
        elif self.path.startswith("/invoices"):
            self._handle_list_invoices()
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/invoices/create":
            self._handle_create_invoice()
        elif self.path == "/webhook/gmail":
            self._handle_gmail_webhook()
        else:
            self._json_response(404, {"error": "not found"})

    def _handle_list_invoices(self):
        if not _invoice_service:
            self._json_response(503, {"error": "service not ready"})
            return
        try:
            invoices = _invoice_service.list_invoices()
            self._json_response(
                200,
                {
                    "invoices": [
                        {
                            "invoice_number": inv.invoice_number,
                            "status": inv.status,
                            "date": inv.date,
                            "total": inv.total,
                            "customer": inv.customer_name,
                        }
                        for inv in invoices
                    ]
                },
            )
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def _handle_create_invoice(self):
        if not _invoice_service:
            self._json_response(503, {"error": "service not ready"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}
            inv = _invoice_service.create_invoice(
                customer_id=body["customer_id"],
                line_items=body["line_items"],
                date=body.get("date", ""),
            )
            self._json_response(
                201,
                {
                    "invoice_id": inv.invoice_id,
                    "invoice_number": inv.invoice_number,
                    "total": inv.total,
                },
            )
        except Exception as e:
            self._json_response(400, {"error": str(e)})

    def _handle_gmail_webhook(self):
        """Handle Gmail push notification webhook."""
        if not _gmail_automation:
            self._json_response(503, {"error": "gmail automation not enabled"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}

            # Gmail sends notification with message ID
            # Format: {"message": {"data": base64({"emailAddress": "...", "historyId": "..."}), "messageId": "..."}}
            import base64
            if "message" in body and "data" in body["message"]:
                data = json.loads(base64.b64decode(body["message"]["data"]).decode())
                history_id = data.get("historyId")
                logger.info(f"Gmail notification received: historyId={history_id}")

                # Process recent messages (will handle the new one)
                # Run in background to not block webhook response
                threading.Thread(
                    target=_process_recent_emails,
                    daemon=True
                ).start()

            self._json_response(200, {"status": "processing"})
        except Exception as e:
            logger.exception(f"Gmail webhook error: {e}")
            self._json_response(500, {"error": str(e)})

    def _json_response(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass  # suppress per-request logs


def _process_recent_emails():
    """Process recent emails in background thread."""
    try:
        if _gmail_automation:
            transfers = _gmail_automation.watcher.poll_recent_messages(max_results=5)
            for transfer in transfers:
                logger.info(f"Processing transfer: ${transfer.amount} from {transfer.sender_name}")
                # Process each message (automation will check for duplicates)
                # For now, we just log - full implementation would track processed IDs
    except Exception as e:
        logger.exception(f"Failed to process emails: {e}")


def cmd_server():
    """Start the server: health endpoint + scheduler + Gmail automation."""
    global _invoice_service, _gmail_automation

    from config.settings import Settings
    from auth.zoho_auth import ZohoAuth
    from zoho.client import ZohoClient
    from zoho.invoices import InvoiceService
    from scheduler.jobs import JobScheduler

    port = int(os.environ.get("PORT", 10000))

    # Start health server first — Render needs it to confirm the service is alive
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Health server listening on :%d", port)

    try:
        settings = Settings()
        settings.validate()

        auth = ZohoAuth(
            client_id=settings.zoho_auth.client_id,
            client_secret=settings.zoho_auth.client_secret,
            refresh_token=settings.zoho_auth.refresh_token,
            accounts_url=settings.zoho_auth.accounts_url,
        )
        client = ZohoClient(
            auth, settings.zoho_auth.api_base_url, settings.zoho_auth.organization_id
        )
        _invoice_service = InvoiceService(client)

        # Initialize Gmail automation if enabled
        if settings.gmail.enabled:
            from gmail.auth import GmailAuth
            from gmail.watcher import GmailWatcher
            from gmail.automation import InvoiceAutomation
            from telegram.notifier import TelegramNotifier

            gmail_auth = GmailAuth(
                credentials_b64=settings.gmail.credentials_b64,
                token_b64=settings.gmail.token_b64,
            )
            watcher = GmailWatcher(gmail_auth, settings.gmail.label_name)
            watcher.initialize()

            # Set up Telegram if enabled
            telegram = None
            if settings.telegram.enabled:
                telegram = TelegramNotifier(
                    bot_token=settings.telegram.bot_token,
                    chat_id=settings.telegram.chat_id,
                )

            _gmail_automation = InvoiceAutomation(watcher, _invoice_service, telegram)
            logger.info("Gmail automation enabled for label: %s", settings.gmail.label_name)

        if settings.scheduler.enabled:
            scheduler = JobScheduler(_invoice_service, settings)
            scheduler.start()

        logger.info("Zoho Invoice Agent running. Waiting for requests...")
        threading.Event().wait()  # block forever

    except Exception as e:
        logger.exception("Failed to initialize: %s", e)
        logger.info("Health server still running — waiting for fix...")
        threading.Event().wait()  # keep health server alive (crash resilience)


def cmd_cli():
    """Delegate to the Click CLI."""
    from cli import cli

    cli()


def main():
    parser = argparse.ArgumentParser(description="Zoho Books Invoice Agent")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode")
    args, remaining = parser.parse_known_args()

    if args.cli:
        sys.argv = [sys.argv[0]] + remaining
        cmd_cli()
    else:
        cmd_server()


if __name__ == "__main__":
    main()
