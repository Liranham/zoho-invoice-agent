"""Tests for SaaS invoice filing (Gmail receipts -> Drive by year/month)."""

from __future__ import annotations

import base64
from datetime import date
from unittest.mock import MagicMock

import pytest

from goldman.invoices import filing
from goldman.reminders.actions import ACTIONS, run_action


# ---- pure helpers ----

def test_collect_pdf_attachments_walks_nested_parts():
    payload = {
        "filename": "", "body": {},
        "parts": [
            {"filename": "Invoice-1.pdf", "body": {"attachmentId": "a1"}},
            {"filename": "logo.png", "body": {"attachmentId": "a2"}},
            {"filename": "", "body": {}, "parts": [
                {"filename": "Receipt-1.pdf", "body": {"attachmentId": "a3"}},
            ]},
        ],
    }
    atts = filing.collect_pdf_attachments(payload)
    assert atts == [("Invoice-1.pdf", "a1"), ("Receipt-1.pdf", "a3")]


def test_choose_pdf_prefers_invoice():
    atts = [("Receipt-2640.pdf", "r"), ("Invoice-9A7A.pdf", "i")]
    assert filing.choose_pdf(atts) == ("Invoice-9A7A.pdf", "i")


def test_choose_pdf_falls_back_to_first():
    atts = [("AC-20260610-754785.pdf", "x")]
    assert filing.choose_pdf(atts) == ("AC-20260610-754785.pdf", "x")
    assert filing.choose_pdf([]) is None


def test_period_and_nice_name():
    from datetime import datetime
    dt = datetime(2026, 1, 16, 9, 0)
    assert filing.period_of(dt) == ("2026", "January")
    assert filing.nice_name("Miro", dt, "Invoice-BB.pdf") == "Miro_2026-01-16_Invoice-BB.pdf"


# ---- discover + file with a mocked Gmail service ----

def _gmail_with_one_invoice():
    """A fake Gmail service returning a single Miro invoice email."""
    gmail = MagicMock()
    msgs = gmail.users.return_value.messages.return_value
    # list() returns one message, then no nextPageToken
    msgs.list.return_value.execute.return_value = {"messages": [{"id": "m1"}]}
    msgs.get.return_value.execute.return_value = {
        "payload": {
            "headers": [{"name": "Date", "value": "Fri, 16 Jan 2026 09:00:00 +0000"},
                        {"name": "Subject", "value": "Your receipt from Miro"}],
            "filename": "",
            "parts": [
                {"filename": "Invoice-BB.pdf", "body": {"attachmentId": "att1"}},
                {"filename": "Receipt-22.pdf", "body": {"attachmentId": "att2"}},
            ],
        }
    }
    msgs.attachments.return_value.get.return_value.execute.return_value = {
        "data": base64.urlsafe_b64encode(b"%PDF-fake").decode()
    }
    return gmail


def test_discover_invoices_picks_invoice_pdf_and_period():
    gmail = _gmail_with_one_invoice()
    items = filing.discover_invoices(gmail, after="2026/01/01",
                                     vendors={"Miro": "from:miro.com"})
    assert len(items) == 1
    it = items[0]
    assert it["vendor"] == "Miro"
    assert it["filename"] == "Invoice-BB.pdf"
    assert (it["year"], it["month"]) == ("2026", "January")
    assert it["nice_name"] == "Miro_2026-01-16_Invoice-BB.pdf"


def test_file_invoices_uploads_new_and_skips_existing():
    gmail = _gmail_with_one_invoice()
    drive = MagicMock()
    # folder resolution returns ids; month folder starts empty
    drive.find_folder.return_value = "folder_id"
    drive.list_children.return_value = []  # nothing there yet

    report = filing.file_invoices(gmail, drive, root_folder_id="root",
                                  after="2026/01/01",
                                  vendors={"Miro": "from:miro.com"})
    assert report["uploaded"] == ["2026/January/Miro_2026-01-16_Invoice-BB.pdf"]
    assert drive.upload_file.call_count == 1
    up = drive.upload_file.call_args.kwargs
    assert up["name"] == "Miro_2026-01-16_Invoice-BB.pdf"
    assert up["mime_type"] == "application/pdf"
    assert up["content"] == b"%PDF-fake"

    # Second run with the file already present -> skipped, no new upload.
    drive2 = MagicMock()
    drive2.find_folder.return_value = "folder_id"
    drive2.list_children.return_value = [{"name": "Miro_2026-01-16_Invoice-BB.pdf"}]
    report2 = filing.file_invoices(gmail, drive2, root_folder_id="root",
                                   after="2026/01/01",
                                   vendors={"Miro": "from:miro.com"})
    assert report2["uploaded"] == []
    assert report2["skipped"] == ["Miro_2026-01-16_Invoice-BB.pdf"]
    drive2.upload_file.assert_not_called()


def test_dry_run_uploads_nothing():
    gmail = _gmail_with_one_invoice()
    drive = MagicMock()
    report = filing.file_invoices(gmail, drive, root_folder_id="root",
                                  after="2026/01/01", vendors={"Miro": "x"},
                                  dry_run=True)
    assert report["discovered"] == 1
    drive.upload_file.assert_not_called()


# ---- action wiring ----

def test_saas_action_registered():
    assert "saas_invoice_filing" in ACTIONS


def test_saas_action_skips_cleanly_without_drive_root(monkeypatch):
    monkeypatch.delenv("GOLDMAN_DRIVE_ROOT_FOLDER_ID", raising=False)
    reminder = MagicMock()
    reminder.action = "saas_invoice_filing"
    out = run_action(MagicMock(), reminder, date(2026, 7, 2))
    assert "skipped" in out.lower()
