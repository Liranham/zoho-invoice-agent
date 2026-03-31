"""Tests for invoice templates."""

import pytest
from invoice_templates import (
    InvoiceGenerator,
    AmzExpertGlobalTemplate,
    GiladWeinbergTemplate,
)


def test_amz_expert_template():
    """Test Amz-expert Global invoice template."""
    wire_amount = 2797.00
    line_items, notes = AmzExpertGlobalTemplate.generate_line_items(wire_amount)

    assert len(line_items) == 1
    assert line_items[0]["name"] == "Global Workforce Disbursement (Reimbursement)"
    assert line_items[0]["rate"] == 2797.00
    assert line_items[0]["quantity"] == 1
    assert "Funding for Philippine Independent Contractors" in line_items[0]["description"]
    assert "disbursement agent" in notes
    assert "taxable revenue" in notes


def test_gilad_weinberg_template():
    """Test Gilad Weinberg invoice template."""
    wire_amount = 3993.89
    line_items, notes = GiladWeinbergTemplate.generate_line_items(wire_amount)

    assert len(line_items) == 2

    # First line: Admin fee
    assert line_items[0]["name"] == "Administrative Disbursement Fee"
    assert line_items[0]["rate"] == 50.00
    assert line_items[0]["quantity"] == 1

    # Second line: Pass-through
    assert line_items[1]["name"] == "Pass-Through Payroll Funding"
    assert line_items[1]["rate"] == 3943.89  # 3993.89 - 50.00
    assert line_items[1]["quantity"] == 1

    # Notes
    assert "fiduciary capacity" in notes


def test_invoice_number_format():
    """Test invoice number generation."""
    # Amz-expert Global
    inv_num = AmzExpertGlobalTemplate.format_invoice_number("HK", "2025-11-24")
    assert inv_num == "HK-2025-11"

    # Gilad Weinberg
    inv_num = GiladWeinbergTemplate.format_invoice_number("IL", "2026-03-06")
    assert inv_num == "IL-2026-03"


def test_invoice_generator():
    """Test InvoiceGenerator factory."""
    # Test Amz-expert Global
    invoice_data = InvoiceGenerator.generate_invoice_data(
        client_name="AMZEXPERTGLOBALL",
        wire_amount=2797.00,
        wire_date="2025-11-24",
        customer_id="test-customer-123"
    )

    assert invoice_data["invoice_number"] == "HK-2025-11"
    assert invoice_data["customer_id"] == "test-customer-123"
    assert invoice_data["date"] == "2025-11-24"
    assert len(invoice_data["line_items"]) == 1
    assert invoice_data["payment_terms"] == 0

    # Test Gilad Weinberg (with partial match)
    invoice_data = InvoiceGenerator.generate_invoice_data(
        client_name="GILAD WEINBERG &",
        wire_amount=3993.89,
        wire_date="2026-03-06",
        customer_id="test-customer-456"
    )

    assert invoice_data["invoice_number"] == "IL-2026-03"
    assert len(invoice_data["line_items"]) == 2
    total = sum(item["rate"] * item["quantity"] for item in invoice_data["line_items"])
    assert total == 3993.89


def test_unknown_client():
    """Test that unknown client raises an error."""
    with pytest.raises(ValueError, match="No template found"):
        InvoiceGenerator.generate_invoice_data(
            client_name="Unknown Client",
            wire_amount=1000.00,
            wire_date="2026-01-01",
            customer_id="test-123"
        )
