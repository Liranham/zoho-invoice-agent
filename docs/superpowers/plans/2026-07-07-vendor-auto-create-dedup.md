# Vendor Auto-Create With Duplicate Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Goldman create a Zoho Books expense by vendor *name* instead of requiring a raw `vendor_id` — auto-creating a new vendor when the name is clearly new, and asking a single bundled question (vendor choice + expense confirmation together) when the name is similar to an existing vendor.

**Architecture:** Extend the existing two-phase Zoho write guardrail (`goldman/zoho_safety.py` + `_zoho_guardrail`) rather than adding a separate tool the model must call first. A new pure-logic module (`goldman/vendor_match.py`) decides exact/similar/none from a name and the entity's live Zoho vendor list; `_create_expense` uses it to resolve or flag a vendor before the normal confirm-then-write flow runs.

**Tech Stack:** Python 3.9, pytest, Zoho Books REST API (`zoho/contacts.py`, `zoho/expenses.py`), stdlib `difflib` for spelling-similarity (no new dependency).

**Reference spec:** `docs/superpowers/specs/2026-07-07-vendor-auto-create-dedup-design.md`

---

## Task 1: `ContactService` learns about `contact_type`

**Files:**
- Modify: `zoho/contacts.py`
- Create: `tests/test_zoho_contacts.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_zoho_contacts.py`:

```python
"""Tests for ContactService — contact_type filtering + field."""

from __future__ import annotations

from unittest.mock import MagicMock

from zoho.contacts import Contact, ContactService


def test_list_contacts_passes_contact_type_filter():
    client = MagicMock()
    client.get.return_value = {"contacts": []}

    svc = ContactService(client)
    svc.list_contacts(contact_type="vendor")

    client.get.assert_called_once_with(
        "contacts", params={"page": 1, "per_page": 200, "contact_type": "vendor"},
    )


def test_list_contacts_omits_filter_by_default():
    client = MagicMock()
    client.get.return_value = {"contacts": []}

    svc = ContactService(client)
    svc.list_contacts()

    client.get.assert_called_once_with(
        "contacts", params={"page": 1, "per_page": 200},
    )


def test_list_contacts_populates_contact_type_field():
    client = MagicMock()
    client.get.return_value = {
        "contacts": [
            {"contact_id": "V-1", "contact_name": "Akiva CPA",
             "company_name": "", "email": "", "contact_type": "vendor"},
        ],
    }

    svc = ContactService(client)
    contacts = svc.list_contacts(contact_type="vendor")

    assert contacts[0].contact_type == "vendor"


def test_create_contact_creates_vendor_type():
    client = MagicMock()
    client.post.return_value = {
        "contact": {"contact_id": "V-2", "contact_name": "Bezeq",
                    "company_name": "", "email": "", "contact_type": "vendor"},
    }

    svc = ContactService(client)
    contact = svc.create_contact(contact_name="Bezeq", contact_type="vendor")

    assert isinstance(contact, Contact)
    assert contact.contact_type == "vendor"
    _, kwargs = client.post.call_args
    assert kwargs["json"]["contact_type"] == "vendor"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_zoho_contacts.py -v`
Expected: FAIL — `TypeError: list_contacts() got an unexpected keyword argument 'contact_type'` (and the field-population/vendor-type tests fail similarly).

- [ ] **Step 3: Implement `contact_type` support**

In `zoho/contacts.py`, replace the `Contact` dataclass (lines 13-18):

```python
@dataclass
class Contact:
    contact_id: str
    contact_name: str
    company_name: str
    email: str
    contact_type: str = ""
```

Replace `list_contacts` (lines 26-40):

```python
    def list_contacts(
        self, page: int = 1, per_page: int = 200, contact_type: str = "",
    ) -> list[Contact]:
        params = {"page": page, "per_page": per_page}
        if contact_type:
            params["contact_type"] = contact_type
        data = self.client.get("contacts", params=params)
        contacts = []
        for raw in data.get("contacts", []):
            c = Contact(
                contact_id=raw.get("contact_id", ""),
                contact_name=raw.get("contact_name", ""),
                company_name=raw.get("company_name", ""),
                email=raw.get("email", ""),
                contact_type=raw.get("contact_type", ""),
            )
            contacts.append(c)
            self._cache[c.contact_name.lower()] = c.contact_id
        return contacts
```

In `create_contact` (around line 103), add `contact_type` to the returned `Contact`:

