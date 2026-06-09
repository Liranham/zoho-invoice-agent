"""Front-door-agnostic 'ask Goldman' entry point.

Wraps the same Claude+tools+memory loop the Telegram bot uses, but exposes
it as a pure function callable from the HTTP API, the CLI, or any future
caller. Inserts the user/assistant turns into goldman.conversation_turns so
memory is preserved across calls keyed on (front_door, channel_id).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from goldman.bot.agent import run_agent
from goldman.bot.tools import ToolContext
from goldman.llm import GoldmanLLM
from goldman_db.bot_sessions import BotSessionRepository
from goldman_db.connection import app_conn
from goldman_db.conversation_turns import ConversationTurnRepository
from goldman_db.entities import EntityRepository


# Imported lazily to avoid a circular import with handlers (which imports ask
# is not the case today, but keep the rule for future-proofing).
def _persona() -> str:
    from goldman.bot.handlers import GOLDMAN_PERSONA
    return GOLDMAN_PERSONA


def ask_goldman(
    *,
    question: str,
    channel_id: str,
    front_door: str = "claude_code",
    entity_slug: Optional[str] = None,
    max_history: int = 10,
) -> dict:
    """Run a single question through Goldman's full conversation engine.

    - `channel_id` is the stable identity for this caller (telegram chat_id,
      claude-code workstation id, etc.). Memory is keyed on this.
    - `front_door` labels where the call originated, for analytics.
    - `entity_slug`, when provided, overrides the session's current entity.
    Returns {"answer", "entity", "session_id"}.
    """
    if not question or not question.strip():
        raise ValueError("question must be a non-empty string")

    llm = GoldmanLLM()

    with app_conn() as conn:
        bot_sessions = BotSessionRepository(conn)
        session_id = f"{front_door}-{channel_id}-{datetime.utcnow():%Y%m%d}"
        sess = bot_sessions.get_or_create(
            front_door=front_door,
            chat_id=channel_id,
            default_entity=entity_slug or "amzg",
            session_id=session_id,
        )
        effective_entity = entity_slug or sess.current_entity or "amzg"

        turns = ConversationTurnRepository(conn)
        ent = EntityRepository(conn).get_by_slug(effective_entity)
        entity_id = ent.id if ent else None

        turns.insert(
            entity_id=entity_id, session_id=sess.session_id,
            front_door=front_door, role="user", text=question,
        )

        recent = turns.list_by_session(sess.session_id)[-max_history:]
        messages = []
        for t in recent:
            if t.role == "user":
                messages.append({"role": "user", "content": t.text})
            elif t.role == "assistant":
                messages.append({"role": "assistant", "content": t.text})

        ctx = ToolContext(
            conn=conn, entity_slug=effective_entity,
            chat_id=channel_id, embedder=None,
            bot_session_repo=bot_sessions,
        )

        reply = run_agent(
            claude=llm._client, model=llm.model,
            system=_persona(), messages=messages, ctx=ctx,
        )

        turns.insert(
            entity_id=entity_id, session_id=sess.session_id,
            front_door=front_door, role="assistant", text=reply,
        )
        bot_sessions.touch(front_door, channel_id)

    return {
        "answer": reply,
        "entity": effective_entity,
        "session_id": sess.session_id,
    }
