"""
CLI interface for the Goldman / Zoho Books Invoice Agent.

Every command takes --entity SLUG (default 'amzg') to route to the right
Zoho Books organisation. SLUG must match a row in goldman.entities.

Usage:
    python cli.py list [--entity amzg|seo] [--status draft|sent|paid|overdue]
    python cli.py create --entity amzg --customer-id ID --amount 500
    python cli.py delete --entity amzg --invoice-id ID
    python cli.py batch-create --entity amzg --file invoices.xlsx [--dry-run]
    python cli.py customers --entity amzg
    python cli.py items --entity amzg
    python cli.py db migrate
    python cli.py db sync-zoho-org-ids
"""

import logging

import click

from config.settings import Settings
from batch.processor import BatchProcessor


def _build_services(entity_slug: str):
    """Build entity-scoped services using the Goldman Zoho factory.

    Each command receives an entity slug (CLI flag default = 'amzg').
    Routing through the factory guarantees no command silently hits
    the wrong Zoho organisation.
    """
    settings = Settings()
    # Settings.validate() is intentionally NOT called here — it validates
    # the legacy ZOHO_* singleton env vars, which we no longer rely on
    # for runtime ops. Validation now happens inside the factory per
    # zoho_credential_key.

    from goldman.zoho import (
        invoice_service_for, contact_service_for, item_service_for,
    )
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository

    # One DB lookup per command — small enough not to bother caching.
    with app_conn() as conn:
        repo = EntityRepository(conn)
        inv_svc = invoice_service_for(entity_slug, entity_repo=repo)
        contact_svc = contact_service_for(entity_slug, entity_repo=repo)
        item_svc = item_service_for(entity_slug, entity_repo=repo)
    return inv_svc, contact_svc, item_svc, settings


