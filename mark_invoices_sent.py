"""
Mark draft invoices as sent and optionally email them.

Usage:
    python3 mark_invoices_sent.py [--send-email]
"""

import click
import logging

from config.settings import Settings
from auth.zoho_auth import ZohoAuth
from zoho.client import ZohoClient
from zoho.invoices import InvoiceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@click.command()
@click.option("--send-email", is_flag=True, help="Email invoices after marking as sent")
def main(send_email: bool):
    """Mark all draft invoices as sent and optionally email them."""

    # Initialize Zoho services
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
    invoice_service = InvoiceService(client)

    # Get all draft invoices
    click.echo("Fetching draft invoices...")
    invoices = invoice_service.list_invoices(status="draft", per_page=100)

    if not invoices:
        click.echo("No draft invoices found.")
        return

    click.echo(f"Found {len(invoices)} draft invoices.\n")

    marked = 0
    emailed = 0
    failed = 0

    for invoice in invoices:
        try:
            # Mark as sent
            client.post(f"invoices/{invoice.invoice_id}/status/sent")
            click.echo(f"✓ Marked as sent: {invoice.invoice_number} | ${invoice.total:.2f}")
            marked += 1

            # Send email if requested
            if send_email:
                try:
                    invoice_service.send_invoice(invoice.invoice_id)
                    click.echo(f"  📧 Emailed to {invoice.customer_name}")
                    emailed += 1
                except Exception as email_error:
                    click.echo(f"  ⚠️  Failed to send email: {email_error}")

        except Exception as e:
            click.echo(f"✗ Failed for {invoice.invoice_number}: {e}")
            failed += 1
            continue

    # Summary
    click.echo(f"\n{'='*60}")
    summary = f"COMPLETE: {marked} marked as sent, {failed} failed"
    if send_email and emailed > 0:
        summary += f", {emailed} emailed"
    click.echo(summary)


if __name__ == "__main__":
    main()
