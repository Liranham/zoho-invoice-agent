-- Seed Goldman's two known entities.
-- Idempotent via ON CONFLICT DO NOTHING on slug.

INSERT INTO goldman.entities (
    slug, legal_name, jurisdiction, base_currency,
    zoho_credential_key
) VALUES (
    'amzg',
    'AMZ Expert Global Limited',
    'HK',
    'HKD',
    'AMZG'
) ON CONFLICT (slug) DO NOTHING;

INSERT INTO goldman.entities (
    slug, legal_name, jurisdiction, base_currency,
    zoho_credential_key, parent_entity_id
) VALUES (
    'seo',
    'Specific Edge Outsourcing LLC',
    'US',
    'USD',
    'SEO',
    (SELECT id FROM goldman.entities WHERE slug = 'amzg')
) ON CONFLICT (slug) DO NOTHING;