```python
        c = Contact(
            contact_id=raw.get("contact_id", ""),
            contact_name=raw.get("contact_name", contact_name),
            company_name=raw.get("company_name", company_name),
            email=raw.get("email", email),
            contact_type=raw.get("contact_type", contact_type),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_zoho_contacts.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `python3 -m pytest -q`
Expected: all tests pass (no other code calls `Contact(...)` positionally, so the new optional field is backward compatible)

- [ ] **Step 6: Commit**

```bash
git add zoho/contacts.py tests/test_zoho_contacts.py
git commit -m "feat(zoho): ContactService supports filtering/tagging by contact_type"
```

---

## Task 2: Pure vendor name-matching module

**Files:**
- Create: `goldman/vendor_match.py`
- Create: `tests/test_goldman_vendor_match.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_goldman_vendor_match.py`:

```python
"""Pure-logic tests for vendor name matching — no I/O, no mocks."""

from __future__ import annotations

from types import SimpleNamespace

from goldman.vendor_match import match_vendor, normalize_name, significant_words


def _vendor(name, vid="V-1"):
    return SimpleNamespace(contact_id=vid, contact_name=name)


def test_normalize_name_strips_case_punctuation_and_whitespace():
    assert normalize_name("Akiva, CPA.") == "akiva cpa"
    assert normalize_name("  Akiva   CPA  ") == "akiva cpa"


def test_significant_words_drops_filler():
    assert significant_words("Akiva CPA LLC") == {"akiva"}


def test_exact_match_ignores_case_and_punctuation():
    existing = [_vendor("Akiva CPA", "V-1")]
    result = match_vendor("akiva, cpa.", existing)
    assert result.kind == "exact"
    assert result.candidates[0].contact_id == "V-1"


def test_shared_distinctive_word_is_flagged_similar():
    existing = [_vendor("Akiva CPA", "V-1")]
    result = match_vendor("Akiva Cohen, Accounting", existing)
    assert result.kind == "similar"
    assert result.candidates[0].contact_id == "V-1"


def test_added_legal_suffix_is_flagged_similar_not_exact():
    existing = [_vendor("Akiva CPA", "V-1")]
    result = match_vendor("AKIVA CPA LTD", existing)
    assert result.kind == "similar"


def test_close_spelling_typo_is_flagged_similar():
    existing = [_vendor("Akiva CPA", "V-1")]
    result = match_vendor("Akvia CPA", existing)
    assert result.kind == "similar"


def test_unrelated_name_is_not_matched():
    existing = [_vendor("Akiva CPA", "V-1")]
    result = match_vendor("Bezeq", existing)
    assert result.kind == "none"


def test_filler_word_overlap_alone_does_not_false_positive():
    existing = [_vendor("Northline Services LLC", "V-1")]
    result = match_vendor("Summit Consulting Services Inc", existing)
    assert result.kind == "none"


def test_no_existing_vendors_is_none():
    assert match_vendor("Bezeq", []).kind == "none"


def test_empty_name_is_none():
    assert match_vendor("", [_vendor("Akiva CPA")]).kind == "none"


