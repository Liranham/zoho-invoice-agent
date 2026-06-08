# Goldman — Claude Code plugin

Slash commands that call the Goldman HTTP API on Render.

## Install

In any Claude Code session:

```
/plugin install /absolute/path/to/goldman.plugin
```

Then set these env vars in your shell rc:

```bash
export GOLDMAN_API_URL="https://goldman.onrender.com"   # or your service URL
export GOLDMAN_API_KEY="<the bearer token>"
```

## Commands

- `/goldman:who` — print the company tree (entities, registrations, banks, top clients/vendors)
- `/goldman:status` — service health + pending counts
- `/goldman:recall <question>` — hybrid search across memory (facts, conversations, documents)
- `/goldman:remember <kind> <text>` — record a fact (`kind` ∈ target/preference/constraint/commitment/event/decision/note)
- `/goldman:invoice [entity-slug]` — list recent invoices (default amzg)
- `/goldman:explain <topic>` — Goldman writes a short explanation grounded in his memory
