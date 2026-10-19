"""Banning across every approved chat, counted in Telegram calls.

The ban itself fans out — one call per chat, which is the whole point. Wiping
the person's messages does not: each message lives in exactly one chat and is
deleted once. Nesting the second inside the first multiplies a hundred deletions
by forty-five chats and spends the rate limit on four and a half thousand calls
that were always going to fail, at the exact moment an administrator is waiting
for a spammer to disappear.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db.models import Chat
from app.moderation import blacklist


class _Row:
    def __init__(self, id_: int, *, approved: bool = True) -> None:
        self.id = id_
        self.is_approved = approved


class _Message:
    def __init__(self, chat_id: int, message_id: int) -> None:
        self.chat_id = chat_id
        self.message_id = message_id


@pytest.fixture
def wired(monkeypatch):
    """Three chats, two recorded messages, and repositories that answer."""
    chats = [_Row(-100_1), _Row(-100_2), _Row(-100_3)]
    messages = [_Message(-100_1, 11), _Message(-100_2, 22)]

    user_repo = AsyncMock()
    chat_repo = AsyncMock()
    chat_repo.get_chats.return_value = chats
    message_repo = AsyncMock()
    message_repo.get_user_messages.return_value = messages

    monkeypatch.setattr(blacklist, "UserRepository", MagicMock(return_value=user_repo))
    monkeypatch.setattr(blacklist, "ChatRepository", MagicMock(return_value=chat_repo))
    monkeypatch.setattr(blacklist, "MessageRepository", MagicMock(return_value=message_repo))

    bot = AsyncMock()
    return bot, message_repo


class TestRevokingMessages:
    async def test_each_message_is_deleted_once(self, wired):
        bot, _ = wired

        await blacklist.add_to_blacklist(AsyncMock(), bot, 777, revoke_messages=True)

        assert bot.ban_chat_member.await_count == 3
        assert bot.delete_message.await_count == 2

    async def test_each_message_is_deleted_where_it_lives(self, wired):
        """Not in whichever chat the surrounding loop happened to be on."""
        bot, _ = wired

        await blacklist.add_to_blacklist(AsyncMock(), bot, 777, revoke_messages=True)

        targeted = {(call.kwargs["chat_id"], call.kwargs["message_id"]) for call in bot.delete_message.await_args_list}
        assert targeted == {(-100_1, 11), (-100_2, 22)}

    async def test_the_record_is_read_once(self, wired):
        """Reading it per chat is the same query answered forty-five times."""
        _, message_repo = wired

        await blacklist.add_to_blacklist(AsyncMock(), AsyncMock(), 777, revoke_messages=True)

        assert message_repo.get_user_messages.await_count == 1

    async def test_a_plain_ban_deletes_nothing(self, wired):
        bot, message_repo = wired

        await blacklist.add_to_blacklist(AsyncMock(), bot, 777, revoke_messages=False)

        assert bot.ban_chat_member.await_count == 3
        assert bot.delete_message.await_count == 0
        message_repo.get_user_messages.assert_not_awaited()

    async def test_one_refused_delete_does_not_stop_the_rest(self, wired):
        """Telegram refuses old messages routinely; that is not a reason to stop."""
        bot, _ = wired
        bot.delete_message.side_effect = [Exception("message can't be deleted"), None]

        await blacklist.add_to_blacklist(AsyncMock(), bot, 777, revoke_messages=True)

        assert bot.delete_message.await_count == 2


class TestOnlyApprovedChats:
    """The bot syncs every group it sits in, including groups other people own.

    A ban or an unban there is a public act in a chat nobody approved: it would
    overrule the owner's own moderation, so the fan-out stops at approval.
    """

    @pytest.fixture
    def mixed(self, monkeypatch):
        chats = [
            Chat(id=-100_1, resource_status=Chat.STATUS_APPROVED),
            Chat(id=-100_2, resource_status=Chat.STATUS_DISCOVERED),
            Chat(id=-100_3, resource_status=Chat.STATUS_APPROVED),
            Chat(id=-100_4, resource_status=Chat.STATUS_DISABLED),
        ]
        messages = [
            _Message(-100_1, 11),
            _Message(-100_2, 22),
            _Message(-100_4, 44),
            _Message(-100_9, 99),  # a group with no row
            _Message(777, 33),
        ]

        chat_repo = AsyncMock()
        chat_repo.get_chats.return_value = chats
        message_repo = AsyncMock()
        message_repo.get_user_messages.return_value = messages

        monkeypatch.setattr(blacklist, "UserRepository", MagicMock(return_value=AsyncMock()))
        monkeypatch.setattr(blacklist, "ChatRepository", MagicMock(return_value=chat_repo))
        monkeypatch.setattr(blacklist, "MessageRepository", MagicMock(return_value=message_repo))
        return AsyncMock()

    async def test_a_ban_skips_unapproved_chats(self, mixed):
        bot = mixed

        await blacklist.add_to_blacklist(AsyncMock(), bot, 777)

        assert {call.args[0] for call in bot.ban_chat_member.await_args_list} == {-100_1, -100_3}

    async def test_messages_in_unapproved_chats_stay(self, mixed):
        """The private chat with the bot is not a synced group and still loses its messages."""
        bot = mixed

        await blacklist.add_to_blacklist(AsyncMock(), bot, 777, revoke_messages=True)

        targeted = {call.kwargs["chat_id"] for call in bot.delete_message.await_args_list}
        assert targeted == {-100_1, 777}

    async def test_an_unban_skips_unapproved_chats(self, mixed):
        bot = mixed

        await blacklist.remove_from_blacklist(AsyncMock(), bot, 777)

        assert {call.args[0] for call in bot.unban_chat_member.await_args_list} == {-100_1, -100_3}

    async def test_an_unban_never_removes_a_member(self, mixed):
        """Telegram's unban kicks a current member unless told only_if_banned."""
        bot = mixed

        await blacklist.remove_from_blacklist(AsyncMock(), bot, 777)

        assert all(call.kwargs == {"only_if_banned": True} for call in bot.unban_chat_member.await_args_list)


