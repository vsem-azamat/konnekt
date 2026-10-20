"""Every private use of a bot reaches the audience; group traffic never does."""

import datetime
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.types import CallbackQuery, ChatMemberBanned, ChatMemberMember, Message, Update
from app.core.enums import Touchpoint
from app.db.models import AudienceMember, AudienceReach, AudienceTouch
from app.presentation.telegram.middlewares.audience import AudienceMiddleware
from sqlalchemy import select

from tests.telegram_helpers import TelegramObjectFactory

pytestmark = pytest.mark.unit

tg = TelegramObjectFactory

PERSON = tg.create_user(id=4242, username="anna_n", first_name="Anna", last_name=None, language_code="uk")


def _private_chat():
    return tg.create_chat(id=PERSON.id, type="private", title=None, first_name="Anna")


def _message(text="hello", chat=None):
    return Message(
        message_id=1,
        date=datetime.datetime.now(datetime.UTC),
        chat=chat or _private_chat(),
        from_user=PERSON,
        text=text,
    )


async def _run(middleware, update):
    handler = AsyncMock(return_value="handled")
    result = await middleware(handler, update, {})
    handler.assert_awaited_once()
    assert result == "handled"


async def _rows(session_maker, model):
    async with session_maker() as db:
        return list(await db.scalars(select(model)))


async def test_a_private_message_records_the_person_and_opens_the_bot(session_maker):
    middleware = AudienceMiddleware(session_maker, Touchpoint.MAIN_BOT)

    await _run(middleware, Update(update_id=1, message=_message()))

    [member] = await _rows(session_maker, AudienceMember)
    assert (member.user_id, member.username, member.language_code) == (PERSON.id, "anna_n", "uk")
    [touch] = await _rows(session_maker, AudienceTouch)
    assert touch.touchpoint == Touchpoint.MAIN_BOT
    [reach] = await _rows(session_maker, AudienceReach)
    assert (reach.bot, reach.blocked_at) == (Touchpoint.MAIN_BOT, None)
    assert reach.started_at is not None


async def test_the_start_payload_is_the_source(session_maker):
    middleware = AudienceMiddleware(session_maker, Touchpoint.MAIN_BOT)

    await _run(middleware, Update(update_id=1, message=_message("/start matfyz")))

    [member] = await _rows(session_maker, AudienceMember)
    assert member.source == "matfyz"


async def test_group_messages_are_not_audience(session_maker):
    middleware = AudienceMiddleware(session_maker, Touchpoint.MAIN_BOT)
    message = _message("hi all", chat=tg.create_chat())

    await _run(middleware, Update(update_id=1, message=message))

    assert await _rows(session_maker, AudienceMember) == []


async def test_a_retired_bot_is_a_touchpoint_but_never_a_way_to_reach_anyone(session_maker):
    middleware = AudienceMiddleware(session_maker, Touchpoint.MOVED_BOT, reach=False)

    await _run(middleware, Update(update_id=1, message=_message()))

    [touch] = await _rows(session_maker, AudienceTouch)
    assert touch.touchpoint == Touchpoint.MOVED_BOT
    assert await _rows(session_maker, AudienceReach) == []


def _my_chat_member(new_member):
    old = ChatMemberMember(user=PERSON, status=ChatMemberStatus.MEMBER)
    return tg.create_chat_member_updated(
        chat=_private_chat(), user=PERSON, old_chat_member=old, new_chat_member=new_member
    )


async def test_blocking_the_bot_is_recorded_and_unblocking_reopens_it(session_maker):
    middleware = AudienceMiddleware(session_maker, Touchpoint.CONTACT_BOT)
    banned = ChatMemberBanned(user=PERSON, status=ChatMemberStatus.KICKED, until_date=datetime.datetime(1970, 1, 1))

    await _run(middleware, Update(update_id=1, my_chat_member=_my_chat_member(banned)))
    [reach] = await _rows(session_maker, AudienceReach)
    assert (reach.bot, reach.started_at) == (Touchpoint.CONTACT_BOT, None)
    assert reach.blocked_at is not None

    member = ChatMemberMember(user=PERSON, status=ChatMemberStatus.MEMBER)
    await _run(middleware, Update(update_id=2, my_chat_member=_my_chat_member(member)))
    [reach] = await _rows(session_maker, AudienceReach)
    assert reach.blocked_at is None
    assert reach.started_at is not None


async def test_a_database_failure_never_stops_the_update(session_maker):
    broken = AsyncMock(side_effect=RuntimeError("database is down"))
    middleware = AudienceMiddleware(broken, Touchpoint.MAIN_BOT)

    await _run(middleware, Update(update_id=1, message=_message()))


async def test_a_bot_added_to_a_group_is_not_a_person_blocking_it(session_maker):
    middleware = AudienceMiddleware(session_maker, Touchpoint.MAIN_BOT)
    banned = ChatMemberBanned(user=PERSON, status=ChatMemberStatus.KICKED, until_date=datetime.datetime(1970, 1, 1))
    old = ChatMemberMember(user=PERSON, status=ChatMemberStatus.MEMBER)
    in_group = tg.create_chat_member_updated(
        chat=tg.create_chat(), user=PERSON, old_chat_member=old, new_chat_member=banned
    )

    await _run(middleware, Update(update_id=1, my_chat_member=in_group))

    assert await _rows(session_maker, AudienceReach) == []


async def test_a_button_pressed_in_private_is_a_visit(session_maker):
    middleware = AudienceMiddleware(session_maker, Touchpoint.MAIN_BOT)
    press = CallbackQuery(id="1", from_user=PERSON, chat_instance="c", message=_message(), data="x")

    await _run(middleware, Update(update_id=1, callback_query=press))

    [touch] = await _rows(session_maker, AudienceTouch)
    assert (touch.user_id, touch.touchpoint) == (PERSON.id, Touchpoint.MAIN_BOT)


@pytest.mark.parametrize("payload", ["a" * 65, "drop table", "привет"])
async def test_a_payload_that_none_of_our_links_carry_is_not_kept(session_maker, payload):
    middleware = AudienceMiddleware(session_maker, Touchpoint.MAIN_BOT)

    await _run(middleware, Update(update_id=1, message=_message(f"/start {payload}")))

    [member] = await _rows(session_maker, AudienceMember)
    assert member.source is None


async def test_a_slow_database_costs_the_record_not_the_answer(session_maker, monkeypatch):
    import asyncio

    from app.presentation.telegram.middlewares import audience

    monkeypatch.setattr(audience, "RECORD_TIMEOUT", 0.05)

    async def stuck(*_args, **_kwargs):
        await asyncio.sleep(10)

    monkeypatch.setattr(audience.record, "seen", stuck)
    middleware = AudienceMiddleware(session_maker, Touchpoint.MAIN_BOT)

    await asyncio.wait_for(_run(middleware, Update(update_id=1, message=_message())), 1)
