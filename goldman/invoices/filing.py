"""File SaaS subscription invoice PDFs from a Gmail inbox into Goldman's Drive.

These vendors email Stripe-style "Your receipt from X" messages with the real
invoice as a PDF attachment. This module finds those emails, picks the official
Invoice PDF, and files it under <COMPANY_FOLDER>/<Year>/<Month> in Drive.

The Gmail service and Drive client are injected so the logic is unit-testable.
"""

from __future__ import annotations

import base64
from email.utils import parsedate_to_datetime

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

COMPANY_FOLDER = "AMZ-Expert Global Limited"

# Vendor name -> Gmail search query (date window is appended at call time).
# Only vendors that actually email a PDF invoice are listed.
DEFAULT_VENDORS = {
    "Lovable": "(from:lovable.dev OR Lovable) (invoice OR receipt)",
    "Miro": '("dba Miro" OR from:miro.com) (receipt OR invoice)',
    "Meshy": "(Meshy) (invoice OR receipt)",
    "Sellerboard": 'from:sellerboard.com ("Invoice Nr" OR invoice)',
    "RainforestAPI": "(Traject OR Rainforest) (invoice OR receipt)",
}


# ---- pure helpers (unit-tested directly) ----

def collect_pdf_attachments(payload, out=None):
    """Walk a Gmail message payload, collecting (filename, attachmentId) for
    every PDF attachment."""
    if out is None:
        out = []
    fn = payload.get("filename") or ""
    body = payload.get("body") or {}
    if fn.lower().endswith(".pdf") and body.get("attachmentId"):
        out.append((fn, body["attachmentId"]))
    for child in (payload.get("parts") or []):
        collect_pdf_attachments(child, out)
    return out


def choose_pdf(attachments):
    """Prefer the official Invoice PDF; fall back to the first PDF.

    `attachments` is a list of (filename, attachmentId). Returns one tuple or
    None.
    """
    if not attachments:
        return None
    invoices = [a for a in attachments if a[0].lower().startswith("invoice")]
    return invoices[0] if invoices else attachments[0]


def period_of(dt):
    """(year_str, month_name) for a datetime."""
    return str(dt.year), MONTHS[dt.month - 1]


def nice_name(vendor, dt, filename):
    """Stable, sortable filename: Vendor_YYYY-MM-DD_original.pdf."""
    return "%s_%s_%s" % (vendor, dt.strftime("%Y-%m-%d"), filename)


# ---- Gmail discovery ----

def _list_message_ids(gmail, query):
    ids, token = [], None
    while True:
        resp = gmail.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=token).execute()
        ids.extend(resp.get("messages", []) or [])
        token = resp.get("nextPageToken")
        if not token:
            break
    return ids


def discover_invoices(gmail, after, before=None, vendors=None):
    """Find invoice PDFs across vendors.

    after/before are Gmail date strings ('YYYY/MM/DD'); before is optional.
    Returns a list of dicts with vendor, message_id, attachment_id, filename,
    year, month, nice_name — de-duplicated on (year, month, nice_name).
    """
    vendors = vendors or DEFAULT_VENDORS
    window = "after:%s" % after + (" before:%s" % before if before else "")
    found, seen = [], set()
    for vendor, q in vendors.items():
        for m in _list_message_ids(gmail, "%s %s" % (q, window)):
            full = gmail.users().messages().get(
                userId="me", id=m["id"], format="full").execute()
            headers = {h["name"]: h["value"]
                       for h in full["payload"].get("headers", [])}
            try:
                dt = parsedate_to_datetime(headers.get("Date"))
            except Exception:
                continue
            chosen = choose_pdf(collect_pdf_attachments(full["payload"]))
            if not chosen:
                continue
            filename, attachment_id = chosen
            year, month = period_of(dt)
            name = nice_name(vendor, dt, filename)
            key = (year, month, name)
            if key in seen:
                continue
            seen.add(key)
            found.append({
                "vendor": vendor, "message_id": m["id"],
                "attachment_id": attachment_id, "filename": filename,
                "year": year, "month": month, "nice_name": name,
            })
    return found


# ---- Drive filing ----

def _ensure_month_folder(drive, root_id, year, month, cache):
    key = (year, month)
    if key in cache:
        return cache[key]
    company = (drive.find_folder(name=COMPANY_FOLDER, parent_id=root_id)
               or drive.create_folder(name=COMPANY_FOLDER, parent_id=root_id))
    y = (drive.find_folder(name=year, parent_id=company)
         or drive.create_folder(name=year, parent_id=company))
    m = (drive.find_folder(name=month, parent_id=y)
         or drive.create_folder(name=month, parent_id=y))
    cache[key] = m
    return m


def file_invoices(gmail, drive, root_folder_id, after, before=None,
                  vendors=None, dry_run=False):
    """Discover invoice PDFs and upload new ones to Drive by year/month.

    Returns {discovered, uploaded: [...], skipped: [...]}. Idempotent: a PDF
    already present in its month folder (by name) is skipped.
    """
    items = discover_invoices(gmail, after, before, vendors)
    report = {"discovered": len(items), "uploaded": [], "skipped": []}
    if dry_run:
        report["skipped"] = [it["nice_name"] for it in items]
        return report

    folder_cache, existing_cache = {}, {}
    for it in items:
        target = _ensure_month_folder(
            drive, root_folder_id, it["year"], it["month"], folder_cache)
        if target not in existing_cache:
            existing_cache[target] = {
                f["name"] for f in drive.list_children(parent_id=target, limit=1000)
            }
        if it["nice_name"] in existing_cache[target]:
            report["skipped"].append(it["nice_name"])
            continue
        att = gmail.users().messages().attachments().get(
            userId="me", messageId=it["message_id"], id=it["attachment_id"]
        ).execute()
        content = base64.urlsafe_b64decode(att["data"])
        drive.upload_file(name=it["nice_name"], parent_id=target,
                          content=content, mime_type="application/pdf")
        existing_cache[target].add(it["nice_name"])
        report["uploaded"].append("%s/%s/%s" % (it["year"], it["month"], it["nice_name"]))
    return report
