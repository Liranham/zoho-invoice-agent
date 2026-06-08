"""Top-level onboarding orchestrator.

Reads brain-dump from $EDITOR, calls Claude to extract structured data,
writes to all tables, runs coverage check, runs gap-fill, prints summary.
"""

from __future__ import annotations

import click

from goldman.llm import GoldmanLLM
from goldman.onboarding.coverage import missing_facts
from goldman.onboarding.extract import extract_from_dump
from goldman.onboarding.gap_fill import run_gap_fill
from goldman.onboarding.writer import OnboardingWriter
from goldman_db.bank_accounts import BankAccountRepository
from goldman_db.clients import ClientRepository
from goldman_db.connection import app_conn
from goldman_db.entities import EntityRepository
from goldman_db.facts import FactRepository
from goldman_db.tax_registrations import TaxRegistrationRepository
from goldman_db.vendors import VendorRepository


def run_onboarding(entity_slug: str) -> None:
    """End-to-end onboarding flow for a single entity."""
    click.echo(f"\nGoldman onboarding - {entity_slug}\n" + "=" * 50)

    with app_conn() as conn:
        ents = EntityRepository(conn)
        entity = ents.get_by_slug(entity_slug)
        if not entity:
            raise click.ClickException(f"Unknown entity slug: {entity_slug!r}")

    # 1. Brain dump via $EDITOR
    click.echo(
        f"\nPaste everything you know about {entity.legal_name} - "
        f"tax registrations, bank accounts, vendors, clients, decisions, "
        f"key people. Save and close the editor when done."
    )
    dump = click.edit(text="# Brain-dump for " + entity.legal_name + "\n\n")
    if dump:
        dump = dump.strip()
    if not dump or dump.startswith("# Brain-dump for"):
        click.echo("Empty brain-dump - skipping extraction phase.")
        extraction = {
            "tax_registrations": [], "bank_accounts": [],
            "vendors": [], "clients": [], "facts": [],
            "entity_metadata": {},
        }
    else:
        click.echo("\n-> Sending to Claude for extraction...")
        llm = GoldmanLLM()
        extraction = extract_from_dump(
            llm=llm,
            entity_slug=entity.slug,
            entity_legal_name=entity.legal_name,
            entity_jurisdiction=entity.jurisdiction,
            dump=dump,
        )
        click.echo(f"  ok extracted: "
                   f"{len(extraction['tax_registrations'])} tax regs, "
                   f"{len(extraction['bank_accounts'])} accounts, "
                   f"{len(extraction['vendors'])} vendors, "
                   f"{len(extraction['clients'])} clients, "
                   f"{len(extraction['facts'])} facts")

    # 2. Write to DB
    with app_conn() as conn:
        writer = OnboardingWriter(
            entities_repo=EntityRepository(conn),
            tax_repo=TaxRegistrationRepository(conn),
            clients_repo=ClientRepository(conn),
            vendors_repo=VendorRepository(conn),
            bank_repo=BankAccountRepository(conn),
            facts_repo=FactRepository(conn),
        )
        summary = writer.write(
            entity_slug=entity.slug,
            entity_id=entity.id,
            extraction=extraction,
        )

    click.echo(
        f"\n-> Wrote: "
        f"{summary.tax_registrations_inserted} tax regs, "
        f"{summary.bank_accounts_upserted} banks, "
        f"{summary.vendors_upserted} vendors, "
        f"{summary.clients_upserted} clients, "
        f"{summary.facts_upserted} facts, "
        f"metadata={summary.metadata_updated}"
    )

    # 3. Coverage check
    click.echo("\n-> Coverage check...")
    with app_conn() as conn:
        ents = EntityRepository(conn)
        entity = ents.get_by_slug(entity_slug)
        tax_repo = TaxRegistrationRepository(conn)
        bank_repo = BankAccountRepository(conn)
        gaps = missing_facts(entity, tax_repo=tax_repo, bank_repo=bank_repo)

    if not gaps:
        click.echo("  ok No mandatory gaps. Onboarding complete.")
        return

    click.echo(f"  warning {len(gaps)} gap(s) remaining. Let's fill them.")

    # 4. Gap-fill loop
    llm = GoldmanLLM()
    with app_conn() as conn:
        writer = OnboardingWriter(
            entities_repo=EntityRepository(conn),
            tax_repo=TaxRegistrationRepository(conn),
            clients_repo=ClientRepository(conn),
            vendors_repo=VendorRepository(conn),
            bank_repo=BankAccountRepository(conn),
            facts_repo=FactRepository(conn),
        )
        run_gap_fill(
            entity=entity,
            gaps=gaps,
            llm=llm,
            writer=writer,
            entity_id=entity.id,
        )

    click.echo("\n-> Onboarding finished. Run `cli.py who` to review.")