@click.group()
def cli():
    """Goldman / Zoho Books Invoice Agent"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )


@cli.command("list")
@click.option("--entity", default="amzg",
              help="Entity slug (amzg = AMZ Expert Global Ltd; seo = Specific Edge Outsourcing LLC)")
@click.option("--status", default="", help="Filter: draft, sent, paid, overdue")
@click.option("--page", default=1, type=int)
def list_invoices(entity, status, page):
    """List invoices."""
    inv_svc, _, _, _ = _build_services(entity)
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
@click.option("--entity", default="amzg",
              help="Entity slug (amzg / seo)")
@click.option("--customer-id", required=True, help="Zoho customer ID")
@click.option("--amount", required=True, type=float, help="Invoice amount")
@click.option("--date", default="", help="YYYY-MM-DD (defaults to today)")
@click.option("--item-id", default="", help="Item ID (uses default if omitted)")
@click.option("--description", default="", help="Line item description")
@click.option("--notes", default="", help="Invoice notes")
def create(entity, customer_id, amount, date, item_id, description, notes):
    """Create a single invoice."""
    inv_svc, _, _, settings = _build_services(entity)
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
@click.option("--entity", default="amzg",
              help="Entity slug (amzg / seo)")
@click.option("--invoice-id", required=True, help="Invoice ID to delete")
@click.confirmation_option(prompt="Are you sure you want to delete this invoice?")
def delete(entity, invoice_id):
    """Delete an invoice."""
    inv_svc, _, _, _ = _build_services(entity)
    inv_svc.delete_invoice(invoice_id)
    click.echo(f"Deleted invoice: {invoice_id}")


@cli.command("batch-create")
@click.option("--entity", default="amzg",
              help="Entity slug (amzg / seo)")
@click.option(
    "--file",
    "file_path",
    required=True,
    type=click.Path(exists=True),
    help="Excel (.xlsx) or CSV file",
)
@click.option("--dry-run", is_flag=True, help="Preview without creating invoices")
def batch_create(entity, file_path, dry_run):
    """Create invoices from an Excel/CSV file.

    Expected columns: date, amount
    Optional columns: customer_id, customer_name, item_id, item_name, description
    """
    inv_svc, contact_svc, item_svc, settings = _build_services(entity)
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
@click.option("--entity", default="amzg",
              help="Entity slug (amzg / seo)")
def customers(entity):
    """List customers (to find customer_id)."""
    _, contact_svc, _, _ = _build_services(entity)
    contacts = contact_svc.list_contacts()
    if not contacts:
        click.echo("No customers found.")
        return
    click.echo(f"{'ID':<20} {'NAME':<30} {'EMAIL'}")
    click.echo("-" * 70)
    for c in contacts:
        click.echo(f"{c.contact_id:<20} {c.contact_name:<30} {c.email}")


@cli.command("create-customer")
@click.option("--entity", default="amzg",
              help="Entity slug (amzg / seo)")
@click.option("--name", required=True, help="Contact / display name")
@click.option("--company", default="", help="Company name")
@click.option("--email", default="", help="Primary email")
@click.option("--phone", default="", help="Primary phone")
def create_customer(entity, name, company, email, phone):
    """Create a new customer contact in Zoho Books."""
    _, contact_svc, _, _ = _build_services(entity)
    c = contact_svc.create_contact(
        contact_name=name,
        company_name=company,
        email=email,
        phone=phone,
    )
    click.echo(f"Created: {c.contact_id} | {c.contact_name} | {c.email}")


@cli.command()
@click.option("--entity", default="amzg",
              help="Entity slug (amzg / seo)")
def items(entity):
    """List items (to find item_id)."""
    _, _, item_svc, _ = _build_services(entity)
    all_items = item_svc.list_items()
    if not all_items:
        click.echo("No items found.")
        return
    click.echo(f"{'ID':<20} {'NAME':<30} {'RATE':>12}")
    click.echo("-" * 65)
    for item in all_items:
        click.echo(f"{item.item_id:<20} {item.name:<30} {item.rate:>12.2f}")


# -----------------------------------------------------------------------------
# Goldman DB operations
# -----------------------------------------------------------------------------

@cli.group()
def db():
    """Goldman database operations."""


@db.command("migrate")
def db_migrate():
    """Apply pending Goldman migrations.

    Uses the admin connection (GOLDMAN_DB_ADMIN_URL). Safe to re-run —
    already-applied migrations are skipped.
    """
    from pathlib import Path
    from goldman_db.connection import admin_conn
    from goldman_db.migrator import apply_pending

    migrations_dir = Path(__file__).resolve().parent / "migrations"
    if not migrations_dir.exists():
        raise click.ClickException(f"No migrations directory at {migrations_dir}")

    with admin_conn() as conn:
        applied = apply_pending(conn, migrations_dir)

    if applied:
        click.echo(f"Applied {len(applied)} migration(s):")
        for name in applied:
            click.echo(f"  ✓ {name}")
    else:
        click.echo("No pending migrations.")


@db.command("sync-zoho-org-ids")
def db_sync_zoho_org_ids():
    """Backfill goldman.entities.zoho_organization_id from env vars.

    Reads ZOHO_<credkey>_ORGANIZATION_ID for each entity and writes it to
    its row. Idempotent — only updates rows where zoho_organization_id
    is currently NULL or differs from env.
    """
    import os
    from goldman_db.connection import admin_conn

    updates = 0
    with admin_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT slug, zoho_credential_key, zoho_organization_id "
                "FROM goldman.entities"
            )
            rows = cur.fetchall()

        for slug, cred_key, current_org_id in rows:
            if not cred_key:
                continue
            env_org_id = os.getenv(
                f"ZOHO_{cred_key.upper()}_ORGANIZATION_ID", ""
            )
            if env_org_id and env_org_id != current_org_id:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE goldman.entities SET zoho_organization_id = %s "
                        "WHERE slug = %s",
                        (env_org_id, slug),
                    )
                updates += 1
                click.echo(f"  ✓ {slug}: org_id = {env_org_id}")
    if updates:
        click.echo(f"Updated {updates} entit{'y' if updates == 1 else 'ies'}.")
    else:
        click.echo("All entities already in sync.")


if __name__ == "__main__":
    cli()
