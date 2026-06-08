"""Tests for the Claude-vision bill parser."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import date

import pytest

from goldman.bills.parser import (
    PARSE_SCHEMA, BillParseResult, parse_bill_file,
)


def test_parse_schema_top_level_keys():
    props = PARSE_SCHEMA["properties"]
    assert "vendor" in props
    assert "invoice_number" in props
    assert "amount" in props
    assert "currency" in props
    assert "invoice_date" in props
    assert "billing_entity" in props


def test_parse_bill_file_returns_validated_result(tmp_path):
    f = tmp_path / "h10.pdf"
    f.write_bytes(b"%PDF-1.4\n")

    fake_llm = MagicMock()
    fake_llm.extract_from_document.return_value = {
        "vendor": "Helium 10",
        "invoice_number": "C0C735E-0091",
        "amount": 89.00,
        "currency": "USD",
        "invoice_date": "2026-06-01",
        "billing_entity": "AMZ Expert Global Limited",
        "line_items": [{"description": "Diamond plan", "amount": 89.00}],
        "tax_amount": None,
        "due_date": None,
        "parse_confidence": 0.95,
    }

    result = parse_bill_file(f, llm=fake_llm, known_entities=["amzg", "seo"])

    assert isinstance(result, BillParseResult)
    assert result.vendor == "Helium 10"
    assert result.amount == 89.00
    assert result.invoice_date == date(2026, 6, 1)
    assert result.billing_entity == "AMZ Expert Global Limited"
