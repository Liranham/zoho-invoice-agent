---
description: List recent client invoices for an entity (default amzg).
argument-hint: [entity-slug]
allowed-tools: Bash(curl:*), Bash(jq:*)
---

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
ENTITY="${ARGUMENTS:-amzg}"
curl -s -H "Authorization: Bearer $KEY" "$URL/invoices?entity=$ENTITY" | \
  jq -r '
    .invoices[] |
    "\(.invoice_number) | \(.status) | \(.date) | \(.total) | \(.customer)"
  '
```
