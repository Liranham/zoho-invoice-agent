---
description: Record a structured fact for an entity.
argument-hint: <kind> <text>
allowed-tools: Bash(curl:*), Bash(jq:*)
---

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
KIND=$(echo "$ARGUMENTS" | awk '{print $1}')
TEXT=$(echo "$ARGUMENTS" | cut -d' ' -f2-)
if [ -z "$KIND" ] || [ -z "$TEXT" ]; then
  echo "Usage: /goldman:remember <kind> <text>"
  echo "Kinds: target | preference | constraint | commitment | event | decision | note"
  exit 1
fi
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"entity\":\"amzg\",\"kind\":\"$KIND\",\"text\":\"$TEXT\"}" "$URL/v1/remember" | \
  jq -r '"Stored fact \(.fact_id) (kind=\(.kind))"'
```
