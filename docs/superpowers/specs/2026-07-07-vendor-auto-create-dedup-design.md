# Vendor auto-create with duplicate detection — design

Date: 2026-07-07
Status: approved, ready for implementation plan

## Problem

`create_expense` requires a raw Zoho `vendor_id`. Goldman's chat agent has no
way to look one up or create one, so every expense filing that involves a
vendor Goldman hasn't been given an ID for dead-ends in a clarifying
question ("is Akiva CPA already a vendor, or should I create one?"). This
follows directly from the Drive-folder and re-confirmation fixes shipped
earlier the same day (commits `601456f`, `41ce840`) — same root complaint:
Goldman asking questions it should be able to resolve itself.

Naively auto-creating a vendor for every new name risks silently splitting
one real-world vendor into duplicate Zoho contacts (e.g. "Akiva CPA" and
"Akiva Cohen, Accounting" filed as two unrelated vendors when they're the
same person). Liran's instruction: auto-create when a name is clearly new,
but ask when a name is *similar* to an existing vendor rather than guessing
either way.

## Scope

- Vendors only (Zoho contact_type=vendor), used by `create_expense`.
- Expense **accounts** (chart of accounts) are explicitly out of scope —
  separate open question, not addressed here.
- Applies to both entities (amzg, seo) — matching is always scoped to one
  entity's vendor list; never compared across entities.

## Architecture

Extend the existing two-phase Zoho write guardrail (`goldman/zoho_safety.py`
+ `_zoho_guardrail` in `goldman/bot/tools.py`) rather than adding a separate
"create vendor" tool the model must call as its own turn. Vendor resolution
happens as a sub-step of the *same* confirmation the user already has to
approve for the expense itself — one round trip covers both, matching the
"stop making Liran repeat himself" fix shipped earlier today.

### New/changed components

1. **`zoho/contacts.py`** (existing file, small extension)
   - `Contact` dataclass gains a `contact_type` field.
   - `list_contacts` accepts an optional `contact_type` filter, passed
     through as a Zoho API query param.
   - `create_contact` already accepts `contact_type` — no change.
   - `_list_customers` tool updated to pass `contact_type="customer"`
     explicitly (latent bug fix: today it returns vendors mixed in too).

2. **`goldman/vendor_match.py`** (new module — pure functions, no I/O)
   - `normalize_name(name: str) -> str` — lowercase, strip punctuation,
     collapse whitespace.
   - `significant_words(name: str) -> set[str]` — normalized words with
     common filler stripped (`the`, `llc`, `inc`, `ltd`, `co`, `corp`,
     `cpa`, `group`, `services`, `company`, `holdings`, `&`).
   - `match_vendor(name: str, candidates: list[Contact]) -> VendorMatch` —
     returns one of:
     - `exact` (normalized names equal) — carries the matched `Contact`.
     - `similar` — carries up to 3 candidate `Contact`s, ranked by: shared
       significant word (highest priority) then close-spelling ratio
       (`difflib.SequenceMatcher` ratio ≥ 0.72 on normalized full strings —
       reuses the stdlib, no new dependency).
     - `none` — no candidate fires either check.
   - Fully unit-testable with plain strings/dataclasses — no Zoho, no DB.

3. **`goldman/bot/tools.py`**
   - New read tool `list_vendors` — mirrors `_list_customers`, filtered to
     `contact_type="vendor"`.
   - `create_expense` schema gains:
     - `vendor_name` (string, optional) — alternative to `vendor_id`.
     - `vendor_choice` (enum `"existing" | "new"`, optional) — only used to
       resolve a previously-flagged `similar` match.
   - `_create_expense` resolution order, before the normal confirm/write
     split:
     1. If `vendor_id` given, use it as-is (unchanged behavior).
     2. Else if `vendor_name` given, call `match_vendor` against that
        entity's live vendor list (via `contact_service_for`):
        - `exact` → resolved `vendor_id`, proceed silently.
        - `similar` and no `vendor_choice` → **do not** proceed to the
          normal write-confirmation text. Instead return a combined
          prompt: the vendor question *and* the rest of the expense
          preview (amount/date/description) in one message, so the next
          user reply can resolve both at once (works with the "resuming a
          plan" persona instruction shipped in commit `41ce840` — a loose
          "existing" or "new" reply is enough).
        - `similar` and `vendor_choice="existing"` → use the top-ranked
          candidate's `vendor_id`.
        - `similar` and `vendor_choice="new"` → mark for creation (falls
          into the same path as `none`).
        - `none` → mark for creation; the normal write-confirmation shows
          `vendor: "<name>" (new — will be created)`, matching the
          existing confirmation-table style.
     3. On the actual write (`confirmed:true`), if the vendor still needs
        creating, call `contact_svc.create_contact(contact_name=name,
        contact_type="vendor")` first, then create the expense with the
        resulting id. Both are one Zoho audit-logged write.

### Error handling

- Zoho vendor-list fetch fails → don't guess; tell the user to supply
  `vendor_id` directly this one time (same "non-fatal, degrade gracefully"
  pattern as Drive-mirror failures in `goldman/documents.py`).
- Ambiguous reply Goldman can't parse as existing/new → re-ask only that
  part, don't silently default either way.
- Every vendor creation is Zoho-audit-logged (`goldman.zoho_audit`) same as
  any other write, so there's always a record of what got created and why.

## Testing

- `tests/test_goldman_vendor_match.py` (new) — pure unit tests on
  `vendor_match.py` covering: exact match modulo case/punctuation, shared
  significant word (the Akiva CPA family), close-spelling typo match,
  clearly-unrelated names (no match), and filler-word stripping not
  producing false positives (e.g. "CPA Services LLC" alone isn't enough
  overlap to flag two otherwise-unrelated firms).
- `tests/test_goldman_phase8_tools.py` (extend) — `list_vendors` tool
  dispatch test (mocked contact service, `contact_type="vendor"` filter
  asserted); `create_expense` with `vendor_name` covering all three
  resolution paths (exact/similar/none), mirroring the existing
  `create_expense`/`list_customers` mocking style.
- Full suite run before shipping, as with the two fixes earlier today.

## Out of scope / explicitly deferred

- Expense account (chart-of-accounts) lookup/auto-resolution — separate
  decision, not addressed here.
- Cross-entity vendor matching — never; vendor lists are always scoped to
  one Zoho organization.
- A standalone `create_vendor` write tool independent of `create_expense`
  — YAGNI for now; the only place vendors get created today is expense
  filing.
