"""Onboarding extraction: prompt + tool schema + parser."""

from __future__ import annotations


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "tax_registrations": {
            "type": "array",
            "description": "Each tax registration the entity holds.",
            "items": {
                "type": "object",
                "properties": {
                    "tax_type": {
                        "type": "string",
                        "enum": ["vat", "sales_tax", "profits_tax",
                                 "income_tax", "withholding_tax",
                                 "payroll_tax", "other"],
                    },
                    "jurisdiction": {"type": "string", "description": "e.g. HK, GB, US-TX"},
                    "registration_number": {"type": ["string", "null"]},
                    "effective_from": {"type": ["string", "null"],
                                       "description": "YYYY-MM-DD"},
                    "effective_to": {"type": ["string", "null"],
                                     "description": "YYYY-MM-DD or null"},
                    "filing_cadence": {
                        "type": ["string", "null"],
                        "enum": ["monthly", "quarterly", "annual", "irregular", None],
                    },
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["tax_type", "jurisdiction"],
            },
        },
        "bank_accounts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "account_label": {"type": "string"},
                    "currency": {"type": "string"},
                    "account_identifier": {"type": ["string", "null"]},
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["provider", "account_label", "currency"],
            },
        },
        "vendors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "vendor_name": {"type": "string"},
                    "category": {
                        "type": ["string", "null"],
                        "enum": ["hosting", "factory", "shipping", "software",
                                 "professional_services", "utilities", "other", None],
                    },
                    "email_domain": {"type": ["string", "null"]},
                    "typical_amount": {"type": ["number", "null"]},
                    "typical_currency": {"type": ["string", "null"]},
                    "typical_cadence": {
                        "type": ["string", "null"],
                        "enum": ["weekly", "monthly", "quarterly", "annual", "irregular", None],
                    },
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["vendor_name"],
            },
        },
        "clients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "contact_name": {"type": "string"},
                    "company_name": {"type": ["string", "null"]},
                    "primary_email": {"type": ["string", "null"]},
                    "tier": {"type": ["string", "null"], "enum": ["a", "b", "c", None]},
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["contact_name"],
            },
        },
        "facts": {
            "type": "array",
            "description": "Free-floating facts that don't fit the structured tables.",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["target", "preference", "constraint",
                                 "commitment", "event", "decision", "note"],
                    },
                    "fact": {"type": "string"},
                },
                "required": ["kind", "fact"],
            },
        },
        "entity_metadata": {
            "type": "object",
            "description": "Updates to the entity row itself.",
            "properties": {
                "fiscal_year_end": {"type": ["string", "null"],
                                    "description": "MM-DD format"},
                "registered_address": {"type": ["string", "null"]},
                "company_number": {"type": ["string", "null"]},
                "incorporation_date": {"type": ["string", "null"],
                                       "description": "YYYY-MM-DD"},
            },
        },
    },
    "required": ["tax_registrations", "bank_accounts", "vendors",
                 "clients", "facts", "entity_metadata"],
}


SYSTEM_PROMPT_TEMPLATE = """\
You are Goldman's onboarding parser. Your job is to extract structured
company facts from the user's free-text brain-dump.

The brain-dump is about ONE legal entity:
  Slug: {slug}
  Legal name: {legal_name}
  Jurisdiction: {jurisdiction}

Extract the following from the dump:

1. TAX REGISTRATIONS — every tax registration the entity holds (VAT, sales tax,
   profits tax, income tax, withholding, payroll). Capture jurisdiction
   (HK / GB / US-TX / US-CA / etc.), registration number if mentioned, the
   start date if mentioned, and the filing cadence if mentioned.
2. BANK ACCOUNTS — every bank or fintech account (Wise, HSBC, Chase, etc.).
   Capture provider, a human-readable label, currency, and a masked identifier
   if the user mentions one.
3. VENDORS — recurring suppliers / services. Capture name, category
   (hosting/factory/shipping/software/professional_services/utilities/other),
   email domain if mentioned, typical recurring amount + currency + cadence
   if mentioned.
4. CLIENTS — customers / paying parties. Capture name and any tier/notes
   the user gives.
5. FACTS — anything else important that doesn't fit above. Examples:
   ownership percentages, key people (CPA name, lawyer name, director name),
   strategic decisions, prior advice from accountants.
   Categorise each as one of: target / preference / constraint /
   commitment / event / decision / note.
6. ENTITY METADATA — updates to the entity row itself: fiscal year end
   (MM-DD), registered address, company number, incorporation date (YYYY-MM-DD).

RULES:
- Fill fields only when you are confident from the text. Leave the rest null.
- NEVER fabricate or guess. If the user says "I might be VAT registered" do
  NOT add a tax_registration — that goes in facts as kind=note.
- Dates: use ISO format YYYY-MM-DD. For fiscal_year_end use MM-DD.
- Call the submit_extraction tool exactly once with your findings.
"""


def build_prompt(
    *,
    entity_slug: str,
    entity_legal_name: str,
    entity_jurisdiction: str,
    dump: str,
):
    """Build (system, user) prompts for the onboarding extraction."""
    system = SYSTEM_PROMPT_TEMPLATE.format(
        slug=entity_slug,
        legal_name=entity_legal_name,
        jurisdiction=entity_jurisdiction,
    )
    user = f"User's brain-dump:\n\n\"\"\"\n{dump}\n\"\"\""
    return system, user


def extract_from_dump(
    *,
    llm,
    entity_slug: str,
    entity_legal_name: str,
    entity_jurisdiction: str,
    dump: str,
) -> dict:
    """Send the dump to Claude; return the validated extraction dict."""
    system, user = build_prompt(
        entity_slug=entity_slug,
        entity_legal_name=entity_legal_name,
        entity_jurisdiction=entity_jurisdiction,
        dump=dump,
    )
    return llm.extract_with_tool(
        system=system,
        user_text=user,
        tool_name="submit_extraction",
        tool_schema=EXTRACTION_SCHEMA,
    )
