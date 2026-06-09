"""HTTP endpoint handlers for the Goldman API (Phase 5 plugin server)."""

from __future__ import annotations

from goldman.decisions import decision_timeline
from goldman.embeddings import EmbeddingClient
from goldman.who import build_who_view
from goldman_db.bills import BillRepository
from goldman_db.connection import app_conn
from goldman_db.entities import EntityRepository
from goldman_db.facts import FactRepository
from goldman_db.hybrid_search import hybrid_search


def _serialise_summary(s) -> dict:
    return {
        "slug": s.slug,
        "legal_name": s.legal_name,
        "jurisdiction": s.jurisdiction,
        "parent_entity_id": str(s.parent_entity_id) if getattr(s, "parent_entity_id", None) else None,
        "base_currency": s.base_currency,
        "fiscal_year_end": s.fiscal_year_end,
        "registered_address": s.registered_address,
        "company_number": s.company_number,
        "tax_registrations": [
            {"tax_type": tr.tax_type, "jurisdiction": tr.jurisdiction,
             "registration_number": tr.registration_number,
             "filing_cadence": tr.filing_cadence}
            for tr in s.tax_registrations
        ],
        "bank_accounts": [
            {"provider": b.provider, "account_label": b.account_label,
             "currency": b.currency}
            for b in s.bank_accounts
        ],
        "top_clients": [
            {"name": c.contact_name, "tier": c.tier}
            for c in s.top_clients
        ],
        "top_vendors": [
            {"name": v.vendor_name, "category": v.category}
            for v in s.top_vendors
        ],
        # Phase 6.4 cross-entity fields
        "intercompany_flow": getattr(s, "intercompany_flow", None) or {
            "count": 0, "total": 0.0, "currency": None, "counterpart": None,
        },
        "last_tp_doc": getattr(s, "last_tp_doc", None),
    }


def handle_who(*, query: dict, body: dict) -> tuple:
    from goldman_db.bank_accounts import BankAccountRepository
    from goldman_db.clients import ClientRepository
    from goldman_db.tax_registrations import TaxRegistrationRepository
    from goldman_db.vendors import VendorRepository

    with app_conn() as conn:
        summaries = build_who_view(
            entities_repo=EntityRepository(conn),
            tax_repo=TaxRegistrationRepository(conn),
            bank_repo=BankAccountRepository(conn),
            clients_repo=ClientRepository(conn),
            vendors_repo=VendorRepository(conn),
            conn=conn,
        )
    return 200, {"entities": [_serialise_summary(s) for s in summaries]}


def handle_recall(*, query: dict, body: dict) -> tuple:
    question = (body or {}).get("question") or (query.get("q", [""])[0] if query else "")
    if not question:
        return 400, {"error": "Missing 'question' in body."}

    entity_slug = (body or {}).get("entity") or (query.get("entity", [None])[0] if query else None)
    top_n = int((body or {}).get("top", 10))

    embedder = EmbeddingClient()
    vec = embedder.embed_batch([question])[0]

    with app_conn() as conn:
        entity_id = None
        if entity_slug:
            ent = EntityRepository(conn).get_by_slug(entity_slug.lower())
            if ent:
                entity_id = ent.id
        results = hybrid_search(
            conn, query_embedding=vec, query_text=question,
            entity_id=entity_id, top_n=top_n,
        )

    return 200, {
        "results": [
            {"source_type": r.source_type, "source_id": str(r.source_id),
             "excerpt": r.excerpt[:500], "score": r.score,
             "metadata": r.metadata}
            for r in results
        ],
    }


def handle_remember(*, query: dict, body: dict) -> tuple:
    body = body or {}
    text = body.get("text")
    kind = body.get("kind", "note")
    entity = body.get("entity", "amzg")
    if not text:
        return 400, {"error": "Missing 'text' in body."}
    if kind not in {"target", "preference", "constraint",
                     "commitment", "event", "decision", "note"}:
        return 400, {"error": f"Bad kind: {kind}"}

    with app_conn() as conn:
        entity_id = None
        if entity and entity != "global":
            ent = EntityRepository(conn).get_by_slug(entity.lower())
            entity_id = ent.id if ent else None
        new_id = FactRepository(conn).upsert(
            entity_id=entity_id, kind=kind, fact=text,
            source="user_explicit",
        )

    return 201, {"fact_id": str(new_id), "kind": kind, "entity": entity}


def handle_pending_bills(*, query: dict, body: dict) -> tuple:
    with app_conn() as conn:
        bills = BillRepository(conn).list_pending_partial_writes(limit=50)

    return 200, {
        "bills": [
            {
                "id": str(b.id),
                "vendor": b.vendor_name_at_intake,
                "amount": float(b.amount), "currency": b.currency,
                "in_storage": b.in_storage,
                "in_drive": b.in_drive,
                "in_zoho": b.in_zoho,
                "status": b.status,
                "last_error": b.last_error,
            }
            for b in bills
        ],
    }


def handle_status(*, query: dict, body: dict) -> tuple:
    with app_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM goldman.entities")
            entities = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM goldman.bills WHERE status = 'pending' OR status = 'partial'")
            pending_bills = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM goldman.pending_confirmations WHERE answered_at IS NULL")
            pending_confs = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM goldman.facts WHERE embedding IS NULL")
            facts_to_embed = cur.fetchone()[0]

    return 200, {
        "service": "goldman",
        "entities": entities,
        "pending_bills": pending_bills,
        "pending_confirmations": pending_confs,
        "facts_awaiting_embedding": facts_to_embed,
    }


def handle_decisions(*, query: dict, body: dict) -> tuple:
    body = body or {}
    topic = (body.get("topic") or "").strip()
    if not topic:
        return 400, {"error": "Missing or empty 'topic' in body."}

    entity = body.get("entity")
    limit = int(body.get("limit", 20))

    with app_conn() as conn:
        results = decision_timeline(
            conn=conn, topic=topic, entity_slug=entity, limit=limit,
        )

    return 200, {
        "decisions": [
            {"id": str(r["id"]),
             "fact": r["fact"],
             "entity_slug": r["entity_slug"],
             "created_at": r["created_at"],
             "supersedes_id": str(r["supersedes_id"]) if r["supersedes_id"] else None}
            for r in results
        ],
    }
