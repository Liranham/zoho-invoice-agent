"""Onboarding coverage check.

Given an entity (already loaded) and the relevant repos, return the list
of mandatory facts that are still missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Gap:
    kind: str               # 'tax_registration_primary', 'bank_account', etc.
    prompt: str             # human-readable question for the user
    field_hints: list       # hint at expected fields (for the LLM gap-fill)


def missing_facts(entity, *, tax_repo, bank_repo) -> List[Gap]:
    """Return the gaps that need to be filled for this entity."""
    gaps: list = []

    # Tax registration for the primary tax in the entity's jurisdiction.
    live_tax = tax_repo.list_live(entity.id)
    if not live_tax:
        primary_hint = {
            "HK": "HK profits tax",
            "US": "US federal income tax",
            "UK": "UK corporation tax",
        }.get(entity.jurisdiction, f"{entity.jurisdiction} income/profits tax")
        gaps.append(Gap(
            kind="tax_registration_primary",
            prompt=(
                f"I don't have a primary tax registration for "
                f"{entity.legal_name}. What's the {primary_hint} "
                f"registration number, and when did it become effective?"
            ),
            field_hints=["tax_type", "registration_number",
                         "effective_from", "filing_cadence"],
        ))

    # At least one bank account.
    if not bank_repo.list_by_entity(entity.id):
        gaps.append(Gap(
            kind="bank_account",
            prompt=(
                f"I don't have any bank accounts for {entity.legal_name}. "
                f"What's at least one account (provider, label, currency)?"
            ),
            field_hints=["provider", "account_label", "currency"],
        ))

    # Entity metadata fields
    if not entity.fiscal_year_end:
        gaps.append(Gap(
            kind="fiscal_year_end",
            prompt=(
                f"What is {entity.legal_name}'s fiscal year end? "
                f"(format MM-DD, e.g. 03-31 for March 31)"
            ),
            field_hints=["fiscal_year_end"],
        ))
    if not entity.registered_address:
        gaps.append(Gap(
            kind="registered_address",
            prompt=f"What is {entity.legal_name}'s registered address?",
            field_hints=["registered_address"],
        ))
    if not entity.company_number:
        gaps.append(Gap(
            kind="company_number",
            prompt=(
                f"What is {entity.legal_name}'s registration / company "
                f"number? (the official ID in {entity.jurisdiction})"
            ),
            field_hints=["company_number"],
        ))

    return gaps
