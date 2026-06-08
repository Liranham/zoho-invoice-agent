-- Seed initial capabilities (Phase 0/1/2).
-- Idempotent via UNIQUE (name).

INSERT INTO goldman.capabilities (name, description, kind, payload) VALUES
    ('create_invoice', 'Create a client invoice in the right Zoho org for the given entity.',
     'tool', '{"phase": 0, "module": "goldman.zoho", "entry": "invoice_service_for"}'),
    ('list_invoices', 'List recent invoices for an entity, optionally filtered by status.',
     'tool', '{"phase": 0, "cli": "list --entity SLUG"}'),
    ('list_customers', 'List Zoho customers (contacts) for an entity.',
     'tool', '{"phase": 0, "cli": "customers --entity SLUG"}'),
    ('onboard_entity', 'Conversational onboarding: brain-dump -> Claude extraction -> 5-table writes -> coverage check -> gap-fill.',
     'skill', '{"phase": 1, "cli": "onboard --entity SLUG", "needs": ["ANTHROPIC_API_KEY"]}'),
    ('sync_zoho_contacts', 'Pull Zoho contacts for an entity into goldman.clients + goldman.vendors.',
     'tool', '{"phase": 1, "cli": "sync zoho-contacts --entity SLUG"}'),
    ('who', 'Print the company brain: each entity with registrations, banks, top clients/vendors.',
     'tool', '{"phase": 1, "cli": "who"}'),
    ('remember_fact', 'Record a free-floating fact for an entity (kind in target/preference/constraint/commitment/event/decision/note).',
     'tool', '{"phase": 2, "cli": "remember --entity SLUG --kind KIND TEXT"}'),
    ('recall', 'Hybrid retrieval (vector + keyword) across facts + conversation turns + document chunks.',
     'tool', '{"phase": 2, "cli": "recall QUESTION [--entity SLUG]", "needs": ["OPENAI_API_KEY"]}'),
    ('document_upload', 'Upload a document (txt/md/pdf), summarise via Claude, chunk + embed.',
     'tool', '{"phase": 2, "cli": "document upload --entity SLUG FILE", "needs": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOLDMAN_SUPABASE_SERVICE_KEY"]}'),
    ('document_list', 'List documents for an entity.',
     'tool', '{"phase": 2, "cli": "document list [--entity SLUG]"}'),
    ('embed_pending', 'Embed all rows missing embeddings (facts + conversation_turns + document_chunks).',
     'tool', '{"phase": 2, "cli": "db embed-pending", "needs": ["OPENAI_API_KEY"]}'),
    ('jurisdiction_hk', 'Knowledge of Hong Kong profits tax + general HK company-law obligations.',
     'jurisdiction', '{"phase": 2, "primary_taxes": ["profits_tax"]}'),
    ('jurisdiction_us', 'Knowledge of US federal income tax + state sales tax nexus basics.',
     'jurisdiction', '{"phase": 2, "primary_taxes": ["income_tax", "sales_tax"]}')
ON CONFLICT (name) DO NOTHING;
