"""
CLI interface for the Zoho Books Invoice Agent.

Usage:
    python cli.py list [--status draft|sent|paid|overdue]
    python cli.py create --customer-id ID --amount 500 [--date 2026-03-01]
    python cli.py delete --invoice-id ID
    python cli.py batch-create --file invoices.xlsx [--dry-run]
    python cli.py customers
    python cli.py items
"""

import logging

import click

from config.settings import Settings
from auth.zoho_auth import ZohoAuth
from zoho.client import ZohoClient
from zoho.invoices import InvoiceService
from zoho.contacts import ContactService
from zoho.items import ItemService
from batch.processor import BatchProcessor


def _build_services():
    """Initialize all service objects from settings."""
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
    return (
        InvoiceService(client),
        ContactService(client),
        ItemService(client),
        settings,
    )


@click.group()
def cli():
    """Zoho Books Invoice Agent"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )


@cli.command("list")
@click.option("--status", default="", help="Filter: draft, sent, paid, overdue")
@click.option("--page", default=1, type=int)
def list_invoices(status, page):
    """List invoices."""
    inv_svc, _, _, _ = _build_services()
    invoices = inv_svc.list_invoices(status=status, page=page)
    if not invoices:
        click.echo("No invoices found.")
        return
    click.echo(f"{'NUMBER':<15} {'STATUS':<10} {'DATE':<12} {'TOTAL':>12}  {'CUSTOMER'}")
    click.echo("-" * 70)
    for inv in invoices:
        click.echo(
            f"{inv.invoice_number:<15} {inv.status:<10} {inv.date:<12} "
            f"{inv.total:>12.2f}  {inv.customer_name}"
        )


@cli.command()
@click.option("--customer-id", required=True, help="Zoho customer ID")
@click.option("--amount", required=True, type=float, help="Invoice amount")
@click.option("--date", default="", help="YYYY-MM-DD (defaults to today)")
@click.option("--item-id", default="", help="Item ID (uses default if omitted)")
@click.option("--description", default="", help="Line item description")
@click.option("--notes", default="", help="Invoice notes")
def create(customer_id, amount, date, item_id, description, notes):
    """Create a single invoice."""
    inv_svc, _, _, settings = _build_services()
    resolved_item_id = item_id or settings.invoice_defaults.default_item_id
    if not resolved_item_id:
        raise click.ClickException(
            "No item ID provided and no ZOHO_DEFAULT_ITEM_ID configured"
        )

    line_items = [
        {
            "item_id": resolved_item_id,
            "rate": amount,
            "quantity": 1,
        }
    ]
    if description:
        line_items[0]["description"] = description

    inv = inv_svc.create_invoice(
        customer_id=customer_id,
        line_items=line_items,
        date=date,
        payment_terms=settings.invoice_defaults.payment_terms,
        notes=notes,
    )
    click.echo(f"Created: {inv.invoice_number} | ${inv.total:.2f} | {inv.customer_name}")


@cli.command()
@click.option("--invoice-id", required=True, help="Invoice ID to delete")
@click.confirmation_option(prompt="Are you sure you want to delete this invoice?")
def delete(invoice_id):
    """Delete an invoice."""
    inv_svc, _, _, _ = _build_services()
    inv_svc.delete_invoice(invoice_id)
    click.echo(f"Deleted invoice: {invoice_id}")


@cli.command("batch-create")
@click.option(
    "--file",
    "file_path",
    required=True,
    type=click.Path(exists=True),
    help="Excel (.xlsx) or CSV file",
)
@click.option("--dry-run", is_flag=True, help="Preview without creating invoices")
def batch_create(file_path, dry_run):
    """Create invoices from an Excel/CSV file.

    Expected columns: date, amount
    Optional columns: customer_id, customer_name, item_id, item_name, description
    """
    inv_svc, contact_svc, item_svc, settings = _build_services()
    processor = BatchProcessor(
        inv_svc, contact_svc, item_svc, settings.invoice_defaults
    )
    result = processor.execute(file_path, dry_run=dry_run)
    click.echo(
        f"\nBatch complete: {result.succeeded} created, "
        f"{result.failed} failed out of {result.total}"
    )
    if result.errors:
        click.echo("\nErrors:")
        for err in result.errors:
            click.echo(f"  Row {err['row']}: {err['error']}")


@cli.command()
def customers():
    """List customers (to find customer_id)."""
    _, contact_svc, _, _ = _build_services()
    contacts = contact_svc.list_contacts()
    if not contacts:
        click.echo("No customers found.")
        return
    click.echo(f"{'ID':<20} {'NAME':<30} {'EMAIL'}")
    click.echo("-" * 70)
    for c in contacts:
        click.echo(f"{c.contact_id:<20} {c.contact_name:<30} {c.email}")


@cli.command("create-customer")
@click.option("--name", required=True, help="Contact / display name")
@click.option("--company", default="", help="Company name")
@click.option("--email", default="", help="Primary email")
@click.option("--phone", default="", help="Primary phone")
def create_customer(name, company, email, phone):
    """Create a new customer contact in Zoho Books."""
    _, contact_svc, _, _ = _build_services()
    c = contact_svc.create_contact(
        contact_name=name,
        company_name=company,
        email=email,
        phone=phone,
    )
    click.echo(f"Created: {c.contact_id} | {c.contact_name} | {c.email}")


@cli.command()
def items():
    """List items (to find item_id)."""
    _, _, item_svc, _ = _build_services()
    all_items = item_svc.list_items()
    if not all_items:
        click.echo("No items found.")
        return
    click.echo(f"{'ID':<20} {'NAME':<30} {'RATE':>12}")
    click.echo("-" * 65)
    for item in all_items:
        click.echo(f"{item.item_id:<20} {item.name:<30} {item.rate:>12.2f}")


if __name__ == "__main__":
    cli()