class TestSuperAdmins:
    async def test_a_super_admin_is_never_blacklisted(self, wired, monkeypatch):
        """Whichever door asks: a command, the console, the control plane.

        A blacklisted account loses every message, its private ones to the bot
        included, so a super admin on the list would lose the bot itself.
        """
        from app.core.config import settings
        from app.core.exceptions import ProtectedUserError

        bot, message_repo = wired
        monkeypatch.setattr(settings.admin, "super_admins", [777])

        with pytest.raises(ProtectedUserError):
            await blacklist.add_to_blacklist(AsyncMock(), bot, 777, revoke_messages=True)

        bot.ban_chat_member.assert_not_awaited()
        bot.delete_message.assert_not_awaited()
        message_repo.get_user_messages.assert_not_awaited()


@pytest.mark.parametrize("stand_in", [136817688, 1087968824, 777000])
async def test_a_stand_in_sender_is_never_blacklisted(stand_in: int) -> None:
    """Blacklisting one silences every channel post, or every anonymous admin, everywhere."""
    from app.core.exceptions import NotAPersonError

    bot = AsyncMock()
    with pytest.raises(NotAPersonError):
        await blacklist.add_to_blacklist(AsyncMock(), bot, stand_in)

    bot.ban_chat_member.assert_not_awaited()


class TestPacing:
    async def test_flood_control_is_waited_out_not_swallowed(self, wired, monkeypatch):
        """A retry_after was logged as "maybe already banned", and the chat stayed open."""
        from aiogram.exceptions import TelegramRetryAfter

        bot, _ = wired
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(blacklist.asyncio, "sleep", fake_sleep)
        bot.ban_chat_member.side_effect = [
            TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=3),
            None,
            None,
            None,
        ]

        failed = await blacklist.add_to_blacklist(AsyncMock(), bot, 777)

        assert failed == []
        assert bot.ban_chat_member.await_count == 4
        assert 3 in slept

    async def test_chats_that_still_refuse_are_named(self, wired):
        bot, _ = wired

        async def refuse_one(chat_id, *_args, **_kwargs):
            if chat_id == -100_2:
                raise RuntimeError("Bad Request: not enough rights")

        bot.ban_chat_member.side_effect = refuse_one

        assert await blacklist.add_to_blacklist(AsyncMock(), bot, 777) == [-100_2]

    async def test_not_every_chat_at_once(self, wired, monkeypatch):
        """46 calls back to back tripped flood control and lost a third of them."""
        import asyncio

        bot, _ = wired
        running = peak = 0

        async def slow_ban(*_args, **_kwargs):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

        bot.ban_chat_member.side_effect = slow_ban
        monkeypatch.setattr(blacklist, "_FAN_OUT_CONCURRENCY", 2)

        await blacklist.add_to_blacklist(AsyncMock(), bot, 777)

        assert peak <= 2

    async def test_unbans_are_paced_and_named_too(self, wired):
        bot, _ = wired

        async def refuse_one(chat_id, *_args, **_kwargs):
            if chat_id == -100_3:
                raise RuntimeError("Bad Request: chat not found")

        bot.unban_chat_member.side_effect = refuse_one

        assert await blacklist.remove_from_blacklist(AsyncMock(), bot, 777) == [-100_3]
