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


@cli.command("onboard")
@click.option("--entity", required=True,
              help="Entity slug to onboard (amzg / seo)")
def onboard(entity):
    """Conversational onboarding for a single entity.

    Opens your editor for a brain-dump, parses it with Claude, writes the
    structured facts into Goldman's DB, then asks targeted questions for
    anything still missing.
    """
    from goldman.onboarding.flow import run_onboarding
    run_onboarding(entity.lower())


@cli.command("remember")
@click.option("--entity", default="amzg",
              help="Entity slug; 'global' for cross-entity facts")
@click.option("--kind", required=True,
              type=click.Choice(["target", "preference", "constraint",
                                 "commitment", "event", "decision", "note"]),
              help="Fact kind")
@click.argument("text")
def remember_cmd(entity, kind, text):
    """Record a free-floating fact for an entity."""
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from goldman_db.facts import FactRepository

    with app_conn() as conn:
        entity_id = None
        if entity != "global":
            ent = EntityRepository(conn).get_by_slug(entity)
            if not ent:
                raise click.ClickException(f"Unknown entity: {entity}")
            entity_id = ent.id
        facts = FactRepository(conn)
        new_id = facts.upsert(
            entity_id=entity_id,
            kind=kind,
            fact=text,
            source="user_explicit",
        )
    click.echo(f"  ok stored fact {new_id}")


@cli.command("recall")
@click.option("--entity", default=None,
              help="Restrict search to this entity (omit = cross-entity)")
@click.option("--top", default=10, type=int)
@click.argument("question")
def recall_cmd(entity, top, question):
    """Hybrid search (vector + keyword) across Goldman's memory.

    Returns top results from facts + conversation turns + document chunks
    with their source pointers.
    """
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from goldman_db.hybrid_search import hybrid_search
    from goldman.embeddings import EmbeddingClient

    embedder = EmbeddingClient()
    query_vec = embedder.embed_batch([question])[0]

    with app_conn() as conn:
        entity_id = None
        if entity:
            ent = EntityRepository(conn).get_by_slug(entity.lower())
            if not ent:
                raise click.ClickException(f"Unknown entity: {entity}")
            entity_id = ent.id

        results = hybrid_search(
            conn,
            query_embedding=query_vec,
            query_text=question,
            entity_id=entity_id,
            top_n=top,
        )

    if not results:
        click.echo("(no results)")
        return

    for i, r in enumerate(results, 1):
        click.echo(f"\n{i}. [{r.source_type}] score={r.score:.3f}")
        click.echo(f"   {r.excerpt[:200]}")
        if r.metadata:
            click.echo(f"   meta: {r.metadata}")


# -----------------------------------------------------------------------------
# Documents
# -----------------------------------------------------------------------------

@cli.group()
def document():
    """Goldman document store."""


@document.command("upload")
@click.option("--entity", required=True, help="Entity slug")
@click.argument("file", type=click.Path(exists=True))
def document_upload(entity, file):
    """Upload a document (txt/md/pdf), summarise via Claude, chunk + insert."""
    from pathlib import Path
    from goldman.documents import upload_document
    from goldman.llm import DocumentSummariser
    from goldman.storage import SupabaseStorage
    from goldman_db.connection import app_conn
    from goldman_db.documents import DocumentChunkRepository, DocumentRepository
    from goldman_db.entities import EntityRepository

    storage = SupabaseStorage()
    summariser = DocumentSummariser()

    with app_conn() as conn:
        ent = EntityRepository(conn).get_by_slug(entity.lower())
        if not ent:
            raise click.ClickException(f"Unknown entity: {entity}")
        doc_repo = DocumentRepository(conn)
        chunk_repo = DocumentChunkRepository(conn)

        result = upload_document(
            file_path=Path(file),
            entity_id=ent.id,
            entity_slug=ent.slug,
            storage=storage,
            doc_repo=doc_repo,
            chunk_repo=chunk_repo,
            summariser=summariser,
            bucket="goldman-documents",
        )

    click.echo(
        f"  ok uploaded {Path(file).name}: "
        f"doc_id={result.document_id}, chunks={result.chunk_count}, "
        f"path={result.storage_path}"
    )
    click.echo("  -> run `db embed-pending` to embed the chunks for retrieval.")


