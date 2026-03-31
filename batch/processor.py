"""
Batch invoice processor.

Reads Excel (.xlsx) or CSV files and creates invoices via Zoho API.
Rate limiting is handled by the ZohoClient layer.

Expected columns: date, amount
Optional columns: customer_id, customer_name, item_id, item_name, description
"""

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from config.settings import InvoiceDefaults
from zoho.invoices import InvoiceService
from zoho.contacts import ContactService
from zoho.items import ItemService

logger = logging.getLogger(__name__)


@dataclass
class BatchRow:
    row_number: int
    date: str
    amount: float
    customer_id: str
    item_id: str
    description: str = ""


@dataclass
class BatchResult:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: list[dict] = field(default_factory=list)


class BatchProcessor:
    def __init__(
        self,
        invoice_service: InvoiceService,
        contact_service: ContactService,
        item_service: ItemService,
        defaults: InvoiceDefaults,
    ):
        self.invoices = invoice_service
        self.contacts = contact_service
        self.items = item_service
        self.defaults = defaults

    def read_file(self, file_path: str) -> list[dict]:
        path = Path(file_path)
        if path.suffix in (".xlsx", ".xls"):
            return self._read_excel(path)
        elif path.suffix == ".csv":
            return self._read_csv(path)
        else:
            raise ValueError(f"Unsupported file type: {path.suffix}. Use .xlsx or .csv")

    def _read_excel(self, path: Path) -> list[dict]:
        wb = openpyxl.load_workbook(path, read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            return []
        # First row is headers
        headers = [str(h).strip().lower().replace(" ", "_") for h in rows[0] if h]
        result = []
        for row in rows[1:]:
            if not any(row):  # skip empty rows
                continue
            result.append(dict(zip(headers, row)))
        return result

    def _read_csv(self, path: Path) -> list[dict]:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [
                {k.strip().lower().replace(" ", "_"): v for k, v in row.items()}
                for row in reader
            ]

    def validate_rows(self, raw_rows: list[dict]) -> tuple[list[BatchRow], list[dict]]:
        """Validate rows and resolve names to IDs. Returns (valid_rows, errors)."""
        validated = []
        errors = []

        for i, raw in enumerate(raw_rows, start=2):  # row 2 = first data row
            try:
                # Amount is required
                amount_val = raw.get("amount")
                if amount_val is None:
                    raise ValueError("Missing 'amount' column")
                amount = float(amount_val)
                if amount <= 0:
                    raise ValueError(f"Amount must be positive, got {amount}")

                # Date is required
                date_val = raw.get("date")
                if not date_val:
                    raise ValueError("Missing 'date' column")
                date_str = str(date_val).strip()
                # Handle Excel date objects
                if hasattr(date_val, "strftime"):
                    date_str = date_val.strftime("%Y-%m-%d")

                # Resolve customer
                customer_id = raw.get("customer_id", "").strip() if raw.get("customer_id") else ""
                if not customer_id:
                    customer_name = raw.get("customer_name", "").strip() if raw.get("customer_name") else ""
                    if customer_name:
                        customer_id = self.contacts.get_customer_id(customer_name)
                    else:
                        customer_id = self.defaults.default_customer_id
                if not customer_id:
                    raise ValueError(
                        "No customer_id or customer_name, and no default configured"
                    )

                # Resolve item
                item_id = raw.get("item_id", "").strip() if raw.get("item_id") else ""
                if not item_id:
                    item_name = raw.get("item_name", "").strip() if raw.get("item_name") else ""
                    if item_name:
                        item_id = self.items.get_item_id(item_name)
                    else:
                        item_id = self.defaults.default_item_id
                if not item_id:
                    raise ValueError(
                        "No item_id or item_name, and no default configured"
                    )

                description = str(raw.get("description", "") or "").strip()

                validated.append(
                    BatchRow(
                        row_number=i,
                        date=date_str,
                        amount=amount,
                        customer_id=customer_id,
                        item_id=item_id,
                        description=description,
                    )
                )
            except Exception as e:
                errors.append({"row": i, "error": str(e)})
                logger.warning("Row %d validation failed: %s", i, e)

        return validated, errors

    def execute(self, file_path: str, dry_run: bool = False) -> BatchResult:
        """Full pipeline: read → validate → create invoices."""
        raw_rows = self.read_file(file_path)
        logger.info("Read %d rows from %s", len(raw_rows), file_path)

        validated, validation_errors = self.validate_rows(raw_rows)
        logger.info(
            "%d rows validated, %d skipped", len(validated), len(validation_errors)
        )

        result = BatchResult(
            total=len(validated) + len(validation_errors),
            errors=list(validation_errors),
            failed=len(validation_errors),
        )

        if dry_run:
            logger.info("DRY RUN — no invoices will be created")
            for row in validated:
                logger.info(
                    "  [DRY RUN] Row %d: %s | $%.2f | customer=%s",
                    row.row_number,
                    row.date,
                    row.amount,
                    row.customer_id,
                )
            return result

        for row in validated:
            try:
                self.invoices.create_invoice(
                    customer_id=row.customer_id,
                    line_items=[
                        {
                            "item_id": row.item_id,
                            "rate": row.amount,
                            "quantity": 1,
                            "description": row.description,
                        }
                    ],
                    date=row.date,
                )
                result.succeeded += 1
                logger.info(
                    "  Row %d: OK ($%.2f)", row.row_number, row.amount
                )
            except Exception as e:
                result.failed += 1
                result.errors.append({"row": row.row_number, "error": str(e)})
                logger.error("  Row %d: FAILED — %s", row.row_number, e)

        return result
