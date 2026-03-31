"""
Generate a CSV preview of invoices to be created.

Usage:
    python3 preview_invoices.py transaction-history.csv -o invoices_preview.csv
"""

import csv
import sys
from typing import List, Dict

import click

from invoice_templates import InvoiceGenerator


def parse_wise_csv(csv_path: str) -> List[Dict]:
    """Parse Wise transaction CSV and extract incoming payments."""
    transactions = []

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            direction = row.get("Direction", "").strip()
            status = row.get("Status", "").strip()
            source_name = row.get("Source name", "").strip()

            # Only process completed incoming transfers
            if direction != "IN" or status != "COMPLETED":
                continue

            # Only process known clients
            if "GILAD WEINBERG" not in source_name.upper() and \
               "AMZEXPERTGLOBALL" not in source_name.upper():
                continue

            # Extract relevant data
            created_date = row.get("Created on", "").strip()
            amount_str = row.get("Source amount (after fees)", "").strip()

            # Parse date (format: "2026-03-06 19:57:01")
            invoice_date = created_date.split(" ")[0] if created_date else ""

            # Parse amount
            try:
                amount = float(amount_str) if amount_str else 0.0
            except ValueError:
                continue

            transactions.append({
                "client_name": source_name,
                "date": invoice_date,
                "amount": amount,
                "reference": row.get("Reference", "").strip(),
            })

    return transactions


@click.command()
@click.argument("csv_file", type=click.Path(exists=True))
@click.option("-o", "--output", default="invoices_preview.csv", help="Output CSV file")
def main(csv_file: str, output: str):
    """Generate CSV preview of invoices to be created."""

    # Parse transactions
    click.echo(f"Parsing {csv_file}...")
    transactions = parse_wise_csv(csv_file)

    if not transactions:
        click.echo("No incoming transactions found from known clients.")
        return

    click.echo(f"Found {len(transactions)} incoming transactions.\n")

    # Generate invoice preview data
    preview_data = []

    for txn in transactions:
        try:
            # Generate invoice data
            invoice_data = InvoiceGenerator.generate_invoice_data(
                client_name=txn["client_name"],
                wire_amount=txn["amount"],
                wire_date=txn["date"],
                customer_id="<placeholder>"
            )

            # Extract line items
            line_items = invoice_data["line_items"]

            # For Gilad (2 line items)
            if len(line_items) == 2:
                preview_data.append({
                    "Invoice Number": invoice_data["invoice_number"],
                    "Client": txn["client_name"],
                    "Date": txn["date"],
                    "Wire Amount": f"${txn['amount']:.2f}",
                    "Line 1 - Description": line_items[0]["name"],
                    "Line 1 - Amount": f"${line_items[0]['rate']:.2f}",
                    "Line 2 - Description": line_items[1]["name"],
                    "Line 2 - Amount": f"${line_items[1]['rate']:.2f}",
                    "Total Invoice": f"${txn['amount']:.2f}",
                    "Notes": invoice_data["notes"][:100] + "..."
                })
            # For Amz-expert (1 line item)
            else:
                preview_data.append({
                    "Invoice Number": invoice_data["invoice_number"],
                    "Client": txn["client_name"],
                    "Date": txn["date"],
                    "Wire Amount": f"${txn['amount']:.2f}",
                    "Line 1 - Description": line_items[0]["name"],
                    "Line 1 - Amount": f"${line_items[0]['rate']:.2f}",
                    "Line 2 - Description": "",
                    "Line 2 - Amount": "",
                    "Total Invoice": f"${txn['amount']:.2f}",
                    "Notes": invoice_data["notes"][:100] + "..."
                })

        except Exception as e:
            click.echo(f"Error processing {txn['client_name']} on {txn['date']}: {e}")
            continue

    # Write to CSV
    if preview_data:
        fieldnames = [
            "Invoice Number",
            "Client",
            "Date",
            "Wire Amount",
            "Line 1 - Description",
            "Line 1 - Amount",
            "Line 2 - Description",
            "Line 2 - Amount",
            "Total Invoice",
            "Notes"
        ]

        with open(output, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(preview_data)

        click.echo(f"\n✓ Preview saved to: {output}")
        click.echo(f"  Total invoices: {len(preview_data)}")

        # Calculate totals
        total_gilad = sum(
            float(row["Wire Amount"].replace("$", "").replace(",", ""))
            for row in preview_data
            if "GILAD" in row["Client"]
        )
        total_amz = sum(
            float(row["Wire Amount"].replace("$", "").replace(",", ""))
            for row in preview_data
            if "AMZ" in row["Client"].upper()
        )

        click.echo(f"  Gilad Weinberg: ${total_gilad:,.2f}")
        click.echo(f"  Amz-expert Global: ${total_amz:,.2f}")
        click.echo(f"  Grand Total: ${total_gilad + total_amz:,.2f}")
    else:
        click.echo("No invoices to preview.")


if __name__ == "__main__":
    main()