@document.command("list")
@click.option("--entity", default=None)
def document_list(entity):
    """List documents (all entities or one)."""
    from goldman_db.connection import app_conn
    from goldman_db.documents import DocumentRepository
    from goldman_db.entities import EntityRepository

    with app_conn() as conn:
        doc_repo = DocumentRepository(conn)
        if entity:
            ent = EntityRepository(conn).get_by_slug(entity.lower())
            if not ent:
                raise click.ClickException(f"Unknown entity: {entity}")
            docs = doc_repo.list_by_entity(ent.id)
        else:
            docs = doc_repo.list_all()

    if not docs:
        click.echo("(no documents)")
        return

    for d in docs:
        click.echo(f"  {d.filename}")
        click.echo(f"    id:   {d.id}")
        click.echo(f"    path: {d.original_storage_path}")
        if d.summary:
            click.echo(f"    summary: {d.summary[:150]}")


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


@db.command("embed-pending")
@click.option("--batch-size", default=50, type=int)
def db_embed_pending(batch_size):
    """Embed all rows with NULL embeddings.

    Hits facts + conversation_turns + document_chunks.
    """
    from goldman.embeddings import EmbeddingClient, embed_pending_in
    from goldman_db.connection import app_conn
    from goldman_db.conversation_turns import ConversationTurnRepository
    from goldman_db.documents import DocumentChunkRepository
    from goldman_db.facts import FactRepository

    embedder = EmbeddingClient()
    with app_conn() as conn:
        summary = embed_pending_in(
            facts_repo=FactRepository(conn),
            turns_repo=ConversationTurnRepository(conn),
            chunks_repo=DocumentChunkRepository(conn),
            embedder=embedder,
            batch_size=batch_size,
        )

    click.echo(
        f"  ok embedded: "
        f"{summary['facts']} facts, "
        f"{summary['turns']} turns, "
        f"{summary['chunks']} chunks."
    )


# -----------------------------------------------------------------------------
# Sync workers
# -----------------------------------------------------------------------------

@cli.group()
def sync():
    """Sync external systems into Goldman."""


@sync.command("zoho-contacts")
@click.option("--entity", required=True, help="Entity slug to sync")
def sync_zoho_contacts_cmd(entity):
    """Pull Zoho contacts for this entity into goldman.clients + goldman.vendors."""
    from goldman.sync.zoho_contacts import sync_zoho_contacts
    from goldman.zoho import contact_service_for
    from goldman_db.clients import ClientRepository
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from goldman_db.vendors import VendorRepository

    entity_slug = entity.lower()

    with app_conn() as conn:
        repo = EntityRepository(conn)
        ent = repo.get_by_slug(entity_slug)
        if not ent:
            raise click.ClickException(f"Unknown entity: {entity_slug}")
        contact_svc = contact_service_for(entity_slug, entity_repo=repo)
        clients_repo = ClientRepository(conn)
        vendors_repo = VendorRepository(conn)

        # Phase 1: route by Zoho's contact_type field. Zoho's Contact dataclass
        # in this repo doesn't expose contact_type yet — we treat everyone
        # as a client. Phase 3 (vendor email intake) will refine this.
        summary = sync_zoho_contacts(
            contact_service=contact_svc,
            entity_id=ent.id,
            clients_repo=clients_repo,
            vendors_repo=vendors_repo,
            is_vendor=lambda c: False,
        )

    click.echo(f"Synced for {entity_slug}: "
               f"{summary['clients']} clients, {summary['vendors']} vendors.")


# -----------------------------------------------------------------------------
# Bills (Phase 3 vendor intake)
# -----------------------------------------------------------------------------

@cli.group()
def bill():
    """Goldman vendor-bill intake pipeline."""


