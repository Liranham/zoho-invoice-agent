---
description: Hybrid search over Goldman's memory (facts, conversations, documents).
argument-hint: <question>
allowed-tools: Bash(curl:*), Bash(jq:*)
---

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
QUESTION="$ARGUMENTS"
if [ -z "$QUESTION" ]; then
  echo "Usage: /goldman:recall <question>"
  exit 1
fi
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"question\":\"$QUESTION\",\"top\":8}" "$URL/v1/recall" | \
  jq -r '
    .results[] |
    "\n[\(.source_type)] score=\(.score)\n  \(.excerpt[:200])"
  '
```
