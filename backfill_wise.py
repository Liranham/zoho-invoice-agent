"""
Backfill missing Zoho invoices from Wise statements.

Pulls balance statements for the configured profile/balances over a date range,
filters for credits, diffs against existing Zoho invoices (matching on
date+amount), and creates the missing ones via the same WiseAutomation path.

This endpoint is SCA-protected — requires WISE_PRIVATE_KEY_B64 and a public key
already uploaded in the Wise UI.

Usage:
    python3 backfill_wise.py --from 2025-05 --to 2026-04 --dry-run
    python3 backfill_wise.py --from 2025-05 --to 2026-04          # actually create

Match heuristic for "already invoiced":
    same date (YYYY-MM-DD) AND same total (within 1 cent).
"""

from __future__ import annotations

import logging
import os
from calendar import monthrange
from datetime import datetime, timezone

import click

from auth.zoho_auth import ZohoAuth
from config.settings import Settings
from wise.auth import WiseAuth
from wise.client import WiseClient
from wise.handler import CLIENT_MAPPING, WiseAutomation
from zoho.client import ZohoClient
from zoho.contacts import ContactService
from zoho.invoices import InvoiceService

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("backfill")


def _month_to_iso_range(month: str) -> tuple[str, str]:
    """'2026-04' -> ('2026-04-01T00:00:00Z', '2026-04-30T23:59:59Z')."""
    year, mo = (int(x) for x in month.split("-"))
    last_day = monthrange(year, mo)[1]
    return (
        f"{year:04d}-{mo:02d}-01T00:00:00Z",
        f"{year:04d}-{mo:02d}-{last_day:02d}T23:59:59Z",
    )


def _months_between(from_month: str, to_month: str) -> list[str]:
    fy, fm = (int(x) for x in from_month.split("-"))
    ty, tm = (int(x) for x in to_month.split("-"))
    months = []
    y, m = fy, fm
    while (y, m) <= (ty, tm):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _is_known_sender(name: str) -> bool:
    if not name:
        return False
    upper = name.upper().strip()
    return any(k in upper or upper in k for k in CLIENT_MAPPING.keys())


def _extract_credit_rows(statement: dict) -> list[dict]:
    """Pull credit transactions out of a Wise statement payload."""
    rows = []
    for txn in statement.get("transactions", []) or []:
        if txn.get("type") != "CREDIT":
            continue
        amount = (txn.get("amount") or {}).get("value")
        currency = (txn.get("amount") or {}).get("currency")
        date = txn.get("date") or ""
        # Wise statement details has sender info under details.senderName
        details = txn.get("details") or {}
        sender = details.get("senderName") or details.get("paymentReference") or ""
        ref = details.get("paymentReference") or ""
        rows.append(
            {
                "date": date.split("T")[0] if "T" in date else date,
                "amount": float(amount) if amount is not None else None,
                "currency": currency or "USD",
                "sender": sender,
                "reference": ref,
                "raw": txn,
            }
        )
    return rows


def _existing_invoices(invoice_service: InvoiceService) -> set[tuple[str, float]]:
    """Set of (date, total) for all existing Zoho invoices (200 most recent)."""
    invoices = invoice_service.list_invoices(per_page=200)
    return {(inv.date, round(inv.total, 2)) for inv in invoices}


@click.command()
@click.option("--from", "from_month", required=True, help="Start month: YYYY-MM")
@click.option("--to", "to_month", required=True, help="End month: YYYY-MM (inclusive)")
@click.option("--dry-run", is_flag=True, help="List the diff; do not create")
def main(from_month: str, to_month: str, dry_run: bool):
    settings = Settings()
    settings.validate()

    if not settings.wise.api_token:
        raise click.UsageError("WISE_API_TOKEN not set")
    if not settings.wise.private_key_b64:
        raise click.UsageError("WISE_PRIVATE_KEY_B64 not set (required for SCA)")
    if not settings.wise.profile_id:
        raise click.UsageError("WISE_PROFILE_ID not set")

    # --- Wise side
    wise_auth = WiseAuth.from_env_b64(settings.wise.api_token, settings.wise.private_key_b64)
    wise = WiseClient(wise_auth)

    profile_id = settings.wise.profile_id
    balances = wise.list_balances(profile_id)
    if not balances:
        raise click.UsageError("No balances found for profile")

    # --- Zoho side
    zoho_auth = ZohoAuth(
        client_id=settings.zoho_auth.client_id,
        client_secret=settings.zoho_auth.client_secret,
        refresh_token=settings.zoho_auth.refresh_token,
        accounts_url=settings.zoho_auth.accounts_url,
    )
    zoho = ZohoClient(zoho_auth, settings.zoho_auth.api_base_url, settings.zoho_auth.organization_id)
    invoice_service = InvoiceService(zoho)
    contact_service = ContactService(zoho)
    existing = _existing_invoices(invoice_service)
    click.echo(f"Existing Zoho invoices in working set: {len(existing)}")

    # --- automation, but with state in /tmp so we don't clobber prod state
    state_dir = os.environ.get("BACKFILL_STATE_DIR", "/tmp/wise_backfill")
    os.makedirs(state_dir, exist_ok=True)
    automation = WiseAutomation(
        wise_client=wise,
        invoice_service=invoice_service,
        contact_service=contact_service,
        telegram=None,
        state_path=os.path.join(state_dir, "processed.json"),
    )

    # --- iterate months × balances
    candidates: list[dict] = []
    for month in _months_between(from_month, to_month):
        from_iso, to_iso = _month_to_iso_range(month)
        for balance in balances:
            balance_id = balance.get("id")
            currency = balance.get("currency") or "USD"
            click.echo(f"  fetching {currency} statement for {month}…")
            try:
                stmt = wise.get_balance_statement(
                    profile_id, balance_id, currency, from_iso, to_iso
                )
            except Exception as e:
                click.echo(f"  ⚠ {currency} {month}: {e}")
                continue
            for row in _extract_credit_rows(stmt):
                if not _is_known_sender(row["sender"]):
                    continue
                if (row["date"], round(row["amount"] or 0, 2)) in existing:
                    continue
                candidates.append(row)

    if not candidates:
        click.echo("\n✓ No missing invoices found in the range.")
        return

    click.echo(f"\nMissing invoices ({len(candidates)}):")
    click.echo("-" * 80)
    for c in candidates:
        click.echo(
            f"  {c['date']} | {c['sender'][:30]:30} | "
            f"{c['amount']:>10.2f} {c['currency']} | ref={c['reference'][:20]}"
        )

    if dry_run:
        click.echo("\nDRY RUN — no invoices created.")
        return

    click.echo("\nCreating invoices…")
    created = 0
    for c in candidates:
        # Synthesize a swift-in#credit-shaped payload so handler.handle works
        synthetic = {
            "event_type": "swift-in#credit",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "data": {
                "resource": {
                    "type": "transfer",
                    "id": f"backfill-{c['date']}-{c['amount']}",
                    "sender": {"name": c["sender"]},
                },
                "amount": c["amount"],
                "currency": c["currency"],
                "occurred_at": f"{c['date']}T12:00:00Z",
            },
        }
        if automation.handle(synthetic):
            created += 1

    click.echo(f"\n✓ Created {created}/{len(candidates)} invoices.")


if __name__ == "__main__":
    main()