@bill.command("parse")
@click.argument("file", type=click.Path(exists=True))
def bill_parse(file):
    """Parse a single bill file via Claude vision. Read-only — no DB writes."""
    from pathlib import Path
    from goldman.bills.parser import parse_bill_file
    from goldman.llm import GoldmanLLM
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository

    llm = GoldmanLLM()
    with app_conn() as conn:
        entities = EntityRepository(conn).list_all()
    known = [e.legal_name for e in entities]

    result = parse_bill_file(Path(file), llm=llm, known_entities=known)

    click.echo(f"  vendor:           {result.vendor}")
    click.echo(f"  invoice_number:   {result.invoice_number or '-'}")
    click.echo(f"  amount:           {result.amount} {result.currency}")
    click.echo(f"  invoice_date:     {result.invoice_date}")
    click.echo(f"  billing_entity:   {result.billing_entity or '-'}")
    click.echo(f"  parse_confidence: {result.parse_confidence}")


@bill.command("file")
@click.option("--entity", default=None,
              help="Force entity slug (overrides parser's billing_entity).")
@click.argument("file", type=click.Path(exists=True))
def bill_file(entity, file):
    """End-to-end: parse + trust gate + three-write pipeline."""
    import mimetypes
    from datetime import date
    from pathlib import Path

    from goldman.bills.idempotency import bill_hash, normalise_vendor
    from goldman.bills.parser import parse_bill_file
    from goldman.bills.pipeline import run_three_write_pipeline
    from goldman.bills.trust_gate import decide_gate
    from goldman.drive.client import GoogleDriveClient
    from goldman.drive.folders import ensure_path
    from goldman.llm import GoldmanLLM
    from goldman.storage import SupabaseStorage
    from goldman.zoho import for_entity
    from goldman_db.bills import BillRepository, DuplicateBillError
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from goldman_db.pending_confirmations import PendingConfirmationRepository
    from goldman_db.vendors import VendorRepository
    from zoho.expenses import ExpenseService

    p = Path(file)
    mime, _ = mimetypes.guess_type(p.name)
    mime = mime or "application/octet-stream"

    llm = GoldmanLLM()

    # 1. Parse (need entity list for the prompt context)
    with app_conn() as conn:
        entities = EntityRepository(conn).list_all()
    known = [e.legal_name for e in entities]
    parse = parse_bill_file(p, llm=llm, known_entities=known)

    # 2. Resolve entity (CLI override > parser's billing_entity match)
    entity_slug = entity.lower() if entity else None
    if not entity_slug and parse.billing_entity:
        for e in entities:
            if e.legal_name.strip().lower() == parse.billing_entity.strip().lower():
                entity_slug = e.slug
                break

    if not entity_slug:
        raise click.ClickException(
            "Cannot resolve billing entity from parse. Pass --entity SLUG."
        )

    # 3-6. Pre-pipeline DB ops in one connection
    with app_conn() as conn:
        ent = EntityRepository(conn).get_by_slug(entity_slug)
        vendors_repo = VendorRepository(conn)
        bills_repo = BillRepository(conn)
        pending_repo = PendingConfirmationRepository(conn)

        # Vendor resolve (normalised fuzzy match)
        all_vendors = vendors_repo.list_by_entity(ent.id)
        norm = normalise_vendor(parse.vendor)
        vendor = next(
            (v for v in all_vendors if normalise_vendor(v.vendor_name) == norm),
            None,
        )

        # Idempotency
        h = bill_hash(
            vendor=parse.vendor,
            invoice_number=parse.invoice_number,
            amount=parse.amount,
            invoice_date=parse.invoice_date,
        )
        existing = bills_repo.get_by_idempotency_hash(h)
        if existing is not None:
            click.echo(
                f"  -> already filed (bill {existing.id}, "
                f"status={existing.status})"
            )
            return

        # Insert bill row
        try:
            bill_id = bills_repo.insert(
                entity_id=ent.id,
                vendor_id=vendor.id if vendor else None,
                vendor_name_at_intake=parse.vendor,
                invoice_number=parse.invoice_number,
                invoice_date=parse.invoice_date,
                amount=parse.amount,
                currency=parse.currency,
                idempotency_hash=h,
                due_date=parse.due_date,
                line_items=parse.line_items,
                tax_amount=parse.tax_amount,
                original_filename=p.name,
            )
        except DuplicateBillError:
            click.echo("  -> race: duplicate found on insert; skipping.")
            return

        # Trust gate
        decision = decide_gate(
            parse=parse, vendor=vendor,
            known_entity_slug=entity_slug,
            bill_already_filed=False,
        )

        if not decision.auto_file:
            bills_repo.mark_confirmation_required(bill_id, reason=decision.reason)
            pending_id = pending_repo.insert(
                bill_id=bill_id, entity_id=ent.id,
                prompt=(
                    f"{parse.vendor} {parse.amount} {parse.currency} — "
                    f"file to {ent.legal_name}? Reason: {decision.reason}"
                ),
                options=[
                    {"label": "Yes, file", "value": f"file:{entity_slug}"},
                    {"label": "Hold", "value": "hold"},
                    {"label": "Discard", "value": "discard"},
                ],
            )
            click.echo(
                f"  -> confirmation required: {decision.reason}\n"
                f"     pending_id={pending_id}; waiting for Telegram (Phase 4)."
            )
            return

    # 7. Auto-file path
    storage = SupabaseStorage()
    drive_client = GoogleDriveClient()
    with app_conn() as conn:
        zoho_client = for_entity(
            entity_slug, entity_repo=EntityRepository(conn),
        )
    zoho_expenses = ExpenseService(zoho_client)

    d = parse.invoice_date or date.today()
    month_name = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November",
                  "December"][d.month - 1]
    folder_id = ensure_path(drive_client, [
        "Goldman Bills", ent.legal_name, str(d.year), month_name,
    ])

    with app_conn() as conn:
        bills_repo = BillRepository(conn)
        bills_repo.mark_auto_filed(bill_id)
        result = run_three_write_pipeline(
            bill_id=bill_id,
            file_path=p,
            mime_type=mime,
            parse=parse,
            entity_slug=ent.slug,
            entity_legal_name=ent.legal_name,
            storage=storage,
            storage_bucket="goldman-bills",
            drive_client=drive_client,
            drive_folder_id=folder_id,
            zoho_expenses=zoho_expenses,
            bills_repo=bills_repo,
        )

    if result.all_succeeded():
        click.echo(
            f"  ok filed {parse.vendor} {parse.amount} {parse.currency} -> "
            f"{ent.legal_name}; Zoho expense {result.zoho_expense_id}"
        )
    else:
        click.echo(
            f"  partial: storage={result.in_storage} drive={result.in_drive} "
            f"zoho={result.in_zoho}; error={result.error}"
        )


