"""The captcha asked in the chat: let in muted, named in a card, asked in a private message.

A chat with `captcha_in_chat` approves the request at once, but only after
muting the applicant, and names them in the chat, where a mention notifies.
The card's button opens the bot, which may then write to them any time.
Passed, they may write and are greeted; out of tries or time, removed.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import RestrictChatMember
from aiogram.types import (
    Chat,
    ChatJoinRequest,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberRestricted,
    ChatMemberUpdated,
    ChatPermissions,
    User,
)
from app.captcha import in_chat, service
from app.chats import welcome
from app.core.config import settings
from app.core.time import utc_now
from app.db.models import Chat as DbChat
from app.db.models import JoinCaptcha, WelcomeGreeting
from app.presentation.telegram.handlers.captcha import captcha_start
from app.presentation.telegram.handlers.events import join_requested, user_joined, user_left, user_unmuted
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit

CHAT_ID = -1001370017010
BOT_ID = 1
BOT_USERNAME = "konnekt_test_bot"
CARD_URL = f"https://t.me/{BOT_USERNAME}?start=captcha"
BATCH = datetime.timedelta(seconds=settings.captcha.card_batch_seconds)
NAMES = {4242: "Marek", 4343: "Tereza", 4444: "Jakub"}


def _user(user_id: int) -> User:
    return User(id=user_id, is_bot=False, first_name=NAMES.get(user_id, "Anna"))


def _request(user_id: int = 4242) -> ChatJoinRequest:
    return ChatJoinRequest(
        chat=Chat(id=CHAT_ID, type="supergroup", title="ČVUT FIT"),
        from_user=_user(user_id),
        user_chat_id=user_id,
        date=datetime.datetime.now(datetime.UTC),
    )


def _muted(user_id: int, *, is_member: bool = True) -> ChatMemberRestricted:
    return ChatMemberRestricted.model_validate(
        {
            "user": _user(user_id),
            "status": ChatMemberStatus.RESTRICTED,
            "is_member": is_member,
            "until_date": datetime.datetime.fromtimestamp(0, datetime.UTC),
            **dict.fromkeys(ChatPermissions.model_fields, False),
        }
    )


def _update(user_id: int, old, new, *, by: int | None = None) -> ChatMemberUpdated:
    return ChatMemberUpdated(
        chat=Chat(id=CHAT_ID, type="supergroup", title="ČVUT FIT"),
        from_user=User(id=by or user_id, is_bot=False, first_name="Someone"),
        date=datetime.datetime.now(datetime.UTC),
        old_chat_member=old,
        new_chat_member=new,
    )


async def _seed(session: AsyncSession, **kwargs) -> DbChat:
    chat = DbChat(
        id=CHAT_ID,
        title="ČVUT FIT",
        resource_status=DbChat.STATUS_APPROVED,
        join_mode=DbChat.JOIN_CAPTCHA,
        captcha_in_chat=True,
        **kwargs,
    )
    session.add(chat)
    await session.commit()
    return chat


@pytest.fixture(autouse=True)
def _no_intro_media(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.telegram, "intro_video", "")
    monkeypatch.setattr(settings.telegram, "intro_video_cover", "")
    welcome.forget()


@pytest.fixture
def calls() -> list[str]:
    return []


@pytest.fixture
def bot(calls: list[str]) -> MagicMock:
    tg_bot = MagicMock()
    tg_bot.id = BOT_ID
    tg_bot.me = AsyncMock(return_value=User(id=BOT_ID, is_bot=True, first_name="Konnekt", username=BOT_USERNAME))
    ids = iter(range(100, 1000))

    def record(name: str, result=None):
        async def call(*_, **kwargs):
            calls.append(name)
            return result() if callable(result) else result

        return AsyncMock(side_effect=call)

    tg_bot.restrict_chat_member = record("restrict")
    tg_bot.approve_chat_join_request = record("approve")
    tg_bot.decline_chat_join_request = record("decline")
    tg_bot.send_message = record("send", lambda: MagicMock(message_id=next(ids)))
    tg_bot.send_video = record("send_video", lambda: MagicMock(message_id=next(ids)))
    tg_bot.edit_message_text = record("edit")
    tg_bot.delete_message = record("delete")
    tg_bot.ban_chat_member = record("ban")
    tg_bot.unban_chat_member = record("unban")

    async def member(*, chat_id: int, user_id: int):
        return MagicMock(user=_user(user_id))

    tg_bot.get_chat_member = AsyncMock(side_effect=member)
    return tg_bot


def _sent(bot, chat_id: int) -> list[dict]:
    return [c.kwargs for c in bot.send_message.await_args_list if c.kwargs["chat_id"] == chat_id]


async def _rows(session: AsyncSession) -> list[JoinCaptcha]:
    session.expire_all()
    return list((await session.scalars(select(JoinCaptcha).order_by(JoinCaptcha.id))).all())


async def _let_in(session: AsyncSession, bot, user_id: int = 4242) -> JoinCaptcha:
    await join_requested(_request(user_id), bot, session)
    return next(r for r in await _rows(session) if r.user_id == user_id)


async def _ask(session: AsyncSession, bot, user_id: int = 4242) -> dict:
    message = MagicMock(from_user=_user(user_id))
    await captcha_start(message, bot, session)
    return _sent(bot, user_id)[-1]


def _right(row: JoinCaptcha) -> int:
    return row.options.index(row.answer)


def _wrong(row: JoinCaptcha) -> int:
    return next(i for i, emoji in enumerate(row.options) if emoji != row.answer)


# --- let in muted ------------------------------------------------------------


async def test_the_applicant_is_muted_before_the_request_is_approved(session: AsyncSession, bot, calls) -> None:
    await _seed(session)

    row = await _let_in(session, bot)

    assert calls[:2] == ["restrict", "approve"]
    permissions = bot.restrict_chat_member.await_args.kwargs["permissions"]
    assert not any(permissions.model_dump(exclude_none=True).values())
    assert row.in_chat
    assert row.status == JoinCaptcha.STATUS_PENDING
    # Nothing in a private message: the request's five minutes are not what this waits on.
    assert _sent(bot, 4242) == []


async def test_a_card_in_the_chat_names_them_with_a_mention_and_a_button(session: AsyncSession, bot) -> None:
    await _seed(session)

    row = await _let_in(session, bot)

    [card] = _sent(bot, CHAT_ID)
    assert card["text"] == (
        '👋 <a href="tg://user?id=4242">Marek</a>, чтобы писать в чат, нажми «Пройти капчу»: '
        "бот задаст один вопрос в личке.\n\n⏱ На это 24 часа, потом бот уберёт из чата."
    )
    [[button]] = card["reply_markup"].inline_keyboard
    assert (button.text, button.url) == ("Пройти капчу", CARD_URL)
    assert row.card_message_id is not None
    assert row.announced_at is not None


async def test_without_the_right_to_mute_the_request_waits_for_the_admins(session: AsyncSession, bot) -> None:
    await _seed(session)
    bot.restrict_chat_member.side_effect = TelegramBadRequest(
        method=MagicMock(spec=RestrictChatMember), message="Bad Request: not enough rights"
    )

    row = await _let_in(session, bot)

    bot.approve_chat_join_request.assert_not_awaited()
    assert row.status == JoinCaptcha.STATUS_UNDELIVERED
    assert _sent(bot, CHAT_ID) == []
    [report] = _sent(bot, settings.admin.default_report_chat_id)
    assert "Проверьте права бота" in report["text"]


async def test_the_dm_captcha_stays_for_chats_without_the_switch(session: AsyncSession, bot) -> None:
    await _seed(session)
    chat = await session.get(DbChat, CHAT_ID)
    assert chat is not None
    chat.captcha_in_chat = False
    await session.commit()

    row = await _let_in(session, bot)

    assert not row.in_chat
    bot.restrict_chat_member.assert_not_awaited()
    bot.approve_chat_join_request.assert_not_awaited()
    assert len(_sent(bot, 4242)) == 1


# --- the card: one per window ------------------------------------------------


async def test_joiners_within_the_window_wait_for_the_next_card(session: AsyncSession, bot) -> None:
    await _seed(session)
    await _let_in(session, bot, 4242)

    await _let_in(session, bot, 4343)
    await _let_in(session, bot, 4444)

    assert len(_sent(bot, CHAT_ID)) == 1
    waiting = [r for r in await _rows(session) if r.announced_at is None]
    assert [r.user_id for r in waiting] == [4343, 4444]


async def test_the_next_card_mentions_the_new_and_carries_the_rest_without_a_ping(session: AsyncSession, bot) -> None:
    await _seed(session)
    first_card = (await _let_in(session, bot, 4242)).card_message_id
    await _let_in(session, bot, 4343)
    await _let_in(session, bot, 4444)

    await in_chat.announce_due(bot, session, utc_now() + BATCH)

    cards = _sent(bot, CHAT_ID)
    assert len(cards) == 2
    assert cards[1]["text"].startswith(
        '👋 Marek, <a href="tg://user?id=4343">Tereza</a>, <a href="tg://user?id=4444">Jakub</a>, '
        "чтобы писать в чат, нажмите «Пройти капчу»: бот задаст каждому один вопрос в личке."
    )
    bot.delete_message.assert_awaited_once_with(chat_id=CHAT_ID, message_id=first_card)
    rows = await _rows(session)
    assert len({r.card_message_id for r in rows}) == 1


async def test_ten_names_still_make_one_card(session: AsyncSession, bot) -> None:
    await _seed(session)
    for user_id in range(5000, 5010):
        await _let_in(session, bot, user_id)
    await in_chat.announce_due(bot, session, utc_now() + BATCH)

    last = _sent(bot, CHAT_ID)[-1]
    assert last["text"].count("tg://user?id=") == 9
    assert last["reply_markup"].inline_keyboard[0][0].url == CARD_URL


async def test_the_sweep_waits_out_the_window(session: AsyncSession, bot) -> None:
    await _seed(session)
    await _let_in(session, bot, 4242)
    await _let_in(session, bot, 4343)

    await in_chat.announce_due(bot, session, utc_now())

    assert len(_sent(bot, CHAT_ID)) == 1


# --- the private message ------------------------------------------------------


async def test_the_cards_button_brings_the_question_to_a_private_message(session: AsyncSession, bot) -> None:
    await _seed(session)
    row = await _let_in(session, bot)

    asked = await _ask(session, bot)

    assert asked["chat_id"] == 4242
    assert asked["text"].startswith("🔐 Проверка для чата <b>ČVUT FIT</b>\n\nНажми на <b>")
    assert "и сможешь писать в чате." in asked["text"]
    [row] = await _rows(session)
    assert row.asked_at is not None
    assert row.message_id is not None


async def test_with_nothing_to_ask_the_button_is_a_plain_start(session: AsyncSession, bot) -> None:
    await _seed(session)

    with pytest.raises(SkipHandler):
        await captcha_start(MagicMock(from_user=_user(4242)), bot, session)


async def test_the_reminder_comes_after_the_five_minutes_a_request_allows(session: AsyncSession, bot) -> None:
    await _seed(session)
    await _let_in(session, bot)
    await _ask(session, bot)
    later = utc_now() + datetime.timedelta(minutes=settings.captcha.in_chat_remind_after_minutes, seconds=1)
    assert later - (await _rows(session))[0].created_at > datetime.timedelta(minutes=5)

    await service.remind(bot, session, now=later)

    assert _sent(bot, 4242)[-1]["text"].startswith("⏳ Ещё ")
    assert (await _rows(session))[0].reminded_at == later


async def test_no_reminder_before_they_open_the_bot(session: AsyncSession, bot) -> None:
    await _seed(session)
    await _let_in(session, bot)

    await service.remind(bot, session, now=utc_now() + datetime.timedelta(hours=1))

    assert _sent(bot, 4242) == []


# --- the answer ---------------------------------------------------------------


async def test_a_pass_unmutes_deletes_the_card_and_greets(session: AsyncSession, bot, calls) -> None:
    await _seed(session, is_welcome_enabled=True, time_delete=900)
    row = await _let_in(session, bot)
    await _ask(session, bot)
    calls.clear()

    outcome = await service.answer(bot, session, challenge_id=row.id, user_id=4242, pick=_right(row))

    assert outcome is service.Outcome.PASSED
    assert calls[0] == "restrict"
    permissions = bot.restrict_chat_member.await_args.kwargs["permissions"]
    assert all(permissions.model_dump(exclude_none=True).values())
    bot.delete_message.assert_awaited_once_with(chat_id=CHAT_ID, message_id=row.card_message_id)
    [greeting] = _sent(bot, CHAT_ID)[1:]
    assert "добро пожаловать" in greeting["text"]
    assert (await session.scalars(select(WelcomeGreeting))).first() is not None
    [row] = await _rows(session)
    assert row.status == JoinCaptcha.STATUS_PASSED
    assert "✅ Готово, теперь можно писать в" in bot.edit_message_text.await_args_list[0].kwargs["text"]


async def test_a_pass_takes_one_name_off_a_shared_card(session: AsyncSession, bot) -> None:
    await _seed(session)
    marek = await _let_in(session, bot, 4242)
    await _let_in(session, bot, 4343)
    await in_chat.announce_due(bot, session, utc_now() + BATCH)
    [marek, _] = await _rows(session)
    await _ask(session, bot, 4242)
    bot.edit_message_text.reset_mock()

    await service.answer(bot, session, challenge_id=marek.id, user_id=4242, pick=_right(marek))

    edits = [c.kwargs for c in bot.edit_message_text.await_args_list if c.kwargs["chat_id"] == CHAT_ID]
    assert edits[-1]["text"].startswith('👋 <a href="tg://user?id=4343">Tereza</a>, чтобы писать в чат, нажми')
    bot.delete_message.assert_awaited_once()  # the first card only


async def test_two_wrong_taps_remove_them_with_their_messages(session: AsyncSession, bot, calls) -> None:
    await _seed(session)
    row = await _let_in(session, bot)
    await _ask(session, bot)

    for _ in range(2):
        outcome = await service.answer(bot, session, challenge_id=row.id, user_id=4242, pick=_wrong(row))

    assert outcome is service.Outcome.FAILED
    assert bot.ban_chat_member.await_args.kwargs["revoke_messages"] is True
    assert bot.unban_chat_member.await_args.kwargs["only_if_banned"] is True
    bot.decline_chat_join_request.assert_not_awaited()
    [row] = await _rows(session)
    assert row.status == JoinCaptcha.STATUS_FAILED


async def test_out_of_time_they_are_removed(session: AsyncSession, bot) -> None:
    await _seed(session)
    row = await _let_in(session, bot)

    await service.expire_stale(bot, session, now=row.expires_at + datetime.timedelta(seconds=1))

    bot.ban_chat_member.assert_awaited_once()
    bot.decline_chat_join_request.assert_not_awaited()
    [row] = await _rows(session)
    assert row.status == JoinCaptcha.STATUS_EXPIRED
    bot.delete_message.assert_awaited_once_with(chat_id=CHAT_ID, message_id=row.card_message_id)


async def test_a_chat_that_stops_checking_lets_its_muted_write(session: AsyncSession, bot) -> None:
    chat = await _seed(session)
    await _let_in(session, bot)
    chat.join_mode = DbChat.JOIN_ADMINS
    await session.commit()

    await service.expire_stale(bot, session)

    assert all(bot.restrict_chat_member.await_args.kwargs["permissions"].model_dump(exclude_none=True).values())
    bot.ban_chat_member.assert_not_awaited()
    [row] = await _rows(session)
    assert row.status == JoinCaptcha.STATUS_GONE


# --- membership updates -------------------------------------------------------


async def test_the_join_the_approval_makes_is_neither_greeted_nor_settled(session: AsyncSession, bot) -> None:
    await _seed(session, is_welcome_enabled=True)
    await _let_in(session, bot)
    sent_before = len(_sent(bot, CHAT_ID))

    left = ChatMemberLeft(user=_user(4242), status=ChatMemberStatus.LEFT)
    await user_joined(_update(4242, left, _muted(4242)), bot, session)

    assert len(_sent(bot, CHAT_ID)) == sent_before
    [row] = await _rows(session)
    assert row.status == JoinCaptcha.STATUS_PENDING


async def test_leaving_closes_their_captcha_and_card(session: AsyncSession, bot) -> None:
    await _seed(session)
    row = await _let_in(session, bot)

    left = ChatMemberLeft(user=_user(4242), status=ChatMemberStatus.LEFT)
    await user_left(_update(4242, _muted(4242), left), bot, session)

    [row] = await _rows(session)
    assert row.status == JoinCaptcha.STATUS_GONE
    bot.delete_message.assert_awaited_once_with(chat_id=CHAT_ID, message_id=row.card_message_id)


async def test_an_admin_unmuting_them_settles_it(session: AsyncSession, bot) -> None:
    await _seed(session)
    await _let_in(session, bot)

    member = ChatMemberMember(user=_user(4242), status=ChatMemberStatus.MEMBER)
    await user_unmuted(_update(4242, _muted(4242), member, by=777), bot, session)

    [row] = await _rows(session)
    assert row.status == JoinCaptcha.STATUS_GONE


async def test_the_bots_own_unmute_is_not_an_admins(session: AsyncSession, bot) -> None:
    await _seed(session)
    await _let_in(session, bot)

    member = ChatMemberMember(user=_user(4242), status=ChatMemberStatus.MEMBER)
    await user_unmuted(_update(4242, _muted(4242), member, by=BOT_ID), bot, session)

    [row] = await _rows(session)
    assert row.status == JoinCaptcha.STATUS_PENDING
