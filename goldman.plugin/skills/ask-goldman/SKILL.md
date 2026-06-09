---
name: ask-goldman
description: "Use whenever the user wants to consult Goldman, the CFO agent for AMZ Expert Global Limited (HK) and Specific Edge Outsourcing LLC (US). Triggers on phrases like 'Ask Goldman', 'Tell Goldman', 'Check with Goldman', 'Goldman, …', or any question about company structure, finances, taxes, vendors, clients, decisions, or bookkeeping for the two entities."
---

# Ask Goldman

Goldman is Liran's CFO agent. He owns the company brain for **AMZ Expert Global Limited (HK)** and **Specific Edge Outsourcing LLC (US)** — entities, taxes, vendors, clients, bank accounts, decisions, and bills. He runs locally on the user's Mac as an HTTP service.

When this skill activates, your job is to **forward the user's question to Goldman and relay his answer back in plain language**. Do not answer from your own knowledge — Goldman has the live data, the memory of past decisions, and the right persona for finance/tax topics.

## How to call Goldman

Use Bash to POST the user's question to Goldman's `/v1/ask` endpoint. The URL and Bearer token live in the user's shell env (`GOLDMAN_API_URL` and `GOLDMAN_API_KEY`).

```bash
URL="${GOLDMAN_API_URL:-http://localhost:10000}"
KEY="${GOLDMAN_API_KEY:-}"
QUESTION="<the user's question, exactly as they asked it>"

curl -s -X POST \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  --max-time 60 \
  -d "$(jq -n --arg q "$QUESTION" --arg c "claude_code-$(hostname -s)" \
        '{question:$q, channel_id:$c, front_door:"claude_code"}')" \
  "$URL/v1/ask"
```

The response is JSON shaped like `{"answer": "...", "entity": "amzg", "session_id": "..."}`. Show the `answer` field to the user — that's Goldman's reply.

## What to forward

- **Direct questions**: "Ask Goldman what we decided about US tax" → forward `"what we decided about US tax"`.
- **Statements / fact-saving**: "Tell Goldman that we're switching banks to Wise" → forward `"we're switching banks to Wise"` (Goldman has a `remember_fact` tool he'll call himself).
- **Multi-sentence context**: forward the whole thing — Goldman holds conversation context per `channel_id`, so follow-ups stay coherent.

## What to do with Goldman's reply

- Present it as-is (plain text). Don't re-summarise or rewrite — Goldman's voice is his persona.
- If Goldman's answer includes a structured list (entities, decisions, etc.), keep it formatted.
- If the call fails (non-200, timeout, connection refused) tell the user Goldman isn't reachable and suggest checking that `main.py` is running on `localhost:10000`. Don't fall back to your own answer for finance questions — say you can't reach him.

## Channel ID

Pass `channel_id` as `claude-code-<short hostname>` so Goldman keeps Claude Code conversations on their own memory thread, separate from the Telegram bot. This means a Goldman conversation started in Claude Code can continue across turns inside Claude Code.

## What this skill is NOT for

- General coding or HQ Hub questions — those have nothing to do with Goldman.
- Personal/email/calendar tasks — that's Bob, not Goldman.
- Amazon-seller PPC questions — Atlas handles those inside HQ Hub.

Use this skill only when the user is asking Goldman, or asking about company finances, entities, taxes, vendors, clients, decisions, or bills for AMZ Expert Global / Specific Edge Outsourcing.
