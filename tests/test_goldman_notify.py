"""notify_liran: sends as Goldman AND records the message in his conversation
memory (with the session pinned), so a later reply keeps context."""

from unittest.mock import MagicMock

from goldman.bot.tools import execute_tool


def _patch_repos(monkeypatch):
    sent = {}

    class FakeNotifier:
        def __init__(self, token, chat_id):
            sent["init"] = (token, chat_id)

        def send_message(self, text, parse_mode="HTML"):
            sent["text"] = text
            return True

    fake_sess = MagicMock(session_id="tg-7884172049-20260707")
    fake_bot_sessions = MagicMock()
    fake_bot_sessions.get_or_create.return_value = fake_sess
    fake_turns = MagicMock()
    fake_ent_repo = MagicMock()
    fake_ent_repo.get_by_slug.return_value = MagicMock(id="ent-seo")

    monkeypatch.setattr("tg_notify.notifier.TelegramNotifier", FakeNotifier)
    monkeypatch.setattr("goldman_db.bot_sessions.BotSessionRepository", lambda conn: fake_bot_sessions)
    monkeypatch.setattr("goldman_db.conversation_turns.ConversationTurnRepository", lambda conn: fake_turns)
    monkeypatch.setattr("goldman_db.entities.EntityRepository", lambda conn: fake_ent_repo)
    return sent, fake_bot_sessions, fake_turns


def test_notify_liran_sends_and_records_assistant_turn(monkeypatch):
    monkeypatch.setenv("GOLDMAN_TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("GOLDMAN_TELEGRAM_CHAT_ID", "7884172049")
    sent, bot_sessions, turns = _patch_repos(monkeypatch)

    out = execute_tool(
        ctx=MagicMock(), name="notify_liran",
        arguments={"text": "INV-22 in Pacific Edge is ready", "entity": "seo"},
    )

    assert "recorded" in out.lower()
    assert sent["text"] == "INV-22 in Pacific Edge is ready"
    assert sent["init"] == ("tok", "7884172049")
    # recorded as an ASSISTANT turn under the telegram session
    kwargs = turns.insert.call_args.kwargs
    assert kwargs["role"] == "assistant"
    assert kwargs["session_id"] == "tg-7884172049-20260707"
    assert kwargs["front_door"] == "telegram"
    # session pinned to seo so a follow-up resolves to Pacific Edge
    bot_sessions.set_current_entity.assert_called_once_with("telegram", "7884172049", "seo")


def test_notify_liran_requires_text(monkeypatch):
    monkeypatch.setenv("GOLDMAN_TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("GOLDMAN_TELEGRAM_CHAT_ID", "7884172049")
    out = execute_tool(ctx=MagicMock(), name="notify_liran", arguments={"text": "   "})
    assert "text is required" in out.lower()


def test_notify_liran_errors_without_credentials(monkeypatch):
    monkeypatch.delenv("GOLDMAN_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("GOLDMAN_TELEGRAM_CHAT_ID", raising=False)
    out = execute_tool(ctx=MagicMock(), name="notify_liran", arguments={"text": "hi"})
    assert "not configured" in out.lower()
