"""Action handlers for scheduled reminders.

Each handler receives (conn, reminder, today) and returns a Markdown-ish
text message. The tick layer takes care of channel delivery (Telegram /
HTTP API / etc.) and audit logging.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from calendar import monthrange


# ---- payroll_reminder -----------------------------------------------------

def _payroll_period_for_today(today: date) -> tuple:
    """Given today (a reminder firing date), figure out which Pacific Edge
    Hubstaff period the user needs to pay for.

    Liran's rule (from the conversation he had with Goldman):
      * Hubstaff cuts at the 15th and end-of-month.
      * He reminds on the 4th (covers prior month's 16th → end)
        and the 19th (covers this month's 1st → 15th).

    The exact firing date can shift (e.g. fired late, fired manually);
    just pick the most-recent CLOSED period whose stop date is the
    closest <= today.
    """
    # Candidate periods near today: previous-month half-2, this-month half-1
    # and this-month half-2 (in case the reminder is late).
    candidates = []
    # this month, half-1: 1..15
    candidates.append((date(today.year, today.month, 1),
                       date(today.year, today.month, 15)))
    # this month, half-2: 16..end_of_month
    last_day_this = monthrange(today.year, today.month)[1]
    candidates.append((date(today.year, today.month, 16),
                       date(today.year, today.month, last_day_this)))
    # previous month, half-2: 16..end_of_month
    prev = (today.replace(day=1) - timedelta(days=1))
    last_day_prev = monthrange(prev.year, prev.month)[1]
    candidates.append((date(prev.year, prev.month, 16),
                       date(prev.year, prev.month, last_day_prev)))
    # previous month, half-1: 1..15
    candidates.append((date(prev.year, prev.month, 1),
                       date(prev.year, prev.month, 15)))
    # Pick the most-recent period whose stop is strictly before today.
    closed = [(s, e) for (s, e) in candidates if e < today]
    if not closed:
        return candidates[0]
    return max(closed, key=lambda se: se[1])


def _payroll_summary_text(conn, start: date, stop: date) -> str:
    """Reuse the bot tool's payroll_summary handler but bypass ctx
    (we don't have a ToolContext at scheduler time)."""
    from goldman.bot.tools import _hubstaff_payroll_summary
    from unittest.mock import MagicMock
    ctx = MagicMock()
    ctx.conn = conn
    ctx.chat_id = "scheduler-tick"
    return _hubstaff_payroll_summary(ctx, {
        "start": start.isoformat(),
        "stop": stop.isoformat(),
    })


def _compute_prediction(conn, start: date, stop: date) -> dict:
    """Run the Hubstaff payroll math and return a structured prediction
    we can persist + later compare against actual Wise outflows."""
    import os
    from decimal import Decimal
    from goldman.hubstaff.client import HubstaffClient
    from goldman.hubstaff.rates import MemberRateRepository

    client = HubstaffClient()
    rows = client.daily_activities(start=start.isoformat(),
                                    stop=stop.isoformat())
    _, users = client.members()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM goldman.entities WHERE slug='seo'")
        seo_id = cur.fetchone()[0]
    rates = {r.hubstaff_user_id: r
              for r in MemberRateRepository(conn).list_for_entity(seo_id)}

    # Aggregate hours per user.
    agg = {}
    for r in rows:
        uid = r["user_id"]
        agg[uid] = agg.get(uid, 0) + int(r.get("tracked") or 0)

    breakdown = []
    total = Decimal("0.00")
    period_days = (stop - start).days + 1
    import calendar
    for uid, secs in agg.items():
        hours = round(secs / 3600.0, 2)
        name = users.get(uid, {}).get("name", f"user_{uid}")
        rate = rates.get(uid)
        if not rate:
            breakdown.append({"user_id": uid, "name": name, "hours": hours,
                              "rate": None, "rate_unit": None,
                              "amount": None, "note": "no rate on file"})
            continue
        if rate.rate_unit == "hour":
            amount = (Decimal(hours).quantize(Decimal("0.01")) *
                      Decimal(rate.rate_amount).quantize(Decimal("0.01")))
            amount = amount.quantize(Decimal("0.01"))
            breakdown.append({"user_id": uid, "name": name, "hours": hours,
                              "rate": float(rate.rate_amount),
                              "rate_unit": "hour",
                              "amount": float(amount), "note": ""})
            total += amount
        elif rate.rate_unit == "half_month":
            # Fixed amount per half-month pay period. Don't pro-rate by days.
            amount = Decimal(rate.rate_amount).quantize(Decimal("0.01"))
            breakdown.append({"user_id": uid, "name": name, "hours": hours,
                              "rate": float(rate.rate_amount),
                              "rate_unit": "half_month",
                              "amount": float(amount),
                              "note": "fixed per pay period"})
            total += amount
        elif rate.rate_unit == "month":
            month_days = calendar.monthrange(start.year, start.month)[1]
            amount = (Decimal(rate.rate_amount) * Decimal(period_days)
                       / Decimal(month_days)).quantize(Decimal("0.01"))
            breakdown.append({"user_id": uid, "name": name, "hours": hours,
                              "rate": float(rate.rate_amount),
                              "rate_unit": "month",
                              "amount": float(amount),
                              "note": f"pro-rata {period_days}/{month_days} days"})
            total += amount
        else:
            breakdown.append({"user_id": uid, "name": name, "hours": hours,
                              "rate": float(rate.rate_amount),
                              "rate_unit": rate.rate_unit,
                              "amount": None,
                              "note": "unsupported rate unit"})
    return {
        "period_start": start.isoformat(),
        "period_stop": stop.isoformat(),
        "total_amount": float(total),
        "currency": "USD",
        "breakdown": breakdown,
    }


def _persist_prediction(conn, *, entity_slug: str, prediction: dict,
                        source_reminder_id=None) -> object:
    """Insert or update the prediction row for this period."""
    import json
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM goldman.entities WHERE slug=%s",
                     (entity_slug,))
        eid = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO goldman.payroll_predictions
              (entity_id, period_start, period_stop, breakdown,
               total_amount, currency, source_reminder_id)
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
            ON CONFLICT (entity_id, period_start, period_stop) DO UPDATE
              SET breakdown = EXCLUDED.breakdown,
                  total_amount = EXCLUDED.total_amount,
                  currency = EXCLUDED.currency,
                  source_reminder_id = EXCLUDED.source_reminder_id,
                  updated_at = now()
            RETURNING id
            """,
            (eid, prediction["period_start"], prediction["period_stop"],
             json.dumps(prediction["breakdown"]),
             prediction["total_amount"], prediction["currency"],
             source_reminder_id),
        )
        return cur.fetchone()[0]


def action_payroll_reminder(conn, reminder, today: date) -> str:
    """Produce the payroll-due message AND persist the prediction so
    Phase 12 reconciliation can later compare it to actual Wise outflows."""
    start, stop = _payroll_period_for_today(today)
    # 1. Save the structured prediction.
    try:
        prediction = _compute_prediction(conn, start, stop)
        _persist_prediction(conn,
                            entity_slug=reminder.entity_slug or "seo",
                            prediction=prediction,
                            source_reminder_id=reminder.id)
        conn.commit()
    except Exception as e:
        prediction = None
    # 2. Build the user-facing payroll table (re-uses the existing tool).
    body = _payroll_summary_text(conn, start, stop)
    # Reconciliation hint matches Phase 12 — Hubstaff's own records, not Wise emails.
    reconcile_day = 10 if stop.day != 15 else 25
    return (
        f"*Payroll reminder — {reminder.name}*\n"
        f"It's {today.strftime('%a %b %-d')}. Time to send Wise payments "
        f"for the {start.isoformat()} → {stop.isoformat()} period.\n\n"
        f"{body}\n\n"
        f"_Auto-reconciliation against Hubstaff's team payments runs on day "
        f"{reconcile_day} of next cycle._"
    )


# ---- payroll_reconciliation ------------------------------------------------

def _gmail_wise_outflows(conn, start: date, stop: date) -> list:
    """Search Gmail for Wise outbound transfer confirmations between start
    and stop (inclusive). Returns a list of {date, recipient, amount, currency}.

    Uses Claude (via _document_extract_with_tool) to parse each thread's
    plaintext, since Wise email formats vary across regions / product
    updates and a strict regex would silently miss money.
    """
    import os
    from goldman.gmail.client import GoldmanGmailClient
    from goldman.llm import GoldmanLLM
    try:
        client = GoldmanGmailClient()
    except Exception as e:
        return []
    # Cast a wide net — outbound transfers can come from several Wise
    # addresses and subject lines vary by product line.
    queries = [
        f'from:noreply@wise.com after:{start.isoformat()} before:{(stop).isoformat()}',
        f'from:wise.com transfer after:{start.isoformat()} before:{(stop).isoformat()}',
        f'from:transferwise.com after:{start.isoformat()} before:{(stop).isoformat()}',
    ]
    seen_thread_ids = set()
    threads = []
    for q in queries:
        try:
            for msg in client.search(query=q, limit=50):
                tid = msg.get("thread_id")
                if tid and tid not in seen_thread_ids:
                    seen_thread_ids.add(tid)
                    try:
                        threads.append(client.get_thread(thread_id=tid))
                    except Exception:
                        pass
        except Exception:
            pass
    if not threads:
        return []

    llm = GoldmanLLM()
    EXTRACT_SCHEMA = {
        "type": "object",
        "properties": {
            "transfers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date":       {"type": "string"},
                        "recipient":  {"type": "string"},
                        "amount":     {"type": "number"},
                        "currency":   {"type": "string"},
                        "is_outflow": {"type": "boolean"},
                    },
                    "required": ["amount", "currency", "is_outflow"],
                },
            },
        },
        "required": ["transfers"],
    }
    outflows = []
    SYSTEM = (
        "You parse Wise transfer confirmation emails. Extract every "
        "OUTBOUND transfer (money leaving the user's Wise account) with "
        "its recipient, amount, and currency. Skip inbound transfers and "
        "fee-only / status update emails."
    )
    for t in threads:
        body_text = "\n\n".join(
            f"From: {m.get('from')}\nSubject: {m.get('subject')}\nDate: {m.get('date')}\n\n{m.get('body_text', '')[:4000]}"
            for m in t.get("messages", [])
        )
        if not body_text.strip():
            continue
        try:
            result = llm.extract_with_tool(
                system=SYSTEM, user_text=body_text,
                tool_name="extract_transfers", tool_schema=EXTRACT_SCHEMA,
            )
            for tr in result.get("transfers", []):
                if tr.get("is_outflow"):
                    outflows.append({
                        "date": tr.get("date", ""),
                        "recipient": tr.get("recipient", ""),
                        "amount": float(tr["amount"]),
                        "currency": tr.get("currency", "USD"),
                    })
        except Exception:
            continue
    return outflows


def _hubstaff_actual_payments(start: date, stop: date) -> list:
    """Pull the AUTHORITATIVE per-recipient payment records from Hubstaff's
    own team_payments endpoint. This is Hubstaff's own record of what got
    paid (gateway, completion status, currency, recipient) — far cleaner
    than parsing Wise emails."""
    from goldman.hubstaff.client import HubstaffClient
    try:
        client = HubstaffClient()
    except Exception:
        return []
    try:
        return client.team_payments(
            start=start.isoformat(), stop=stop.isoformat(),
            only_complete=True,
        )
    except Exception:
        return []


def action_payroll_reconciliation(conn, reminder, today: date) -> str:
    """Compare the most recent unreconciled prediction against Hubstaff's
    own record of completed team payments. Hubstaff is the SOURCE OF TRUTH
    for what got paid (it tracks the Wise gateway calls itself), so no
    email parsing is needed."""
    # 1. Find the unreconciled prediction whose period ended most recently.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, period_start, period_stop, total_amount, currency
            FROM goldman.payroll_predictions
            WHERE reconciled_at IS NULL
              AND period_stop <= %s
            ORDER BY period_stop DESC
            LIMIT 1
            """,
            (today,),
        )
        row = cur.fetchone()
    if not row:
        return (
            f"🔍 *Reconciliation — {reminder.name}*\n"
            f"No unreconciled payroll predictions on file. "
            f"Either the payroll reminder didn't fire (so no prediction "
            f"was saved) or everything's already reconciled."
        )
    pred_id, p_start, p_stop, p_total, p_curr = row
    p_total = float(p_total)

    # 2. Pull Hubstaff's completed payments whose period overlaps the
    # predicted one. Liran pays a few days after period stop, so we look
    # at Hubstaff payment records whose stop_date is within [p_stop, today].
    payments = _hubstaff_actual_payments(p_stop, today)
    # Keep only the payments whose Hubstaff `stop_date` equals our predicted
    # period stop — that ties each actual payment to the exact period we
    # predicted (so we don't double-count or pull in an unrelated payment).
    matching = [p for p in payments
                 if (p.get("stop_date") or "") == p_stop.isoformat()]
    actual_total = round(sum(p["amount"] for p in matching), 2)
    delta = round(actual_total - p_total, 2)
    tolerance = max(5.00, p_total * 0.005)  # ±$5 or ±0.5%

    # 3. Per-VA reconciliation — pinpoint exactly who is off.
    predicted_by_user = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT breakdown FROM goldman.payroll_predictions WHERE id=%s",
            (pred_id,),
        )
        breakdown = cur.fetchone()[0] or []
    for line in breakdown:
        if line.get("amount") is not None:
            predicted_by_user[line["user_id"]] = {
                "name": line.get("name", str(line["user_id"])),
                "predicted": float(line["amount"]),
                "actual": 0.0,
            }
    for p in matching:
        uid = p["user_id"]
        rec = predicted_by_user.get(uid)
        if rec is None:
            predicted_by_user[uid] = {
                "name": f"user_{uid}",
                "predicted": 0.0,
                "actual": p["amount"],
            }
        else:
            rec["actual"] += p["amount"]

    # 4. Persist the reconciliation result.
    note = (
        f"Hubstaff team_payments for period_stop={p_stop.isoformat()}: "
        f"{len(matching)} records summing ${actual_total:,.2f} vs predicted "
        f"${p_total:,.2f}; delta ${delta:+,.2f}."
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE goldman.payroll_predictions
            SET reconciled_at = now(),
                actual_amount = %s,
                delta_amount = %s,
                reconciliation_note = %s
            WHERE id = %s
            """,
            (actual_total, delta, note[:1000], pred_id),
        )
    conn.commit()

    # 5. Build the user-facing message — only loud when there IS a gap.
    if abs(delta) <= tolerance and matching:
        return (
            f"✅ *Reconciliation clean — {reminder.name}*\n"
            f"Period **{p_start.isoformat()} → {p_stop.isoformat()}**\n"
            f"Predicted: **${p_total:,.2f} {p_curr}**\n"
            f"Hubstaff records: **${actual_total:,.2f} {p_curr}** "
            f"across {len(matching)} completed payments\n"
            f"Delta: ${delta:+,.2f} — within ±${tolerance:,.2f} tolerance. "
            f"Nothing to do."
        )

    # Either mismatch OR no payments found at all.
    lines = [
        f"⚠️ *Reconciliation MISMATCH — {reminder.name}*",
        f"Period **{p_start.isoformat()} → {p_stop.isoformat()}**",
        f"Predicted: **${p_total:,.2f} {p_curr}**",
        f"Hubstaff records: **${actual_total:,.2f} {p_curr}** "
        f"({len(matching)} completed payments)",
        f"Delta: **${delta:+,.2f}** — outside ±${tolerance:,.2f} tolerance.",
    ]
    if not matching:
        lines.append("")
        lines.append("⚠️ No completed Hubstaff payments tagged to this period. "
                     "Either the payments haven't been pushed yet, were paid "
                     "outside Hubstaff (rate-only Wise transfer), or the "
                     "period dates don't match what Hubstaff has on file.")
    else:
        lines.append("")
        lines.append("Per-VA breakdown:")
        rows = sorted(predicted_by_user.values(),
                       key=lambda r: -abs(r["actual"] - r["predicted"]))
        for r in rows[:15]:
            d = r["actual"] - r["predicted"]
            flag = "✅" if abs(d) <= 1 else "⚠️"
            lines.append(
                f"  {flag} {r['name']:28} predicted ${r['predicted']:>8,.2f}  "
                f"actual ${r['actual']:>8,.2f}  delta ${d:+,.2f}"
            )
    lines.append("")
    lines.append("Please investigate. Common causes: a VA missed payment, "
                  "rate changed mid-period, FX adjustment on the Wise transfer.")
    return "\n".join(lines)


# ---- generic_note_reminder -----------------------------------------------

def action_generic_note(conn, reminder, today: date) -> str:
    """Just remind Liran of the configured text."""
    note = (reminder.action_params or {}).get("note") or reminder.name
    return f"🔔 *Reminder — {reminder.name}*\n{note}"


# ---- saas_invoice_filing --------------------------------------------------

def action_saas_invoice_filing(conn, reminder, today: date) -> str:
    """File last month's SaaS subscription invoice PDFs from Liran's personal
    Gmail into Drive under AMZ-Expert Global Limited / <Year> / <Month>.

    Fires on the 2nd; searches from the 1st of the *previous* month through now
    so the just-closed month is captured. Idempotent — already-filed PDFs are
    skipped, so re-runs and overlapping windows are safe.
    """
    import os
    from goldman.gmail.client import build_personal_service, GoldmanGmailConfigError
    from goldman.drive.client import GoogleDriveClient, DriveConfigError
    from goldman.invoices.filing import file_invoices

    root = os.getenv("GOLDMAN_DRIVE_ROOT_FOLDER_ID", "")
    if not root:
        return "⚠️ *SaaS invoice filing skipped* — GOLDMAN_DRIVE_ROOT_FOLDER_ID not set."

    # First day of the previous calendar month.
    first_this = today.replace(day=1)
    prev_last = first_this - timedelta(days=1)
    after = prev_last.replace(day=1).strftime("%Y/%m/%d")

    try:
        gmail = build_personal_service()
        drive = GoogleDriveClient()
    except (GoldmanGmailConfigError, DriveConfigError) as e:
        return f"⚠️ *SaaS invoice filing skipped* — {e}"

    try:
        report = file_invoices(gmail, drive, root, after=after)
    except Exception as e:  # never let one bad run kill the whole tick
        return f"⚠️ *SaaS invoice filing failed* — {e}"

    uploaded = report["uploaded"]
    if not uploaded:
        return (f"🧾 *SaaS invoice filing* — checked since {after}, "
                f"nothing new to file ({report['discovered']} already on record).")
    lines = "\n".join(f"• {u}" for u in uploaded)
    return (f"🧾 *SaaS invoices filed* — {len(uploaded)} new PDF(s) into "
            f"AMZ-Expert Global Limited:\n{lines}")


ACTIONS = {
    "payroll_reminder":       action_payroll_reminder,
    "payroll_reconciliation": action_payroll_reconciliation,
    "generic_note":           action_generic_note,
    "saas_invoice_filing":    action_saas_invoice_filing,
}


def run_action(conn, reminder, today: date) -> str:
    handler = ACTIONS.get(reminder.action)
    if not handler:
        return f"⚠️ Unknown reminder action {reminder.action!r}."
    return handler(conn, reminder, today)
