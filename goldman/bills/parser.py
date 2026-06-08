"""Claude-vision parser for vendor bills (PDF / image / HTML)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional


PARSE_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor": {"type": "string",
                   "description": "The supplier's name as it appears on the bill."},
        "invoice_number": {"type": ["string", "null"]},
        "amount": {"type": "number",
                   "description": "Total amount due (grand total including tax)."},
        "currency": {"type": "string",
                     "description": "ISO currency code (USD, HKD, GBP, EUR, etc.)."},
        "invoice_date": {"type": ["string", "null"],
                         "description": "YYYY-MM-DD; date issued."},
        "due_date": {"type": ["string", "null"]},
        "billing_entity": {"type": ["string", "null"],
                            "description": "Which of OUR companies is being billed (legal name on the invoice)."},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": ["description", "amount"],
            },
        },
        "tax_amount": {"type": ["number", "null"]},
        "parse_confidence": {
            "type": "number",
            "description": "0.0-1.0 confidence in the parse. Below 0.7 -> trust gate forces confirm.",
        },
    },
    "required": ["vendor", "amount", "currency", "parse_confidence"],
}


@dataclass(frozen=True)
class BillParseResult:
    vendor: str
    invoice_number: Optional[str]
    amount: float
    currency: str
    invoice_date: Optional[date]
    due_date: Optional[date]
    billing_entity: Optional[str]
    line_items: list
    tax_amount: Optional[float]
    parse_confidence: float


def _safe_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except Exception:
        return None


def _build_prompt(known_entities: list) -> str:
    return (
        "You are Goldman's vendor-bill parser. Extract the structured fields "
        "from the attached document.\n\n"
        f"Known billing entities for this user: {', '.join(known_entities)}.\n"
        "If the bill is addressed to one of these, set billing_entity to "
        "its full legal name. If it's clearly a vendor's own invoice header "
        "(NOT addressed to one of OUR entities), set billing_entity to null.\n\n"
        "Rules:\n"
        "- amount = total amount due (final grand total).\n"
        "- currency = ISO code (USD/HKD/GBP/EUR/...).\n"
        "- Dates: YYYY-MM-DD.\n"
        "- parse_confidence: 0.0-1.0. Drop below 0.7 if anything is unclear, "
        "the scan is poor, or you had to guess.\n"
        "- NEVER invent fields. Use null for anything not on the document.\n\n"
        "Call submit_bill_parse with your findings."
    )


def parse_bill_file(
    file_path: Path,
    *,
    llm,
    known_entities: Optional[list] = None,
) -> BillParseResult:
    known_entities = known_entities or []
    system = _build_prompt(known_entities)
    extracted = llm.extract_from_document(
        document_path=file_path,
        system=system,
        tool_name="submit_bill_parse",
        tool_schema=PARSE_SCHEMA,
    )
    return BillParseResult(
        vendor=extracted["vendor"],
        invoice_number=extracted.get("invoice_number"),
        amount=float(extracted["amount"]),
        currency=extracted["currency"],
        invoice_date=_safe_date(extracted.get("invoice_date")),
        due_date=_safe_date(extracted.get("due_date")),
        billing_entity=extracted.get("billing_entity"),
        line_items=extracted.get("line_items") or [],
        tax_amount=extracted.get("tax_amount"),
        parse_confidence=float(extracted.get("parse_confidence", 0.0)),
    )
