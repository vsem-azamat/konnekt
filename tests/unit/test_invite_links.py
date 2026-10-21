"""The invite link the bot keeps for a listed chat without a username.

The catalogue serves `chats.public_link`; for a private chat that is a link the
bot made itself and keeps working. Telegram never says when a link is revoked,
so every rule here is about what the bot does when its own call says so.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import (
    ClientDecodeError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import ChatInviteLink, User
from app.chats import invite_links
from app.chats.invite_links import LINK_NAME, ensure_link, sync_once
from app.core.time import utc_now
from app.db.models import Chat
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

OURS = "https://t.me/+ours"
NEW = "https://t.me/+fresh"
BOT = User(id=1, is_bot=True, first_name="bot")


@pytest.fixture(autouse=True)
def _no_memory_of_problems():
    invite_links.forget_problems()
    yield
    invite_links.forget_problems()


def _link(url: str = OURS, **fields) -> ChatInviteLink:
    return ChatInviteLink(
        invite_link=url,
        creator=BOT,
        creates_join_request=fields.pop("creates_join_request", False),
        is_primary=False,
        is_revoked=fields.pop("is_revoked", False),
        name=LINK_NAME,
        **fields,
    )


def _refused(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=MagicMock(), message=message)


def _bot(*, username: str | None = None, join_by_request: bool = False, edit=None, create=None) -> AsyncMock:
    bot = AsyncMock()
    bot.id = BOT.id
    bot.get_chat = AsyncMock(return_value=MagicMock(username=username, join_by_request=join_by_request))
    bot.edit_chat_invite_link = AsyncMock(side_effect=edit, return_value=_link())
    bot.create_chat_invite_link = AsyncMock(side_effect=create, return_value=_link(NEW))
    bot.revoke_chat_invite_link = AsyncMock()
    return bot


def _chat(link: str | None = OURS, **fields) -> Chat:
    return Chat(id=-100, title="Private room", resource_status=Chat.STATUS_APPROVED, public_link=link, **fields)


async def test_a_working_link_is_kept_and_not_recreated() -> None:
    bot, chat = _bot(), _chat()

    assert await ensure_link(bot, chat) == "kept"

    assert chat.public_link == OURS
    bot.create_chat_invite_link.assert_not_called()


async def test_a_link_the_bot_made_by_hand_is_adopted_in_place() -> None:
    """Editing succeeds only for a link the bot itself made, which is the proof of ownership."""
    bot, chat = _bot(), _chat()

    await ensure_link(bot, chat)

    edited = bot.edit_chat_invite_link.call_args.kwargs
    assert edited["invite_link"] == OURS
    assert edited["name"] == LINK_NAME
    bot.create_chat_invite_link.assert_not_called()
    bot.revoke_chat_invite_link.assert_not_called()


@pytest.mark.parametrize(
    ("captcha", "by_request", "wanted"),
    [(False, False, False), (True, False, True), (False, True, True), (True, True, True)],
)
async def test_the_link_asks_for_join_requests_when_the_chat_does(
    captcha: bool, by_request: bool, wanted: bool
) -> None:
    bot, chat = _bot(join_by_request=by_request), _chat(is_captcha_enabled=captcha)

    await ensure_link(bot, chat)

    assert bot.edit_chat_invite_link.call_args.kwargs["creates_join_request"] is wanted


async def test_a_new_link_follows_the_chats_join_request_setting_too() -> None:
    bot = _bot(edit=_refused("INVITE_REVOKED_MISSING"))
    chat = _chat(is_captcha_enabled=True)

    await ensure_link(bot, chat)

    assert bot.create_chat_invite_link.call_args.kwargs["creates_join_request"] is True


@pytest.mark.parametrize("message", ["INVITE_REVOKED_MISSING", "INVITE_HASH_EXPIRED", "INVITE_HASH_INVALID"])
async def test_a_dead_link_is_replaced_and_the_new_one_is_served(message: str) -> None:
    bot, chat = _bot(edit=_refused(message)), _chat()

    assert await ensure_link(bot, chat) == "replaced"

    assert chat.public_link == NEW
    assert bot.create_chat_invite_link.call_args.kwargs["name"] == LINK_NAME


@pytest.mark.parametrize(
    "returned",
    [
        _link(is_revoked=True),
        _link(member_limit=5),
        _link(expire_date=utc_now() - datetime.timedelta(hours=1)),
    ],
    ids=["revoked", "member limit", "expired"],
)
async def test_a_link_that_edits_but_does_not_work_is_replaced(returned: ChatInviteLink) -> None:
    bot, chat = _bot(), _chat()
    bot.edit_chat_invite_link.return_value = returned

    assert await ensure_link(bot, chat) == "replaced"

    assert chat.public_link == NEW


async def test_a_link_somebody_else_made_is_replaced_by_one_of_ours() -> None:
    bot, chat = _bot(edit=_refused("CHAT_ADMIN_REQUIRED")), _chat("https://t.me/+pasted")

    assert await ensure_link(bot, chat) == "replaced"

    assert chat.public_link == NEW


async def test_a_listed_chat_with_no_link_of_its_own_gets_one() -> None:
    bot, chat = _bot(), _chat("https://t.me/placeholder_name")
    bot.get_chat.return_value = MagicMock(username=None, join_by_request=False)

    assert await ensure_link(bot, chat) == "created"

    assert chat.public_link == NEW
    bot.edit_chat_invite_link.assert_not_called()


async def test_a_chat_with_a_username_is_served_by_it() -> None:
    bot, chat = _bot(username="Room_Chat"), _chat()

    assert await ensure_link(bot, chat) == "username"

    assert chat.public_link == "https://t.me/Room_Chat"
    bot.create_chat_invite_link.assert_not_called()
    # Ours is retired rather than left joinable behind the catalogue's back.
    bot.revoke_chat_invite_link.assert_awaited_once_with(chat_id=chat.id, invite_link=OURS)


async def test_a_username_link_that_is_already_right_is_left_alone() -> None:
    bot, chat = _bot(username="room_chat"), _chat("https://t.me/room_chat")

    assert await ensure_link(bot, chat) == "kept"

    bot.revoke_chat_invite_link.assert_not_called()
    bot.edit_chat_invite_link.assert_not_called()


async def test_a_failed_revoke_does_not_undo_the_username_switch() -> None:
    bot, chat = _bot(username="room_chat"), _chat()
    bot.revoke_chat_invite_link.side_effect = _refused("INVITE_REVOKED_MISSING")

    assert await ensure_link(bot, chat) == "username"

    assert chat.public_link == "https://t.me/room_chat"


@pytest.mark.parametrize(
    "error", [TelegramNetworkError(MagicMock(), "down"), TelegramRetryAfter(MagicMock(), "slow", 1)]
)
async def test_a_transient_failure_changes_nothing(error: Exception) -> None:
    bot, chat = _bot(edit=error), _chat()

    assert await ensure_link(bot, chat) == "transient"

    assert chat.public_link == OURS
    bot.create_chat_invite_link.assert_not_called()


async def test_a_transient_failure_on_getting_the_chat_changes_nothing() -> None:
    bot, chat = _bot(), _chat()
    bot.get_chat.side_effect = TelegramNetworkError(MagicMock(), "down")

    assert await ensure_link(bot, chat) == "transient"

    assert chat.public_link == OURS
    bot.edit_chat_invite_link.assert_not_called()


async def test_without_the_invite_right_the_old_link_keeps_being_served_and_the_problem_is_named() -> None:
    bot = _bot(
        edit=_refused("not enough rights to manage chat invite link"),
        create=_refused("not enough rights to manage chat invite link"),
    )
    chat = _chat()

    assert await ensure_link(bot, chat) == "no_invite_right"

    assert chat.public_link == OURS


async def test_a_chat_the_bot_left_is_a_problem_not_a_new_link() -> None:
    bot, chat = _bot(), _chat()
    bot.get_chat.side_effect = TelegramForbiddenError(method=MagicMock(), message="bot was kicked")

    assert await ensure_link(bot, chat) == "not_in_chat"

    assert chat.public_link == OURS
    bot.create_chat_invite_link.assert_not_called()


async def test_an_unrecoverable_chat_alerts_once_and_not_on_every_tick(caplog: pytest.LogCaptureFixture) -> None:
    bot = _bot(edit=_refused("CHAT_ADMIN_REQUIRED"), create=_refused("CHAT_ADMIN_REQUIRED"))
    chat = _chat()

    with caplog.at_level(logging.INFO):
        for _ in range(3):
            await ensure_link(bot, chat)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1


async def test_a_recovered_chat_alerts_again_if_it_breaks_again(caplog: pytest.LogCaptureFixture) -> None:
    broken = _bot(edit=_refused("CHAT_ADMIN_REQUIRED"), create=_refused("CHAT_ADMIN_REQUIRED"))
    chat = _chat()

    with caplog.at_level(logging.INFO):
        await ensure_link(broken, chat)
        assert await ensure_link(_bot(), chat) == "kept"
        await ensure_link(broken, chat)

    assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 2


async def test_sync_handles_listed_private_chats_and_nothing_else(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        session.add_all(
            [
                Chat(id=-1, title="approved", resource_status=Chat.STATUS_APPROVED, public_link=OURS),
                Chat(id=-2, title="observed", resource_status=Chat.STATUS_OBSERVED, public_link="https://t.me/+two"),
                # Somebody else's room, and the bot may not even be in it.
                Chat(
                    id=-3, title="external", resource_status=Chat.STATUS_EXTERNAL, public_link="https://t.me/ext_chat"
                ),
                # Not listed: the bot never publishes a chat on its own.
                Chat(id=-4, title="unlisted", resource_status=Chat.STATUS_APPROVED, public_link=None),
                Chat(id=-5, title="taken down", resource_status=Chat.STATUS_DISABLED, public_link="https://t.me/+old"),
            ]
        )
        await session.commit()
    bot = _bot()

    await sync_once(session_maker=session_maker, bot=bot, pause_seconds=0)

    asked = sorted(call.args[0] if call.args else call.kwargs["chat_id"] for call in bot.get_chat.call_args_list)
    assert asked == [-1]
    async with session_maker() as session:
        unlisted = await session.get(Chat, -4)
    assert unlisted is not None
    assert unlisted.public_link is None


async def test_sync_stores_a_replaced_link(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        session.add(Chat(id=-1, title="room", resource_status=Chat.STATUS_APPROVED, public_link=OURS))
        await session.commit()
    bot = _bot(edit=_refused("INVITE_REVOKED_MISSING"))

    await sync_once(session_maker=session_maker, bot=bot, pause_seconds=0)

    async with session_maker() as session:
        stored = (await session.execute(select(Chat.public_link))).scalar_one()
    assert stored == NEW


async def test_one_chat_failing_does_not_stop_the_rest(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        session.add_all(
            [
                Chat(id=-1, title="a", resource_status=Chat.STATUS_APPROVED, public_link=OURS),
                Chat(id=-2, title="b", resource_status=Chat.STATUS_APPROVED, public_link="https://t.me/+two"),
            ]
        )
        await session.commit()
    bot = _bot(edit=[RuntimeError("boom"), _link("https://t.me/+two")])

    await sync_once(session_maker=session_maker, bot=bot, pause_seconds=0)

    assert bot.edit_chat_invite_link.await_count == 2


async def test_a_chat_unlisted_during_the_sweep_stays_unlisted_and_the_new_link_is_revoked(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        session.add(Chat(id=-1, title="room", resource_status=Chat.STATUS_APPROVED, public_link=OURS))
        await session.commit()

    async def operator_takes_it_down(**_kwargs):
        async with session_maker() as other:
            chat = await other.get(Chat, -1)
            assert chat is not None
            chat.public_link = None
            await other.commit()
        raise _refused("INVITE_REVOKED_MISSING")

    bot = _bot(edit=operator_takes_it_down)

    counts = await sync_once(session_maker=session_maker, bot=bot, pause_seconds=0)

    async with session_maker() as session:
        stored = (await session.execute(select(Chat.public_link))).scalar_one()
    assert stored is None
    assert counts == {"raced": 1}
    bot.revoke_chat_invite_link.assert_awaited_once_with(chat_id=-1, invite_link=NEW)


async def test_a_chat_switched_off_during_the_sweep_is_not_given_the_link(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        session.add(Chat(id=-1, title="room", resource_status=Chat.STATUS_APPROVED, public_link=OURS))
        await session.commit()

    async def operator_switches_it_to_watching(**_kwargs):
        async with session_maker() as other:
            chat = await other.get(Chat, -1)
            assert chat is not None
            chat.resource_status = Chat.STATUS_DISABLED
            await other.commit()
        raise _refused("INVITE_REVOKED_MISSING")

    bot = _bot(edit=operator_switches_it_to_watching)

    await sync_once(session_maker=session_maker, bot=bot, pause_seconds=0)

    async with session_maker() as session:
        stored = (await session.execute(select(Chat.public_link))).scalar_one()
    assert stored == OURS


async def test_a_mass_of_dead_links_stops_the_sweep(session_maker: async_sessionmaker[AsyncSession], caplog) -> None:
    async with session_maker() as session:
        session.add_all(
            Chat(id=-i, title=f"room {i}", resource_status=Chat.STATUS_APPROVED, public_link=f"https://t.me/+old{i}")
            for i in range(1, 12)
        )
        await session.commit()
    bot = _bot(edit=_refused("INVITE_REVOKED_MISSING"))

    with caplog.at_level(logging.INFO):
        counts = await sync_once(session_maker=session_maker, bot=bot, pause_seconds=0)

    assert counts == {"replaced": invite_links.MAX_REPLACEMENTS_PER_SWEEP + 1}
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


async def test_the_old_link_is_revoked_only_after_its_replacement_exists() -> None:
    order: list[str] = []
    bot, chat = _bot(), _chat()
    bot.edit_chat_invite_link.return_value = _link(member_limit=3)
    bot.create_chat_invite_link.side_effect = lambda **_: order.append("create") or _link(NEW)
    bot.revoke_chat_invite_link.side_effect = lambda **_: order.append("revoke")

    await ensure_link(bot, chat)

    assert order == ["create", "revoke"]


async def test_a_failed_replacement_leaves_the_old_link_unrevoked() -> None:
    bot, chat = _bot(create=_refused("CHAT_ADMIN_REQUIRED")), _chat()
    bot.edit_chat_invite_link.return_value = _link(member_limit=3)

    await ensure_link(bot, chat)

    bot.revoke_chat_invite_link.assert_not_called()
    assert chat.public_link == OURS


async def test_an_answer_telegram_sent_that_cannot_be_read_is_transient() -> None:
    bot, chat = _bot(edit=ClientDecodeError("bad", Exception("x"), "{}")), _chat()

    assert await ensure_link(bot, chat) == "transient"
    bot.create_chat_invite_link.assert_not_called()


async def test_each_broken_chat_gets_an_alert_of_its_own(caplog: pytest.LogCaptureFixture) -> None:
    bot = _bot(edit=_refused("CHAT_ADMIN_REQUIRED"), create=_refused("CHAT_ADMIN_REQUIRED"))
    first, second = _chat(), Chat(id=-200, title="b", resource_status=Chat.STATUS_APPROVED, public_link=OURS)

    with caplog.at_level(logging.INFO):
        await ensure_link(bot, first)
        await ensure_link(bot, second)

    names = {r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR}
    assert len(names) == 2
    assert all("chat=" in name for name in names)


async def test_observed_chats_are_not_ours_to_link(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        session.add(Chat(id=-1, title="o", resource_status=Chat.STATUS_OBSERVED, public_link=OURS))
        await session.commit()
    bot = _bot()

    await sync_once(session_maker=session_maker, bot=bot, pause_seconds=0)

    bot.get_chat.assert_not_called()
