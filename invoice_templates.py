"""
Client-specific invoice templates for Pacific Edge Outsourcing LLC.
"""

from datetime import datetime
from typing import Dict, List, Tuple


class InvoiceTemplate:
    """Base class for invoice templates."""

    @staticmethod
    def format_invoice_number(client_prefix: str, date: str) -> str:
        """Generate invoice number in format: PREFIX-YYYY-MM"""
        dt = datetime.strptime(date, "%Y-%m-%d")
        return f"{client_prefix}-{dt.year}-{dt.strftime('%m')}"

    @staticmethod
    def generate_line_items(wire_amount: float, client_name: str) -> Tuple[List[Dict], str]:
        """Generate line items and notes for the invoice."""
        raise NotImplementedError


class AmzExpertGlobalTemplate(InvoiceTemplate):
    """Invoice template for Amz-expert Limited (Hong Kong)."""

    CLIENT_NAME = "AMZEXPERTGLOBALL"
    PREFIX = "HK"

    @staticmethod
    def generate_line_items(wire_amount: float, client_name: str = None) -> Tuple[List[Dict], str]:
        """
        Generate invoice for Amz-expert Global.

        Format:
        - Description: Global Workforce Disbursement (Reimbursement)
        - Amount: Full wire amount
        - Reference: Funding for Philippine Independent Contractors
        """
        line_items = [
            {
                "name": "Global Workforce Disbursement (Reimbursement)",
                "description": "Ref: Funding for Philippine Independent Contractors",
                "rate": wire_amount,
                "quantity": 1
            }
        ]

        notes = (
            "Note: Funds are received by Pacific Edge Outsourcing LLC acting as a "
            "disbursement agent. These funds do not constitute taxable revenue for the US entity."
        )

        return line_items, notes


class GiladWeinbergTemplate(InvoiceTemplate):
    """Invoice template for Gilad Weinberg."""

    CLIENT_NAME = "GILAD WEINBERG"
    PREFIX = "IL"
    ADMIN_FEE = 50.00

    @staticmethod
    def generate_line_items(wire_amount: float, client_name: str = None) -> Tuple[List[Dict], str]:
        """
        Generate invoice for Gilad Weinberg.

        Format:
        - Line 1: Administrative Disbursement Fee = $50.00
        - Line 2: Pass-Through Payroll Funding = Wire Amount - $50
        - TOTAL = Wire Amount (the $50 is deducted FROM the wire, not added)
        """
        payroll_funding = wire_amount - GiladWeinbergTemplate.ADMIN_FEE

        line_items = [
            {
                "name": "Administrative Disbursement Fee",
                "description": "Ref: Monthly management fee for payroll facilitation",
                "rate": GiladWeinbergTemplate.ADMIN_FEE,
                "quantity": 1
            },
            {
                "name": "Pass-Through Payroll Funding",
                "description": "Ref: Advance funding for international service providers",
                "rate": payroll_funding,
                "quantity": 1
            }
        ]

        notes = (
            "Note: Disbursement funds are held in a fiduciary capacity for the benefit of "
            "the Client and are not income to Pacific Edge Outsourcing LLC"
        )

        return line_items, notes


class InvoiceGenerator:
    """Factory for generating client-specific invoices."""

    TEMPLATES = {
        "AMZEXPERTGLOBALL": AmzExpertGlobalTemplate,
        "GILAD WEINBERG": GiladWeinbergTemplate,
    }

    @classmethod
    def get_template(cls, client_name: str) -> InvoiceTemplate:
        """Get the appropriate template for a client."""
        # Normalize client name
        normalized = client_name.upper().strip()

        # Check for exact match
        if normalized in cls.TEMPLATES:
            return cls.TEMPLATES[normalized]

        # Check for partial match
        for key, template in cls.TEMPLATES.items():
            if key in normalized or normalized in key:
                return template

        raise ValueError(f"No template found for client: {client_name}")

    @classmethod
    def generate_invoice_data(
        cls,
        client_name: str,
        wire_amount: float,
        wire_date: str,
        customer_id: str
    ) -> Dict:
        """
        Generate complete invoice data for a client.

        Args:
            client_name: Name of the client (e.g., "GILAD WEINBERG &" or "AMZEXPERTGLOBALL")
            wire_amount: Amount of the wire transfer
            wire_date: Date of wire in YYYY-MM-DD format
            customer_id: Zoho customer ID

        Returns:
            Dict with invoice data ready for Zoho API
        """
        template_class = cls.get_template(client_name)
        line_items, notes = template_class.generate_line_items(wire_amount, client_name)
        invoice_number = template_class.format_invoice_number(template_class.PREFIX, wire_date)

        return {
            "customer_id": customer_id,
            "date": wire_date,
            "invoice_number": invoice_number,
            "line_items": line_items,
            "notes": notes,
            "payment_terms": 0,  # Due immediately
        }
