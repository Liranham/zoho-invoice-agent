-- Register the goldman-documents Storage bucket. Service-role uploads only;
-- RLS not configured because the Goldman service runs with service_role key.

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'goldman-documents',
    'goldman-documents',
    false,
    52428800,                                  -- 50 MB
    ARRAY['application/pdf', 'text/plain', 'text/markdown',
          'application/octet-stream', 'image/png', 'image/jpeg']
) ON CONFLICT (id) DO NOTHING;

-- Reserved for Phase 3 vendor-bill intake.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'goldman-bills',
    'goldman-bills',
    false,
    20971520,                                  -- 20 MB
    ARRAY['application/pdf', 'image/png', 'image/jpeg',
          'text/html', 'application/octet-stream']
) ON CONFLICT (id) DO NOTHING;