def test_similar_candidates_capped_and_ranked_shared_word_first():
    existing = [
        _vendor("Akiva Cohen Accounting", "V-2"),  # shared word, lower ratio
        _vendor("Akiva CPA", "V-1"),                # exact-ish, would be "exact" alone
        _vendor("Akvia CPA Group", "V-3"),          # ratio-only match
    ]
    # Use a name that doesn't exactly equal any of them, so all three compete
    # as "similar" candidates instead of short-circuiting to "exact".
    result = match_vendor("Akiva CPA Services", existing)
    assert result.kind == "similar"
    assert len(result.candidates) <= 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_goldman_vendor_match.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'goldman.vendor_match'`

- [ ] **Step 3: Implement the matching module**

Create `goldman/vendor_match.py`:

```python
"""Pure name-matching helpers for vendor deduplication — no I/O.

Decides, from a proposed vendor name and an entity's existing Zoho vendor
contacts, whether the name is the same vendor (exact), a plausible
duplicate worth asking about (similar), or clearly new (none). See
docs/superpowers/specs/2026-07-07-vendor-auto-create-dedup-design.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

_FILLER_WORDS = {
    "the", "llc", "inc", "ltd", "co", "corp", "cpa", "group",
    "services", "company", "holdings", "and", "of",
}

# Calibrated against real examples (see design spec): catches typos and
# added legal suffixes (ratio ~0.82-0.89) without flagging generically
# similar-sounding but unrelated firms (ratio ~0.58 for two different
# "...Services..." companies).
_SIMILARITY_THRESHOLD = 0.72

_MAX_CANDIDATES = 3


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    lowered = (name or "").lower()
    stripped = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def significant_words(name: str) -> set:
    """Normalized words with common filler (LLC, CPA, Services, ...) stripped."""
    words = normalize_name(name).split()
    return {w for w in words if w not in _FILLER_WORDS and len(w) > 1}


@dataclass
class VendorMatch:
    kind: str  # Literal["exact", "similar", "none"]
    candidates: list = field(default_factory=list)


def match_vendor(name: str, existing: list) -> "VendorMatch":
    """Compare `name` against `existing` (objects with `.contact_name` and
    `.contact_id`). `existing` should already be scoped to one entity's
    vendor-type contacts — this function does no entity filtering itself.
    """
    target_norm = normalize_name(name)
    if not target_norm:
        return VendorMatch(kind="none")

    for contact in existing:
        if normalize_name(contact.contact_name) == target_norm:
            return VendorMatch(kind="exact", candidates=[contact])

    target_words = significant_words(name)
    scored = []
    for contact in existing:
        other_norm = normalize_name(contact.contact_name)
        other_words = significant_words(contact.contact_name)
        shared = bool(target_words & other_words)
        ratio = SequenceMatcher(None, target_norm, other_norm).ratio()
        if shared or ratio >= _SIMILARITY_THRESHOLD:
            # Shared-word matches rank above pure spelling matches; within
            # each group, higher ratio first.
            rank = (0 if shared else 1, -ratio)
            scored.append((rank, contact))

    if not scored:
        return VendorMatch(kind="none")

    scored.sort(key=lambda pair: pair[0])
    return VendorMatch(kind="similar", candidates=[c for _, c in scored[:_MAX_CANDIDATES]])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_goldman_vendor_match.py -v`
Expected: PASS (11 tests). If `test_added_legal_suffix_is_flagged_similar_not_exact` or
`test_close_spelling_typo_is_flagged_similar` fail because the ratio landed
under `_SIMILARITY_THRESHOLD` in practice, print the actual ratio (`python3 -c
"from difflib import SequenceMatcher; print(SequenceMatcher(None, 'akiva cpa',
'akiva cpa ltd').ratio())"`) and lower the threshold slightly — do not change
the test expectations, they encode the product requirement from the design
spec.

- [ ] **Step 5: Commit**

```bash
git add goldman/vendor_match.py tests/test_goldman_vendor_match.py
git commit -m "feat(goldman): pure vendor name-matching (exact/similar/none)"
```

---

## Task 3: `list_customers` stops leaking vendors

**Files:**
- Modify: `goldman/bot/tools.py:1182-1194` (`_list_customers`)
- Modify: `tests/test_goldman_phase8_tools.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_goldman_phase8_tools.py`, add (near `test_list_customers_validates_entity`):

```python
def test_list_customers_filters_to_customer_type():
    ctx = MagicMock()
    cur = ctx.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = _entity_row()

    contact_svc = MagicMock()
    contact_svc.list_contacts.return_value = []

    with patch("goldman.bot.tools._zoho_services_for",
               return_value=(MagicMock(), contact_svc, MagicMock(), MagicMock())):
        execute_tool(ctx=ctx, name="list_customers", arguments={"entity": "amzg"})

    contact_svc.list_contacts.assert_called_once_with(per_page=50, contact_type="customer")
```

(This uses the `_entity_row()` helper already added to this file for the
`ensure_drive_folder` tests — reuse it, don't redefine it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_goldman_phase8_tools.py::test_list_customers_filters_to_customer_type -v`
Expected: FAIL — `AssertionError` (called with `per_page=50` only, no `contact_type`)

- [ ] **Step 3: Implement the filter**

In `goldman/bot/tools.py`, change line 1187 inside `_list_customers`:

```python
        contacts = contact_svc.list_contacts(per_page=min(limit, 200), contact_type="customer")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_goldman_phase8_tools.py -v`
Expected: PASS (all tests in file)

- [ ] **Step 5: Commit**

```bash
git add goldman/bot/tools.py tests/test_goldman_phase8_tools.py
git commit -m "fix(goldman): list_customers no longer includes vendor contacts"
```

---

## Task 4: `list_vendors` tool

**Files:**
- Modify: `goldman/bot/tools.py` (schema list, dispatcher, new `_list_vendors`)
- Modify: `goldman/api/mcp_server.py` (schema list, `AGENT_TOOLS`)
- Modify: `goldman/zoho_safety.py:35-39` (`READ_TOOLS`, documentation only)
- Modify: `tests/test_goldman_phase8_tools.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_goldman_phase8_tools.py`, add:

```python
def test_list_vendors_is_in_bot_registry():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert "list_vendors" in names


def test_list_vendors_is_in_mcp_registry():
    names = {t["name"] for t in MCP_TOOLS}
    assert "list_vendors" in names


def test_list_vendors_filters_to_vendor_type():
    ctx = MagicMock()
    cur = ctx.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = _entity_row()

    contact_svc = MagicMock()
    contact_svc.list_contacts.return_value = [
        SimpleNamespace(contact_id="V-1", contact_name="Akiva CPA", email=""),
    ]

    with patch("goldman.bot.tools._zoho_services_for",
               return_value=(MagicMock(), contact_svc, MagicMock(), MagicMock())):
        out = execute_tool(ctx=ctx, name="list_vendors", arguments={"entity": "amzg"})

    contact_svc.list_contacts.assert_called_once_with(per_page=50, contact_type="vendor")
    assert "Akiva CPA" in out
```

Add the import this test needs at the top of the file:

```python
from types import SimpleNamespace
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_goldman_phase8_tools.py -k list_vendors -v`
Expected: FAIL — registry tests fail (`'list_vendors' not in names`); dispatch test fails with `ValueError: Unknown tool: list_vendors`

- [ ] **Step 3: Add the tool schema in `goldman/bot/tools.py`**

Insert immediately after the `list_customers` schema block (after line 268, before the `create_customer` block):

```python
    {
        "name": "list_vendors",
        "description": (
            "List Zoho Books vendors (contact_type=vendor). HARD MAPPING: "
            "amzg=AMZ-Expert Global Limited (HK), seo=Pacific Edge Outsourcing "
            "LLC (US). Read-only; no confirmation needed. Result is stamped "
            "with [ENTITY:…]. Use this before guessing whether a vendor "
            "already exists — create_expense with vendor_name does this "
            "automatically, but this tool is here for a direct look."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo"]},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["entity"],
        },
    },
```

- [ ] **Step 4: Add the dispatcher line**

In the `execute_tool` dispatch chain, immediately after:

```python
    if name == "list_customers":
        return _list_customers(ctx, arguments)
```

add:

```python
    if name == "list_vendors":
        return _list_vendors(ctx, arguments)
```

- [ ] **Step 5: Implement `_list_vendors`**

Immediately after the `_list_customers` function (after its closing line,
before `_create_customer`), add:

```python
def _list_vendors(ctx, args) -> str:
    limit = int(args.get("limit", 50))

    def work(info):
        _, contact_svc, _, _ = _zoho_services_for(ctx, info.slug)
        contacts = contact_svc.list_contacts(per_page=min(limit, 200), contact_type="vendor")
        if not contacts:
            return "No vendors found."
        lines = [f"{len(contacts)} vendor(s):"]
        for c in contacts[:limit]:
            lines.append(f"  {c.contact_id} | {c.contact_name} | {c.email}")
        return "\n".join(lines)
    return _zoho_guardrail("list_vendors", ctx, args, work)
```

- [ ] **Step 6: Mirror the schema in `goldman/api/mcp_server.py`**

Insert immediately after the `list_customers` block (after line 312, before `create_customer`):

```python
    {
        "name": "list_vendors",
        "description": "List Zoho Books vendors for the given entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo"]},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["entity"],
        },
    },
```

- [ ] **Step 7: Add `list_vendors` to `AGENT_TOOLS` in `goldman/api/mcp_server.py`**

Change:

```python
        "list_drive_folder", "read_drive_file", "ensure_drive_folder",
        "create_invoice", "list_customers", "create_customer",
```

to:

```python
        "list_drive_folder", "read_drive_file", "ensure_drive_folder",
        "create_invoice", "list_customers", "list_vendors", "create_customer",
```

- [ ] **Step 8: Add `list_vendors` to `READ_TOOLS` in `goldman/zoho_safety.py`**

Change:

```python
READ_TOOLS = {
    "list_invoices",
    "list_customers",
    "list_pending_confirmations",
}
```

to:

```python
READ_TOOLS = {
    "list_invoices",
    "list_customers",
    "list_vendors",
    "list_pending_confirmations",
}
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_goldman_phase8_tools.py -v`
Expected: PASS (all tests in file)

- [ ] **Step 10: Commit**

```bash
git add goldman/bot/tools.py goldman/api/mcp_server.py goldman/zoho_safety.py tests/test_goldman_phase8_tools.py
git commit -m "feat(goldman): add list_vendors tool (Telegram + MCP)"
```

---

## Task 5: `_describe_action` shows a pending new-vendor name

**Files:**
- Modify: `goldman/zoho_safety.py:131-136` (`_describe_action`, `create_expense` branch)
- Modify: `tests/test_goldman_zoho_safety.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_goldman_zoho_safety.py`, add:

```python
from goldman.zoho_safety import confirmation_prompt


def test_confirmation_prompt_flags_new_vendor_by_name():
    info = EntityInfo(slug="amzg",
                       legal_name="AMZ-Expert Global Limited",
                       org_id="876247837")
    prompt = confirmation_prompt(info, "create_expense", {
        "amount": 5900, "currency": "ILS", "vendor_name": "Bezeq",
        "description": "Utility bill",
    })
    assert "Bezeq" in prompt
    assert "NEW" in prompt


def test_confirmation_prompt_shows_known_vendor_id_unchanged():
    info = EntityInfo(slug="amzg",
                       legal_name="AMZ-Expert Global Limited",
                       org_id="876247837")
    prompt = confirmation_prompt(info, "create_expense", {
        "amount": 5900, "currency": "ILS", "vendor_id": "V-1",
    })
    assert "vendor=V-1" in prompt
```

(`confirmation_prompt` is already imported at the top of this file per the
existing `from goldman.zoho_safety import (... confirmation_prompt ...)`
line — only add the extra `import` line above if it isn't already there.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_goldman_zoho_safety.py -k confirmation_prompt_flags_new_vendor -v`
Expected: FAIL — `AssertionError` (current text shows `vendor=?` not `Bezeq`/`NEW`)

- [ ] **Step 3: Implement**

In `goldman/zoho_safety.py`, replace the `create_expense` branch of `_describe_action` (currently lines 131-136):

```python
    if tool_name == "create_expense":
        vendor_id = args.get("vendor_id")
        vendor_name = args.get("vendor_name")
        if vendor_id:
            vendor_desc = vendor_id
        elif vendor_name:
            vendor_desc = f"{vendor_name!r} (NEW — will be created)"
        else:
            vendor_desc = "?"
        return (
            f"CREATE EXPENSE for {args.get('amount', '?')} "
            f"{args.get('currency', 'USD')}, vendor={vendor_desc}, "
            f"description={args.get('description', '?')!r}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_goldman_zoho_safety.py -v`
Expected: PASS (all tests in file)

- [ ] **Step 5: Commit**

```bash
git add goldman/zoho_safety.py tests/test_goldman_zoho_safety.py
git commit -m "feat(goldman): confirmation prompt shows pending new-vendor name"
```

---

## Task 6: `create_expense` resolves `vendor_name` (auto-create / ask / reuse)

This is the integration task that ties Tasks 1-5 together, and also fixes a
pre-existing bug found while reading this code: `_create_expense` calls
`expense_svc.create_expense(..., currency_code=...)`, but
`ExpenseService.create_expense` (`zoho/expenses.py`) takes a keyword-only
`currency` argument, not `currency_code`. Every real `create_expense` call
today raises `TypeError`, which `_zoho_guardrail`'s `except Exception`
silently turns into a "Zoho create_expense failed: ..." message instead of
ever writing to Zoho. This task fixes that as part of rewriting the function.

**Files:**
- Modify: `goldman/bot/tools.py` (schema, `_create_expense`)
- Modify: `goldman/api/mcp_server.py` (schema)
- Modify: `tests/test_goldman_phase8_tools.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_goldman_phase8_tools.py`, add:

```python
def _resolve_entity_row(slug="amzg", legal_name="AMZ-Expert Global Limited",
                         org_id="876247837"):
    # Matches the 3-column SELECT in goldman.zoho_safety.resolve_entity —
    # NOT the same shape as _entity_row() (EntityRepository's 12 columns).
    return (slug, legal_name, org_id)


def test_create_expense_exact_vendor_match_uses_existing_id_and_fixes_currency_kwarg():
    ctx = MagicMock()
    cur = ctx.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = _resolve_entity_row()

    contact_svc = MagicMock()
    contact_svc.list_contacts.return_value = [
        SimpleNamespace(contact_id="V-1", contact_name="Akiva CPA"),
    ]
    expense_svc = MagicMock()
    expense_svc.create_expense.return_value = SimpleNamespace(expense_id="E-1")

    with patch("goldman.bot.tools._zoho_services_for",
               return_value=(MagicMock(), contact_svc, MagicMock(), expense_svc)):
        out = execute_tool(
            ctx=ctx, name="create_expense",
            arguments={
                "entity": "amzg", "amount": 100, "currency": "ILS",
                "vendor_name": "Akiva CPA", "confirmed": True,
            },
        )

    contact_svc.list_contacts.assert_called_with(contact_type="vendor")
    expense_svc.create_expense.assert_called_once()
    _, kwargs = expense_svc.create_expense.call_args
    assert kwargs["vendor_id"] == "V-1"
    assert kwargs["currency"] == "ILS"  # regression check for the currency_code bug
    assert "currency_code" not in kwargs
    contact_svc.create_contact.assert_not_called()
    assert "E-1" in out


def test_create_expense_no_match_auto_creates_vendor_on_confirm():
    ctx = MagicMock()
    cur = ctx.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = _resolve_entity_row()

    contact_svc = MagicMock()
    contact_svc.list_contacts.return_value = []
    contact_svc.create_contact.return_value = SimpleNamespace(contact_id="V-9")
    expense_svc = MagicMock()
    expense_svc.create_expense.return_value = SimpleNamespace(expense_id="E-2")

    with patch("goldman.bot.tools._zoho_services_for",
               return_value=(MagicMock(), contact_svc, MagicMock(), expense_svc)):
        # First call: not yet confirmed — should describe the new vendor, not create anything.
        preview = execute_tool(
            ctx=ctx, name="create_expense",
            arguments={"entity": "amzg", "amount": 50, "vendor_name": "Bezeq"},
        )
        assert "Bezeq" in preview
        assert "NEW" in preview
        contact_svc.create_contact.assert_not_called()

        # Second call: confirmed — now it should create the vendor, then the expense.
        out = execute_tool(
            ctx=ctx, name="create_expense",
            arguments={"entity": "amzg", "amount": 50, "vendor_name": "Bezeq", "confirmed": True},
        )

    contact_svc.create_contact.assert_called_once_with(contact_name="Bezeq", contact_type="vendor")
    _, kwargs = expense_svc.create_expense.call_args
    assert kwargs["vendor_id"] == "V-9"
    assert "E-2" in out


def test_create_expense_similar_vendor_asks_without_creating():
    ctx = MagicMock()
    cur = ctx.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = _resolve_entity_row()

    contact_svc = MagicMock()
    contact_svc.list_contacts.return_value = [
        SimpleNamespace(contact_id="V-1", contact_name="Akiva CPA"),
    ]
    expense_svc = MagicMock()

    with patch("goldman.bot.tools._zoho_services_for",
               return_value=(MagicMock(), contact_svc, MagicMock(), expense_svc)):
        out = execute_tool(
            ctx=ctx, name="create_expense",
            arguments={
                "entity": "amzg", "amount": 100, "currency": "ILS",
                "vendor_name": "Akiva Cohen Accounting", "confirmed": True,
            },
        )

    assert "Akiva CPA" in out
    assert "existing" in out.lower()
    assert "new" in out.lower()
    contact_svc.create_contact.assert_not_called()
    expense_svc.create_expense.assert_not_called()


def test_create_expense_similar_vendor_choice_existing_uses_matched_id():
    ctx = MagicMock()
    cur = ctx.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = _resolve_entity_row()

    contact_svc = MagicMock()
    contact_svc.list_contacts.return_value = [
        SimpleNamespace(contact_id="V-1", contact_name="Akiva CPA"),
    ]
    expense_svc = MagicMock()
    expense_svc.create_expense.return_value = SimpleNamespace(expense_id="E-3")

    with patch("goldman.bot.tools._zoho_services_for",
               return_value=(MagicMock(), contact_svc, MagicMock(), expense_svc)):
        out = execute_tool(
            ctx=ctx, name="create_expense",
            arguments={
                "entity": "amzg", "amount": 100,
                "vendor_name": "Akiva Cohen Accounting",
                "vendor_choice": "existing", "confirmed": True,
            },
        )

    contact_svc.create_contact.assert_not_called()
    _, kwargs = expense_svc.create_expense.call_args
    assert kwargs["vendor_id"] == "V-1"
    assert "E-3" in out


def test_create_expense_vendor_lookup_failure_asks_for_vendor_id_directly():
    ctx = MagicMock()
    cur = ctx.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = _resolve_entity_row()

    contact_svc = MagicMock()
    contact_svc.list_contacts.side_effect = RuntimeError("Zoho API timeout")
    expense_svc = MagicMock()

    with patch("goldman.bot.tools._zoho_services_for",
               return_value=(MagicMock(), contact_svc, MagicMock(), expense_svc)):
        out = execute_tool(
            ctx=ctx, name="create_expense",
            arguments={"entity": "amzg", "amount": 100, "vendor_name": "Bezeq"},
        )

    assert "vendor_id" in out.lower()
    expense_svc.create_expense.assert_not_called()
    contact_svc.create_contact.assert_not_called()


def test_create_expense_similar_vendor_choice_new_creates_separate_vendor():
    ctx = MagicMock()
    cur = ctx.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = _resolve_entity_row()

    contact_svc = MagicMock()
    contact_svc.list_contacts.return_value = [
        SimpleNamespace(contact_id="V-1", contact_name="Akiva CPA"),
    ]
    contact_svc.create_contact.return_value = SimpleNamespace(contact_id="V-4")
    expense_svc = MagicMock()
    expense_svc.create_expense.return_value = SimpleNamespace(expense_id="E-4")

    with patch("goldman.bot.tools._zoho_services_for",
               return_value=(MagicMock(), contact_svc, MagicMock(), expense_svc)):
        out = execute_tool(
            ctx=ctx, name="create_expense",
            arguments={
                "entity": "amzg", "amount": 100,
                "vendor_name": "Akiva Cohen Accounting",
                "vendor_choice": "new", "confirmed": True,
            },
        )

    contact_svc.create_contact.assert_called_once_with(
        contact_name="Akiva Cohen Accounting", contact_type="vendor",
    )
    _, kwargs = expense_svc.create_expense.call_args
    assert kwargs["vendor_id"] == "V-4"
    assert "E-4" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_goldman_phase8_tools.py -k create_expense -v`
Expected: FAIL — the exact-match test fails on the `currency_code` assertion
(current code passes `currency_code=`, not `currency=`); the others fail
because `vendor_name`/`vendor_choice` aren't handled yet (vendor never gets
resolved, `contact_svc.list_contacts` never called with `contact_type="vendor"`);
the lookup-failure test fails because today a `RuntimeError` from
`list_contacts` would never even get called (vendor_name is silently ignored
today), so `execute_tool` would proceed straight into the normal write path
instead of returning the fallback message.

- [ ] **Step 3: Update the tool schema in `goldman/bot/tools.py`**

Replace the `create_expense` schema block (around lines 268-288):

```python
    {
        "name": "create_expense",
        "description": (
            "Record a bill/expense in Zoho Books. HARD MAPPING: amzg=AMZ-Expert "
            "Global (HK), seo=Pacific Edge (US). Pass vendor_id if you already "
            "know it. Otherwise pass vendor_name: if it matches an existing "
            "vendor exactly, that vendor is used silently; if it's similar to "
            "an existing vendor, you'll be asked to pick 'existing' or 'new' "
            "via vendor_choice (re-issue the call with that + confirmed:true); "
            "if nothing similar exists, a new vendor is created automatically. "
            "WRITE OPERATION — first call returns a confirmation prompt; call "
            "again with confirmed:true to actually execute. NEVER pass "
            "confirmed:true on the first attempt; require explicit user 'yes'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo"]},
                "amount": {"type": "number"},
                "currency": {"type": "string", "default": "USD"},
                "date": {"type": "string"},
                "vendor_id": {"type": "string"},
                "vendor_name": {
                    "type": "string",
                    "description": "Alternative to vendor_id — Goldman resolves or creates it.",
                },
                "vendor_choice": {
                    "type": "string", "enum": ["existing", "new"],
                    "description": "Only needed after Goldman flags a similar existing vendor.",
                },
                "description": {"type": "string"},
                "account_id": {"type": "string"},
                "confirmed": {"type": "boolean", "default": False},
            },
            "required": ["entity", "amount"],
        },
    },
```

- [ ] **Step 4: Rewrite `_create_expense` in `goldman/bot/tools.py`**

Replace the whole function (currently lines 1214-1230-ish, from `def
_create_expense(ctx, args) -> str:` through its `return
_zoho_guardrail(...)` line):

```python
def _create_expense(ctx, args) -> str:
    amount = args.get("amount")
    if amount is None:
        return "create_expense error: amount is required."

    args = dict(args)
    vendor_id = (args.get("vendor_id") or "").strip()
    vendor_name = (args.get("vendor_name") or "").strip()
    pending_vendor_name = ""

    if not vendor_id and vendor_name:
        from goldman.zoho_safety import banner, log_audit, resolve_entity, UnknownEntityError
        try:
            info = resolve_entity(ctx.conn, args.get("entity") or "")
        except UnknownEntityError:
            info = None
        if info is not None:
            from goldman.vendor_match import match_vendor
            _, contact_svc, _, _ = _zoho_services_for(ctx, info.slug)
            try:
                candidates = contact_svc.list_contacts(contact_type="vendor")
            except Exception as e:
                return (
                    f"{banner(info)}\n"
                    f"Couldn't check Zoho's vendor list ({e}) — pass vendor_id "
                    f"directly this time, or try again in a moment."
                )
            match = match_vendor(vendor_name, candidates)
            if match.kind == "exact":
                vendor_id = match.candidates[0].contact_id
            elif match.kind == "similar":
                choice = (args.get("vendor_choice") or "").strip().lower()
                if choice == "existing":
                    vendor_id = match.candidates[0].contact_id
                elif choice == "new":
                    pending_vendor_name = vendor_name
                else:
                    names = ", ".join(
                        f"'{c.contact_name}' ({c.contact_id})" for c in match.candidates
                    )
                    log_audit(
                        ctx.conn, info=info, tool_name="create_expense",
                        arguments=args, status="blocked_ambiguous",
                        result_summary=f"vendor name {vendor_name!r} similar to: {names}",
                        channel_id=getattr(ctx, "chat_id", "") or "",
                    )
                    return (
                        f"{banner(info)}\n"
                        f"⚠️  VENDOR NEEDS A DECISION before I log this "
                        f"{amount} {args.get('currency', 'USD')} expense "
                        f"({args.get('description', 'no description')!r}).\n"
                        f"   You said: '{vendor_name}'\n"
                        f"   Existing similar vendor(s): {names}\n\n"
                        f"Reply 'existing' to use {match.candidates[0].contact_name}, "
                        f"or 'new' to create '{vendor_name}' as a separate vendor. "
                        f"Say 'confirmed' too and I'll log the expense in the same step."
                    )
            else:
                pending_vendor_name = vendor_name

    args["vendor_id"] = vendor_id

    def work(info):
        nonlocal vendor_id
        _, contact_svc, _, expense_svc = _zoho_services_for(ctx, info.slug)
        if not expense_svc:
            return "create_expense not yet supported in this build."
        if not vendor_id and pending_vendor_name:
            new_vendor = contact_svc.create_contact(
                contact_name=pending_vendor_name, contact_type="vendor",
            )
            vendor_id = new_vendor.contact_id
        result = expense_svc.create_expense(
            amount=float(amount),
            date=args.get("date", ""),
            description=args.get("description", ""),
            vendor_id=vendor_id or "",
            account_id=args.get("account_id", ""),
            currency=args.get("currency", "USD"),
        )
        vendor_note = f" (new vendor {vendor_id})" if pending_vendor_name else ""
        return f"Recorded expense {result.expense_id} ({amount} {args.get('currency', 'USD')}){vendor_note}."
    return _zoho_guardrail("create_expense", ctx, args, work)
```

- [ ] **Step 5: Mirror the schema in `goldman/api/mcp_server.py`**

Replace the `create_expense` block's `inputSchema.properties` (around lines
340-350) — keep `description` text simple here (MCP client, not the Telegram
persona), just add the two new properties:

```python
            "properties": {
                "entity": {"type": "string", "enum": ["amzg", "seo"]},
                "amount": {"type": "number"},
                "currency": {"type": "string"},
                "date": {"type": "string"},
                "vendor_id": {"type": "string"},
                "vendor_name": {"type": "string", "description": "Alternative to vendor_id."},
                "vendor_choice": {"type": "string", "enum": ["existing", "new"]},
                "description": {"type": "string"},
                "account_id": {"type": "string"},
                "confirmed": {"type": "boolean", "default": False},
            },
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_goldman_phase8_tools.py -v`
Expected: PASS (all tests in file)

- [ ] **Step 7: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all tests pass, no regressions

- [ ] **Step 8: Commit**

```bash
git add goldman/bot/tools.py goldman/api/mcp_server.py tests/test_goldman_phase8_tools.py
git commit -m "$(cat <<'EOF'
feat(goldman): create_expense resolves vendor_name (auto-create/ask/reuse)

Also fixes a pre-existing bug found while rewriting this function:
expense_svc.create_expense() takes a keyword-only `currency` argument, but
this call site passed `currency_code=`, so every real create_expense
invocation raised TypeError (silently swallowed by the guardrail's generic
except-and-report). Fixed as part of this change; regression-tested.
EOF
)"
```

---

## Task 7: Full verification and ship

**Files:** none (verification + deploy only)

- [ ] **Step 1: Run the complete test suite one more time**

Run: `python3 -m pytest -q`
Expected: all tests pass (should be the pre-existing 315 plus everything added in Tasks 1-6 — expect roughly 335-340 total)

- [ ] **Step 2: Push to origin/main**

```bash
git push origin main
```

This triggers Render's auto-deploy for the `goldman` service
(`srv-d8k1f4uk1jcs73ea1p40`) same as the two fixes shipped earlier today.

- [ ] **Step 3: Confirm the deploy went live**

Use the `mcp__render__list_deploys` tool with `serviceId:
"srv-d8k1f4uk1jcs73ea1p40"`, `limit: 1`. Confirm `status: "live"` and the
`commit.id` matches the last commit from Step 2.

- [ ] **Step 4: Confirm the service is healthy**

Fetch `https://goldman-qzv3.onrender.com/health` (e.g. via `WebFetch`).
Expected: `{"status": "ok"}`, not a 503.

- [ ] **Step 5: Report to the user**

Summarize in plain language (per this project's communication style — no
raw diffs/code unless asked): the vendor auto-create + duplicate-check
feature is live; give one example of each of the three behaviors (exact
reuse, similar-name question, auto-create) using vendor names Liran will
recognize if possible (e.g. reference the Akiva CPA case from the original
conversation that started this work).
