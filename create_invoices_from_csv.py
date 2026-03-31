"""
Create invoices from Wise transaction CSV export.

Usage:
    python3 create_invoices_from_csv.py transaction-history.csv [--dry-run]
"""

import csv
import logging
import sys
from typing import List, Dict

import click

from config.settings import Settings
from auth.zoho_auth import ZohoAuth
from zoho.client import ZohoClient
from zoho.invoices import InvoiceService
from zoho.contacts import ContactService
from invoice_templates import InvoiceGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# Customer mapping from Zoho Books
CUSTOMER_MAP = {
    "GILAD WEINBERG": "8399034000000100025",
    "AMZEXPERTGLOBALL": "8399034000000100007",
}


def parse_wise_csv(csv_path: str) -> List[Dict]:
    """
    Parse Wise transaction CSV and extract incoming payments.

    Returns list of transactions with Direction=IN from relevant clients.
    """
    transactions = []

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            direction = row.get("Direction", "").strip()
            status = row.get("Status", "").strip()
            source_name = row.get("Source name", "").strip()

            # Only process completed incoming transfers
            if direction != "IN" or status != "COMPLETED":
                continue

            # Only process known clients
            if "GILAD WEINBERG" not in source_name.upper() and \
               "AMZEXPERTGLOBALL" not in source_name.upper():
                continue

            # Extract relevant data
            created_date = row.get("Created on", "").strip()
            amount_str = row.get("Source amount (after fees)", "").strip()

            # Parse date (format: "2026-03-06 19:57:01")
            invoice_date = created_date.split(" ")[0] if created_date else ""

            # Parse amount
            try:
                amount = float(amount_str) if amount_str else 0.0
            except ValueError:
                logger.warning(f"Could not parse amount: {amount_str}")
                continue

            transactions.append({
                "client_name": source_name,
                "date": invoice_date,
                "amount": amount,
                "reference": row.get("Reference", "").strip(),
            })

    return transactions


def get_customer_id(contact_service: ContactService, client_name: str) -> str:
    """Get Zoho customer ID for a client."""
    # First check hardcoded map
    normalized = client_name.upper().strip()
    for key, customer_id in CUSTOMER_MAP.items():
        if key in normalized:
            if customer_id:
                return customer_id
            break

    # Search in Zoho
    logger.info(f"Searching for customer: {client_name}")
    contacts = contact_service.list_contacts()

    for contact in contacts:
        if client_name.upper() in contact.contact_name.upper() or \
           contact.contact_name.upper() in client_name.upper():
            logger.info(f"Found customer: {contact.contact_name} (ID: {contact.contact_id})")
            return contact.contact_id

    raise ValueError(f"Customer not found in Zoho: {client_name}")


@click.command()
@click.argument("csv_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Preview invoices without creating")
@click.option("--skip-existing", is_flag=True, help="Skip if invoice number already exists")
@click.option("--send-email", is_flag=True, help="Automatically email invoices to customers after creation")
def main(csv_file: str, dry_run: bool, skip_existing: bool, send_email: bool):
    """Create invoices from Wise transaction CSV."""

    # Parse CSV
    click.echo(f"Parsing {csv_file}...")
    transactions = parse_wise_csv(csv_file)

    if not transactions:
        click.echo("No incoming transactions found from known clients.")
        return

    click.echo(f"Found {len(transactions)} incoming transactions.\n")

    # Initialize Zoho services
    if not dry_run:
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
        contact_service = ContactService(client)

        # Get existing invoices if skip_existing is enabled
        existing_invoice_numbers = set()
        if skip_existing:
            click.echo("Fetching existing invoices...")
            existing = invoice_service.list_invoices(per_page=200)
            existing_invoice_numbers = {inv.invoice_number for inv in existing}
            click.echo(f"Found {len(existing_invoice_numbers)} existing invoices.\n")

    # Process each transaction
    created = 0
    skipped = 0
    failed = 0
    sent = 0

    for txn in transactions:
        try:
            # Generate invoice data
            invoice_data = InvoiceGenerator.generate_invoice_data(
                client_name=txn["client_name"],
                wire_amount=txn["amount"],
                wire_date=txn["date"],
                customer_id="<placeholder>"  # Will be replaced
            )

            invoice_number = invoice_data["invoice_number"]

            # Check if already exists
            if skip_existing and invoice_number in existing_invoice_numbers:
                click.echo(f"⏭  SKIP: {invoice_number} already exists")
                skipped += 1
                continue

            if dry_run:
                click.echo(f"\n{'='*60}")
                click.echo(f"Invoice: {invoice_number}")
                click.echo(f"Client:  {txn['client_name']}")
                click.echo(f"Date:    {txn['date']}")
                click.echo(f"Amount:  ${txn['amount']:.2f}")
                click.echo(f"\nLine Items:")
                for item in invoice_data["line_items"]:
                    click.echo(f"  • {item['name']}: ${item['rate']:.2f}")
                click.echo(f"\nNotes:\n{invoice_data['notes']}")
                created += 1
            else:
                # Get customer ID
                customer_id = get_customer_id(contact_service, txn["client_name"])
                invoice_data["customer_id"] = customer_id

                # Create invoice
                invoice = invoice_service.create_invoice(
                    customer_id=invoice_data["customer_id"],
                    line_items=invoice_data["line_items"],
                    date=invoice_data["date"],
                    payment_terms=invoice_data["payment_terms"],
                    notes=invoice_data["notes"],
                )

                click.echo(
                    f"✓ Created: {invoice.invoice_number} | "
                    f"${invoice.total:.2f} | {invoice.customer_name}"
                )
                created += 1

                # Send email if requested
                if send_email:
                    try:
                        invoice_service.send_invoice(invoice.invoice_id)
                        click.echo(f"  📧 Emailed to customer")
                        sent += 1
                    except Exception as email_error:
                        click.echo(f"  ⚠️  Failed to send email: {email_error}")

        except Exception as e:
            click.echo(f"✗ Failed for {txn['client_name']} on {txn['date']}: {e}")
            failed += 1
            continue

    # Summary
    click.echo(f"\n{'='*60}")
    if dry_run:
        click.echo(f"DRY RUN COMPLETE: Would create {created} invoices")
    else:
        summary = f"COMPLETE: {created} created, {skipped} skipped, {failed} failed"
        if send_email and sent > 0:
            summary += f", {sent} emailed"
        click.echo(summary)


if __name__ == "__main__":
    main()
