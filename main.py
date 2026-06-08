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

# Global references for HTTP handler to use.
# _invoice_services is keyed by entity slug; pre-populated at startup.
_invoice_services: dict = {}  # slug -> InvoiceService
_gmail_automation = None
_wise_automation = None
_wise_signature_verifier = None
_telegram_notifier = None


class _HealthHandler(BaseHTTPRequestHandler):
    """Health endpoint + lightweight HTTP API for remote triggering."""

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._json_response(200, {"status": "ok", "service": "goldman"})
        elif self.path.startswith("/v1/"):
            self._handle_api(method="GET")
        elif self.path.startswith("/invoices"):
            self._handle_list_invoices()
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/invoices/create":
            self._handle_create_invoice()
        elif self.path.startswith("/v1/"):
            self._handle_api(method="POST")
        elif self.path == "/webhook/gmail":
            self._handle_gmail_webhook()
        elif self.path == "/webhook/wise":
            self._handle_wise_webhook()
        elif self.path == "/webhook/telegram":
            self._handle_telegram_webhook()
        else:
            self._json_response(404, {"error": "not found"})

    def _handle_api(self, method: str):
        from urllib.parse import urlparse, parse_qs
        from goldman.api.auth import is_authorized
        from goldman.api.endpoints import (
            handle_who, handle_recall, handle_remember,
            handle_pending_bills, handle_status,
        )

        if not is_authorized(dict(self.headers)):
            self._json_response(401, {"error": "unauthorized"})
            return

        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        body = {}
        if method == "POST":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length:
                    raw = self.rfile.read(content_length)
                    body = json.loads(raw.decode("utf-8"))
            except Exception as e:
                self._json_response(400, {"error": f"bad json: {e}"})
                return

        try:
            if path == "/v1/who":
                code, payload = handle_who(query=query, body=body)
            elif path == "/v1/recall":
                code, payload = handle_recall(query=query, body=body)
            elif path == "/v1/remember":
                code, payload = handle_remember(query=query, body=body)
            elif path == "/v1/bills/pending":
                code, payload = handle_pending_bills(query=query, body=body)
            elif path == "/v1/status":
                code, payload = handle_status(query=query, body=body)
            else:
                code, payload = 404, {"error": f"unknown api path: {path}"}
        except Exception as e:
            logger.exception("API error: %s", e)
            code, payload = 500, {"error": str(e)}

        self._json_response(code, payload)

    def _handle_list_invoices(self):
        if not _invoice_services:
            self._json_response(503, {"error": "service not ready"})
            return
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            entity_slug = (qs.get("entity") or ["amzg"])[0].lower()
            svc = _invoice_services.get(entity_slug)
            if not svc:
                self._json_response(
                    400, {"error": f"unknown entity: {entity_slug}"}
                )
                return
            invoices = svc.list_invoices()
            self._json_response(
                200,
                {
                    "entity": entity_slug,
                    "invoices": [
                        {
                            "invoice_number": inv.invoice_number,
                            "status": inv.status,
                            "date": inv.date,
                            "total": inv.total,
                            "customer": inv.customer_name,
                        }
                        for inv in invoices
                    ],
                },
            )
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def _handle_create_invoice(self):
        if not _invoice_services:
            self._json_response(503, {"error": "service not ready"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}
            entity_slug = (body.get("entity") or "amzg").lower()
            svc = _invoice_services.get(entity_slug)
            if not svc:
                self._json_response(
                    400, {"error": f"unknown entity: {entity_slug}"}
                )
                return
            inv = svc.create_invoice(
                customer_id=body["customer_id"],
                line_items=body["line_items"],
                date=body.get("date", ""),
            )
            self._json_response(
                201,
                {
                    "entity": entity_slug,
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

    def _handle_wise_webhook(self):
        """Verify and process a Wise webhook delivery."""
        if not _wise_automation or not _wise_signature_verifier:
            self._json_response(503, {"error": "wise automation not enabled"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length) if content_length else b""
            signature = self.headers.get("X-Signature-SHA256", "")

            if not _wise_signature_verifier.verify(raw_body, signature):
                logger.warning("Wise webhook signature invalid; rejecting")
                self._json_response(401, {"error": "invalid signature"})
                return

            try:
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except json.JSONDecodeError:
                self._json_response(400, {"error": "invalid json"})
                return

            # Ack within Wise's retry window; do work in background.
            threading.Thread(
                target=_wise_automation.handle, args=(payload,), daemon=True
            ).start()
            self._json_response(200, {"status": "queued"})
        except Exception as e:
            logger.exception("Wise webhook error: %s", e)
            self._json_response(500, {"error": str(e)})

    def _handle_telegram_webhook(self):
        """Process Telegram inline-keyboard callbacks."""
        if not _wise_automation:
            self._json_response(503, {"error": "wise automation not enabled"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}
            from tg_notify.inbox import process_update
            threading.Thread(
                target=process_update,
                args=(body, _wise_automation, _telegram_notifier),
                daemon=True,
            ).start()
            self._json_response(200, {"status": "ok"})
        except Exception as e:
            logger.exception("Telegram webhook error: %s", e)
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
                _gmail_automation.process_transfer(transfer)
    except Exception as e:
        logger.exception(f"Failed to process emails: {e}")


def cmd_server():
    """Start the server: health endpoint + scheduler + Gmail automation."""
    global _gmail_automation, _wise_automation
    global _wise_signature_verifier, _telegram_notifier

    from config.settings import Settings
    from scheduler.jobs import JobScheduler

    port = int(os.environ.get("PORT", 10000))

    # Start health server first — Render needs it to confirm the service is alive
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Health server listening on :%d", port)

    try:
        settings = Settings()
        # Note: settings.validate() not called — legacy singleton vars are no
        # longer required. Validation is per-entity inside the factory.

        from goldman.zoho import invoice_service_for, contact_service_for
        from goldman_db.connection import app_conn
        from goldman_db.entities import EntityRepository

        with app_conn() as conn:
            repo = EntityRepository(conn)
            entities = repo.list_all()
            for entity in entities:
                if not entity.zoho_credential_key or not entity.zoho_organization_id:
                    logger.warning(
                        "Entity %s missing Zoho creds — skipping in services map",
                        entity.slug,
                    )
                    continue
                try:
                    _invoice_services[entity.slug] = invoice_service_for(
                        entity.slug, entity_repo=repo
                    )
                    logger.info("Wired Zoho services for entity %s", entity.slug)
                except Exception as svc_err:
                    logger.warning(
                        "Could not wire entity %s: %s", entity.slug, svc_err
                    )

        # Telegram (shared by Gmail + Wise flows)
        if settings.telegram.enabled:
            from tg_notify.notifier import TelegramNotifier
            _telegram_notifier = TelegramNotifier(
                bot_token=settings.telegram.bot_token,
                chat_id=settings.telegram.chat_id,
            )

        # Initialize Gmail automation if enabled (targets amzg for v1)
        if settings.gmail.enabled:
            from gmail.auth import GmailAuth
            from gmail.watcher import GmailWatcher
            from gmail.automation import InvoiceAutomation

            gmail_auth = GmailAuth(
                credentials_b64=settings.gmail.credentials_b64,
                token_b64=settings.gmail.token_b64,
            )
            watcher = GmailWatcher(gmail_auth, settings.gmail.label_name)
            watcher.initialize()

            _gmail_automation = InvoiceAutomation(
                watcher, _invoice_services.get("amzg"), _telegram_notifier
            )
            logger.info("Gmail automation enabled for label: %s (entity=amzg)", settings.gmail.label_name)

        # Initialize Wise automation if enabled (targets amzg for v1)
        if settings.wise.enabled:
            from wise.auth import WiseAuth
            from wise.client import WiseClient
            from wise.signature import SignatureVerifier
            from wise.handler import WiseAutomation

            wise_auth = WiseAuth.from_env_b64(
                settings.wise.api_token, settings.wise.private_key_b64
            )
            wise_client = WiseClient(wise_auth)
            _wise_signature_verifier = SignatureVerifier()
            with app_conn() as conn:
                repo = EntityRepository(conn)
                contact_service = contact_service_for("amzg", entity_repo=repo)
            _wise_automation = WiseAutomation(
                wise_client=wise_client,
                invoice_service=_invoice_services.get("amzg"),
                contact_service=contact_service,
                telegram=_telegram_notifier,
            )
            logger.info("Wise automation enabled (entity=amzg)")

        if settings.scheduler.enabled:
            scheduler = JobScheduler(
                _invoice_services.get("amzg"), settings, _gmail_automation
            )
            scheduler.start()

        # Goldman Telegram bot (Phase 4)
        if os.environ.get("GOLDMAN_TELEGRAM_BOT_TOKEN"):
            try:
                from goldman.bot.app import run_bot
                threading.Thread(
                    target=run_bot, daemon=True, name="goldman-bot",
                ).start()
                logger.info("Goldman bot thread started")
            except Exception as e:
                logger.exception("Goldman bot failed to start: %s", e)

        logger.info("Goldman running. Waiting for requests...")
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
