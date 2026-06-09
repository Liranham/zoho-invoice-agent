---
description: Print Goldman's company tree (entities, registrations, banks, top clients/vendors, intercompany flow, TP documentation).
allowed-tools: Bash(curl:*), Bash(jq:*)
---

Call Goldman's `/v1/who` endpoint and render the result.

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
if [ -z "$KEY" ]; then
  echo "GOLDMAN_API_KEY not set"
  exit 1
fi
curl -s -H "Authorization: Bearer $KEY" "$URL/v1/who" | \
  jq -r '
    .entities[] |
    "\n\(.legal_name) (\(.slug))" +
    "\n  Jurisdiction:      \(.jurisdiction)" +
    "\n  Tax registrations: \(.tax_registrations | length)" +
    "\n  Bank accounts:     \(.bank_accounts | length)" +
    "\n  Top clients:       \(.top_clients | length)" +
    "\n  Top vendors:       \(.top_vendors | length)" +
    "\n  Intercompany flow (30d): \(
        if (.intercompany_flow.count // 0) > 0 then
          "-> \(.intercompany_flow.counterpart): \(.intercompany_flow.total) \(.intercompany_flow.currency) across \(.intercompany_flow.count) bill(s)"
        else "(none)" end
      )" +
    "\n  TP documentation:   \(
        if .last_tp_doc then
          "\(.last_tp_doc.filename) (\(.last_tp_doc.uploaded_at[0:10]))"
        else "(none on file)" end
      )"
  '
```
