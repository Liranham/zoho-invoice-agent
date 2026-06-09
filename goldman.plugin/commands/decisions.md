---
description: Chronological timeline of decisions matching a topic.
argument-hint: <topic>
allowed-tools: Bash(curl:*), Bash(jq:*)
---

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
TOPIC="$ARGUMENTS"
if [ -z "$TOPIC" ]; then
  echo "Usage: /goldman:decisions <topic>"
  exit 1
fi
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"topic\":\"$TOPIC\"}" "$URL/v1/decisions" | \
  TOPIC="$TOPIC" jq -r '
    if (.decisions | length) == 0 then
      "No prior decisions matching \"" + ($ENV.TOPIC // "") + "\"."
    else
      "Decision timeline for \"" + ($ENV.TOPIC // "") + "\":\n" +
      (.decisions | map(
        "  " + (.created_at[0:10]) + ": " + .fact +
        (if .entity_slug then " (\(.entity_slug))" else "" end)
      ) | join("\n"))
    end
  '
```
