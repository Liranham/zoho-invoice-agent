"""Gap-fill loop: for each Gap, prompt the user, parse, write."""

from __future__ import annotations

from typing import Callable, Optional
from uuid import UUID

import click

from goldman.onboarding.coverage import Gap


GAP_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "tax_type": {"type": ["string", "null"]},
        "jurisdiction": {"type": ["string", "null"]},
        "registration_number": {"type": ["string", "null"]},
        "effective_from": {"type": ["string", "null"]},
        "filing_cadence": {"type": ["string", "null"]},
        "provider": {"type": ["string", "null"]},
        "account_label": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"]},
        "fiscal_year_end": {"type": ["string", "null"]},
        "registered_address": {"type": ["string", "null"]},
        "company_number": {"type": ["string", "null"]},
    },
}


def _gap_extraction_prompt(gap: Gap, entity_legal_name: str, jurisdiction: str) -> str:
    return (
        f"You are extracting a single fact about {entity_legal_name} "
        f"(jurisdiction: {jurisdiction}).\n\n"
        f"Question asked: {gap.prompt}\n\n"
        f"Extract any of these fields the user provided: "
        f"{', '.join(gap.field_hints)}. Leave fields null if not provided. "
        f"Dates: YYYY-MM-DD. Fiscal year end: MM-DD."
    )


def run_gap_fill(
    *,
    entity,
    gaps,
    llm,
    writer,
    entity_id: UUID,
    prompt_func: Optional[Callable[[str], str]] = None,
) -> None:
    """Prompt the user for each gap, write the answer.

    prompt_func is injected for testability (default = click.prompt).
    Users can type 'skip' to defer a gap.
    """
    ask = prompt_func or (lambda msg: click.prompt(msg, default="skip"))

    for gap in gaps:
        click.echo(f"\nGoldman: {gap.prompt}")
        click.echo("    (type 'skip' to defer this question)")
        answer = ask("Your answer").strip()
        if answer.lower() == "skip" or not answer:
            click.echo(f"  -> skipped - Goldman will ask again next time.")
            continue

        system = _gap_extraction_prompt(gap, entity.legal_name, entity.jurisdiction)
        try:
            extracted = llm.extract_with_tool(
                system=system,
                user_text=answer,
                tool_name="submit_gap_answer",
                tool_schema=GAP_EXTRACTION_SCHEMA,
            )
        except Exception as e:
            click.echo(f"  x couldn't parse that - skipped. ({e})")
            continue

        # Route the extracted single-field answer to the writer through the
        # same extraction dict shape it understands.
        extraction = {
            "tax_registrations": [],
            "bank_accounts": [],
            "vendors": [],
            "clients": [],
            "facts": [],
            "entity_metadata": {},
        }
        if gap.kind == "tax_registration_primary":
            extraction["tax_registrations"].append({
                "tax_type": extracted.get("tax_type") or "profits_tax",
                "jurisdiction": extracted.get("jurisdiction") or entity.jurisdiction,
                "registration_number": extracted.get("registration_number"),
                "effective_from": extracted.get("effective_from"),
                "filing_cadence": extracted.get("filing_cadence"),
            })
        elif gap.kind == "bank_account":
            extraction["bank_accounts"].append({
                "provider": extracted.get("provider") or "Unknown",
                "account_label": extracted.get("account_label") or "Primary",
                "currency": extracted.get("currency") or entity.jurisdiction[:3].upper(),
            })
        elif gap.kind in ("fiscal_year_end", "registered_address", "company_number"):
            extraction["entity_metadata"][gap.kind] = extracted.get(gap.kind)

        writer.write(
            entity_slug=entity.slug,
            entity_id=entity_id,
            extraction=extraction,
        )
        click.echo(f"  ok saved.")
