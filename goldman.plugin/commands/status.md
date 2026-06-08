---
description: Service health + pending bills + pending confirmations + facts awaiting embedding.
allowed-tools: Bash(curl:*), Bash(jq:*)
---

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
curl -s -H "Authorization: Bearer $KEY" "$URL/v1/status" | jq .
```