@bill.command("list-pending")
def bill_list_pending():
    """List bills with status partial/pending (failure tray)."""
    from goldman_db.bills import BillRepository
    from goldman_db.connection import app_conn

    with app_conn() as conn:
        bills = BillRepository(conn).list_pending_partial_writes(limit=50)

    if not bills:
        click.echo("(no pending bills)")
        return
    for b in bills:
        click.echo(
            f"  {b.vendor_name_at_intake} {b.amount} {b.currency} | "
            f"storage={b.in_storage} drive={b.in_drive} zoho={b.in_zoho} | "
            f"id={b.id} | {b.last_error or ''}"
        )


@bill.command("retry")
@click.argument("bill_id")
def bill_retry(bill_id):
    """Retry the failed legs for a partial bill.

    Expects GOLDMAN_BILL_RETRY_PATH env var pointing at the original file
    on disk. Production retry will fetch from Storage; v1 keeps it simple.
    """
    import os
    from datetime import date
    from pathlib import Path
    from uuid import UUID

    from goldman.bills.parser import BillParseResult
    from goldman.bills.pipeline import run_three_write_pipeline
    from goldman.drive.client import GoogleDriveClient
    from goldman.drive.folders import ensure_path
    from goldman.storage import SupabaseStorage
    from goldman.zoho import for_entity
    from goldman_db.bills import BillRepository
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from zoho.expenses import ExpenseService

    src = os.environ.get("GOLDMAN_BILL_RETRY_PATH", "")
    if not src or not Path(src).exists():
        raise click.ClickException(
            "Set GOLDMAN_BILL_RETRY_PATH to the original file path to retry."
        )

    with app_conn() as conn:
        b = BillRepository(conn).get(UUID(bill_id))
        if not b:
            raise click.ClickException(f"No bill {bill_id}")
        ent = EntityRepository(conn).get_by_id(b.entity_id)

    parse = BillParseResult(
        vendor=b.vendor_name_at_intake, invoice_number=b.invoice_number,
        amount=float(b.amount), currency=b.currency,
        invoice_date=b.invoice_date, due_date=b.due_date,
        billing_entity=ent.legal_name,
        line_items=b.line_items, tax_amount=float(b.tax_amount or 0) or None,
        parse_confidence=1.0,
    )

    storage = SupabaseStorage()
    drive_client = GoogleDriveClient()
    with app_conn() as conn:
        zoho_client = for_entity(ent.slug, entity_repo=EntityRepository(conn))
    zoho_expenses = ExpenseService(zoho_client)

    d = b.invoice_date or date.today()
    month_name = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November",
                  "December"][d.month - 1]
    folder_id = ensure_path(drive_client, [
        "Goldman Bills", ent.legal_name, str(d.year), month_name,
    ])

    with app_conn() as conn:
        bills_repo = BillRepository(conn)
        result = run_three_write_pipeline(
            bill_id=b.id, file_path=Path(src),
            mime_type="application/pdf", parse=parse,
            entity_slug=ent.slug, entity_legal_name=ent.legal_name,
            storage=storage, storage_bucket="goldman-bills",
            drive_client=drive_client, drive_folder_id=folder_id,
            zoho_expenses=zoho_expenses, bills_repo=bills_repo,
        )

    click.echo(
        f"  retry: storage={result.in_storage} drive={result.in_drive} "
        f"zoho={result.in_zoho}"
    )


