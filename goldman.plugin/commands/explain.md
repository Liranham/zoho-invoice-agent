---
description: Goldman explains a topic in plain English, grounded in his memory.
argument-hint: <topic>
allowed-tools: Bash(curl:*), Bash(jq:*)
---

Step 1 — pull relevant memory:

```bash
URL="${GOLDMAN_API_URL:-https://goldman.onrender.com}"
KEY="${GOLDMAN_API_KEY:-}"
TOPIC="$ARGUMENTS"
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"question\":\"$TOPIC\",\"top\":10}" "$URL/v1/recall" | \
  jq -r '.results | map("- [\(.source_type)] \(.excerpt[:250])") | join("\n")'
```

Step 2 — synthesise:

Read the memory chunks above. Write 2–3 short paragraphs in plain English that explain the topic from `$ARGUMENTS` using ONLY what's in those chunks.

CITATION RULES:
- If a chunk's source is `knowledge_pack`, cite it as "per the [pack_topic] reference pack v[pack_version]" — these are the canonical rules.
- If a chunk's source is `uploaded`, `email`, or `manual`, cite it as "per [filename]" — these are the user's specific documents.
- When both kinds are relevant, show both together. The pack is the rule; the uploaded documents are the specifics for this company.

If the memory doesn't cover the topic, say so clearly — do NOT invent.
