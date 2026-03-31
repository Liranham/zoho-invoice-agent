"""Tests for the Invoice service."""

from unittest.mock import MagicMock

from zoho.invoices import InvoiceService


def _make_service(mock_responses: dict = None):
    client = MagicMock()
    if mock_responses:
        client.get.return_value = mock_responses.get("get", {})
        client.post.return_value = mock_responses.get("post", {})
        client.delete.return_value = mock_responses.get("delete", {})
    return InvoiceService(client), client


def test_list_invoices():
    svc, client = _make_service(
        {
            "get": {
                "invoices": [
                    {
                        "invoice_id": "inv_1",
                        "invoice_number": "INV-001",
                        "status": "sent",
                        "customer_name": "Acme Corp",
                        "date": "2026-01-15",
                        "due_date": "2026-02-14",
                        "total": 1500.00,
                        "balance": 1500.00,
                        "currency_code": "USD",
                        "line_items": [],
                    }
                ]
            }
        }
    )

    invoices = svc.list_invoices()
    assert len(invoices) == 1
    assert invoices[0].invoice_number == "INV-001"
    assert invoices[0].total == 1500.00
    assert invoices[0].customer_name == "Acme Corp"
    client.get.assert_called_once_with("invoices", params={"page": 1, "per_page": 25})


def test_list_invoices_with_status_filter():
    svc, client = _make_service({"get": {"invoices": []}})
    svc.list_invoices(status="paid")
    client.get.assert_called_once_with(
        "invoices", params={"page": 1, "per_page": 25, "status": "paid"}
    )


def test_create_invoice():
    svc, client = _make_service(
        {
            "post": {
                "invoice": {
                    "invoice_id": "inv_new",
                    "invoice_number": "INV-002",
                    "status": "draft",
                    "customer_name": "Test Co",
                    "date": "2026-03-01",
                    "due_date": "2026-03-31",
                    "total": 500.00,
                    "balance": 500.00,
                    "currency_code": "USD",
                    "line_items": [],
                }
            }
        }
    )

    inv = svc.create_invoice(
        customer_id="cust_1",
        line_items=[{"item_id": "item_1", "rate": 500, "quantity": 1}],
        date="2026-03-01",
    )

    assert inv.invoice_number == "INV-002"
    assert inv.total == 500.00
    client.post.assert_called_once()


def test_delete_invoice():
    svc, client = _make_service({"delete": {}})
    result = svc.delete_invoice("inv_123")
    assert result is True
    client.delete.assert_called_once_with("invoices/inv_123")


def test_get_invoice():
    svc, client = _make_service(
        {
            "get": {
                "invoice": {
                    "invoice_id": "inv_1",
                    "invoice_number": "INV-001",
                    "status": "paid",
                    "customer_name": "Acme",
                    "date": "2026-01-01",
                    "due_date": "2026-01-31",
                    "total": 200.0,
                    "balance": 0.0,
                    "currency_code": "USD",
                }
            }
        }
    )

    inv = svc.get_invoice("inv_1")
    assert inv.status == "paid"
    assert inv.balance == 0.0
    client.get.assert_called_once_with("invoices/inv_1")