# -----------------------------------------------------------------------------
# Bot (Phase 4)
# -----------------------------------------------------------------------------

@cli.group("bot")
def bot_group():
    """Goldman Telegram bot operations."""


@bot_group.command("run")
def bot_run_cmd():
    """Start the Goldman Telegram bot (long-polling, blocking)."""
    from goldman.bot.app import run_bot
    run_bot()


@bot_group.command("ping")
def bot_ping_cmd():
    """Send a test ping via the bot token (no polling)."""
    import os
    import requests
    token = os.getenv("GOLDMAN_TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("GOLDMAN_TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise click.ClickException(
            "GOLDMAN_TELEGRAM_BOT_TOKEN and GOLDMAN_TELEGRAM_CHAT_ID required."
        )
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": "Goldman bot ping ok"},
    )
    if r.ok:
        click.echo(f"  ok: {r.json().get('result', {}).get('message_id')}")
    else:
        click.echo(f"  failed: {r.status_code} {r.text}")


@cli.command("who")
def who_cmd():
    """Print Goldman's company brain: every entity + its registrations,
    bank accounts, top clients and vendors. Uses the goldman_app DB role."""
    from goldman.who import build_who_view, render_who
    from goldman_db.bank_accounts import BankAccountRepository
    from goldman_db.clients import ClientRepository
    from goldman_db.connection import app_conn
    from goldman_db.entities import EntityRepository
    from goldman_db.tax_registrations import TaxRegistrationRepository
    from goldman_db.vendors import VendorRepository

    with app_conn() as conn:
        summaries = build_who_view(
            entities_repo=EntityRepository(conn),
            tax_repo=TaxRegistrationRepository(conn),
            bank_repo=BankAccountRepository(conn),
            clients_repo=ClientRepository(conn),
            vendors_repo=VendorRepository(conn),
        )

    click.echo(render_who(summaries))


if __name__ == "__main__":
    cli()
