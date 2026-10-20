"""@konnekt_ads_bot: a contact desk with one forum topic per person (#265).

Livegram forwarded everyone into one plain group, so conversations with
different people were interleaved and staff answered by replying to forwards.
"""

from __future__ import annotations

import asyncio
import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import Chat, ForumTopic, Message, PhotoSize, Update, User
from app.ads.desk import AdsDesk
from app.core.config import AdsBotSettings
from app.db.models import AdsTopic
from app.presentation.telegram import ads
from sqlalchemy import select

if TYPE_CHECKING:
    from aiogram.methods import TelegramMethod

pytestmark = pytest.mark.unit

GROUP = -1009990001
ADS = "400:ads"
PERSON = User(id=555, is_bot=False, first_name="Анна", last_name="Новак", username="anna_n", language_code="uk")
STAFF = User(id=777, is_bot=False, first_name="Staff")


def _private(message_id: int, **fields: Any) -> Message:
    return Message.model_validate(
        {
            "message_id": message_id,
            "date": datetime.datetime.now(datetime.UTC),
            "chat": Chat(id=PERSON.id, type="private"),
            "from_user": PERSON,
            "text": "Хочу рекламу",
        }
        | fields
    )


def _in_topic(message_id: int, thread: int | None, **fields: Any) -> Message:
    return Message.model_validate(
        {
            "message_id": message_id,
            "date": datetime.datetime.now(datetime.UTC),
            "chat": Chat(id=GROUP, type="supergroup", is_forum=True),
            "from_user": STAFF,
            "message_thread_id": thread,
            "is_topic_message": thread is not None or None,
            "text": "Здравствуйте",
        }
        | fields
    )


def _bot() -> AsyncMock:
    bot = AsyncMock()
    threads = iter(range(10, 100))
    bot.create_forum_topic.side_effect = lambda **kw: ForumTopic(
        message_thread_id=next(threads), name=kw["name"], icon_color=0
    )
    return bot


async def _topics(session_maker) -> list[tuple[int, int, int]]:
    async with session_maker() as session:
        rows = (await session.execute(select(AdsTopic))).scalars().all()
        return [(row.group_id, row.user_id, row.thread_id) for row in rows]


# --- A person writes --------------------------------------------------------


async def test_a_first_message_opens_a_topic_named_after_the_person_with_a_card_first(session_maker) -> None:
    bot = _bot()
    desk = AdsDesk(bot, session_maker, GROUP)

    await desk.from_person([_private(1)])

    assert bot.create_forum_topic.await_args.kwargs == {"chat_id": GROUP, "name": "Анна Новак @anna_n"}
    card = bot.send_message.await_args.kwargs
    assert card["chat_id"] == GROUP
    assert card["message_thread_id"] == 10
    assert card["text"].startswith("Новое обращение")
    for detail in ("Анна Новак", "@anna_n", "555", "uk"):
        assert detail in card["text"]
    bot.copy_message.assert_awaited_once_with(chat_id=GROUP, from_chat_id=PERSON.id, message_id=1, message_thread_id=10)
    # The card comes before what the person wrote.
    order = [call[0] for call in bot.mock_calls if call[0] in {"send_message", "copy_message"}]
    assert order == ["send_message", "copy_message"]
    assert await _topics(session_maker) == [(GROUP, PERSON.id, 10)]


async def test_the_next_message_goes_to_the_same_topic_even_after_a_restart(session_maker) -> None:
    await AdsDesk(_bot(), session_maker, GROUP).from_person([_private(1)])
    bot = _bot()

    await AdsDesk(bot, session_maker, GROUP).from_person([_private(2)])

    bot.create_forum_topic.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    bot.copy_message.assert_awaited_once_with(chat_id=GROUP, from_chat_id=PERSON.id, message_id=2, message_thread_id=10)


async def test_a_topic_staff_deleted_is_opened_again(session_maker) -> None:
    bot = _bot()
    desk = AdsDesk(bot, session_maker, GROUP)
    await desk.from_person([_private(1)])
    bot.copy_message.side_effect = [
        TelegramBadRequest(method=MagicMock(), message="Bad Request: message thread not found"),
        None,
    ]

    await desk.from_person([_private(2)])

    assert bot.create_forum_topic.await_count == 2
    assert bot.copy_message.await_args.kwargs["message_thread_id"] == 11
    assert await _topics(session_maker) == [(GROUP, PERSON.id, 11)]


async def test_an_album_is_copied_whole(session_maker) -> None:
    bot = _bot()
    album = [_private(i, text=None, media_group_id="g", caption=None) for i in (5, 6, 7)]

    await AdsDesk(bot, session_maker, GROUP).from_person(album)

    bot.copy_messages.assert_awaited_once_with(
        chat_id=GROUP, from_chat_id=PERSON.id, message_ids=[5, 6, 7], message_thread_id=10
    )
    bot.copy_message.assert_not_awaited()


async def test_a_topic_name_fits_telegrams_limit(session_maker) -> None:
    bot = _bot()
    long = PERSON.model_copy(update={"first_name": "A" * 200})

    await AdsDesk(bot, session_maker, GROUP).from_person([_private(1, from_user=long)])

    assert len(bot.create_forum_topic.await_args.kwargs["name"]) <= 128


@pytest.mark.parametrize(
    "gone",
    ["Bad Request: message thread not found", "Bad Request: TOPIC_DELETED", "Bad Request: TOPIC_ID_INVALID"],
)
async def test_every_way_telegram_says_the_topic_is_gone_opens_a_new_one(session_maker, gone) -> None:
    bot = _bot()
    desk = AdsDesk(bot, session_maker, GROUP)
    await desk.from_person([_private(1)])
    bot.copy_message.side_effect = [TelegramBadRequest(method=MagicMock(), message=gone), None]

    await desk.from_person([_private(2)])

    assert bot.create_forum_topic.await_count == 2


async def test_two_first_messages_at_once_open_one_topic(session_maker) -> None:
    bot = _bot()
    opened = bot.create_forum_topic.side_effect

    async def slow_topic(**kw: Any) -> ForumTopic:
        await asyncio.sleep(0.01)
        return opened(**kw)

    bot.create_forum_topic.side_effect = slow_topic
    desk = AdsDesk(bot, session_maker, GROUP)

    await asyncio.gather(desk.from_person([_private(1)]), desk.from_person([_private(2)]))

    assert bot.create_forum_topic.await_count == 1
    assert {call.kwargs["message_thread_id"] for call in bot.copy_message.await_args_list} == {10}


async def test_a_card_that_failed_does_not_lose_the_topic(session_maker) -> None:
    """Without the row, the next message would open a second topic for the same person."""
    bot = _bot()
    bot.send_message.side_effect = TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=5)
    desk = AdsDesk(bot, session_maker, GROUP)

    await desk.from_person([_private(1)])
    await desk.from_person([_private(2)])

    assert bot.create_forum_topic.await_count == 1
    assert [call.kwargs["message_id"] for call in bot.copy_message.await_args_list] == [1, 2]
    assert await _topics(session_maker) == [(GROUP, PERSON.id, 10)]


async def test_a_message_that_could_not_be_copied_is_reported_in_the_topic(session_maker) -> None:
    bot = _bot()
    desk = AdsDesk(bot, session_maker, GROUP)
    await desk.from_person([_private(1)])
    bot.copy_message.side_effect = TelegramBadRequest(
        method=MagicMock(), message="Bad Request: message can't be copied"
    )

    await desk.from_person([_private(2)])

    # Not taken for a deleted topic.
    assert bot.create_forum_topic.await_count == 1
    notice = bot.send_message.await_args.kwargs
    assert notice["message_thread_id"] == 10
    assert notice["text"] == "Сообщение не скопировано: Bad Request: message can't be copied"


def _flood(retry_after: int = 0) -> TelegramRetryAfter:
    return TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=retry_after)


async def test_a_copy_telegram_asks_to_wait_for_is_tried_once_more(session_maker) -> None:
    bot = _bot()
    desk = AdsDesk(bot, session_maker, GROUP)
    await desk.from_person([_private(1)])
    bot.send_message.reset_mock()
    bot.copy_message.side_effect = [_flood(), None]

    await desk.from_person([_private(2)])

    assert bot.copy_message.await_count == 3
    bot.send_message.assert_not_awaited()


async def test_a_copy_still_refused_after_waiting_is_reported(session_maker) -> None:
    bot = _bot()
    desk = AdsDesk(bot, session_maker, GROUP)
    await desk.from_person([_private(1)])
    bot.copy_message.side_effect = [_flood(), _flood()]

    await desk.from_person([_private(2)])

    assert "не скопировано" in bot.send_message.await_args.kwargs["text"]


# --- Staff answer -----------------------------------------------------------


async def _desk_with_topic(session_maker) -> tuple[AdsDesk, AsyncMock]:
    desk = AdsDesk(_bot(), session_maker, GROUP)
    await desk.from_person([_private(1)])
    bot = _bot()
    return AdsDesk(bot, session_maker, GROUP), bot


async def test_a_staff_message_in_a_topic_reaches_its_person(session_maker) -> None:
    desk, bot = await _desk_with_topic(session_maker)

    await desk.from_staff([_in_topic(50, 10)])

    bot.copy_message.assert_awaited_once_with(
        chat_id=PERSON.id, from_chat_id=GROUP, message_id=50, message_thread_id=None
    )


async def test_a_staff_album_reaches_its_person_whole(session_maker) -> None:
    desk, bot = await _desk_with_topic(session_maker)

    await desk.from_staff([_in_topic(i, 10, text=None, media_group_id="s") for i in (51, 52)])

    bot.copy_messages.assert_awaited_once_with(
        chat_id=PERSON.id, from_chat_id=GROUP, message_ids=[51, 52], message_thread_id=None
    )


@pytest.mark.parametrize("fields", [{"text": "// он уже писал нам"}, {"text": None, "caption": "//скрин"}])
async def test_a_note_starting_with_two_slashes_stays_with_staff(session_maker, fields) -> None:
    desk, bot = await _desk_with_topic(session_maker)

    await desk.from_staff([_in_topic(50, 10, **fields)])

    bot.copy_message.assert_not_awaited()
    bot.send_message.assert_not_awaited()


async def test_a_message_in_a_topic_of_nobody_is_left_alone(session_maker) -> None:
    desk, bot = await _desk_with_topic(session_maker)

    await desk.from_staff([_in_topic(50, 99)])

    assert bot.mock_calls == []


@pytest.mark.parametrize(
    "error",
    [
        TelegramForbiddenError(method=MagicMock(), message="Forbidden: bot was blocked by the user"),
        TelegramBadRequest(method=MagicMock(), message="Bad Request: chat not found"),
    ],
)
async def test_staff_hear_in_the_topic_when_a_message_was_not_delivered(session_maker, error) -> None:
    desk, bot = await _desk_with_topic(session_maker)
    bot.copy_message.side_effect = error

    await desk.from_staff([_in_topic(50, 10)])

    notice = bot.send_message.await_args.kwargs
    assert notice["chat_id"] == GROUP
    assert notice["message_thread_id"] == 10
    assert notice["reply_to_message_id"] == 50
    assert "не доставлено" in notice["text"].lower()


async def test_a_note_in_an_albums_later_caption_still_stays_with_staff(session_maker) -> None:
    desk, bot = await _desk_with_topic(session_maker)
    album = [
        _in_topic(51, 10, text=None, media_group_id="s"),
        _in_topic(52, 10, text=None, caption="// для своих", media_group_id="s"),
    ]

    await desk.from_staff(album)

    bot.copy_messages.assert_not_awaited()


@pytest.mark.parametrize(
    "errors",
    [
        [_flood(), _flood()],
        [TelegramNetworkError(method=MagicMock(), message="timeout")],
    ],
)
async def test_staff_hear_of_any_failure_to_deliver(session_maker, errors) -> None:
    desk, bot = await _desk_with_topic(session_maker)
    bot.copy_message.side_effect = errors

    await desk.from_staff([_in_topic(50, 10)])

    assert "не доставлено" in bot.send_message.await_args.kwargs["text"].lower()


async def test_a_staff_answer_telegram_asks_to_wait_for_is_tried_once_more(session_maker) -> None:
    desk, bot = await _desk_with_topic(session_maker)
    bot.copy_message.side_effect = [_flood(), None]

    await desk.from_staff([_in_topic(50, 10)])

    assert bot.copy_message.await_count == 2
    bot.send_message.assert_not_awaited()


@pytest.mark.parametrize("deleted_first", [False, True])
async def test_a_person_hears_when_no_topic_could_be_opened(session_maker, deleted_first) -> None:
    """Otherwise the message is lost and nobody knows, the person least of all."""
    bot = _bot()
    desk = AdsDesk(bot, session_maker, GROUP)
    if deleted_first:
        await desk.from_person([_private(1)])
        bot.copy_message.side_effect = TelegramBadRequest(method=MagicMock(), message="Bad Request: TOPIC_DELETED")
    bot.create_forum_topic.side_effect = TelegramBadRequest(
        method=MagicMock(), message="Bad Request: not enough rights"
    )

    await desk.from_person([_private(2)])

    answer = bot.send_message.await_args.kwargs
    assert answer["chat_id"] == PERSON.id
    assert answer["text"] == "Не получилось передать сообщение, попробуйте чуть позже"


async def test_a_person_who_cannot_be_told_either_is_only_logged(session_maker, monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr("app.ads.desk.logger", logger)
    bot = _bot()
    bot.create_forum_topic.side_effect = TelegramBadRequest(
        method=MagicMock(), message="Bad Request: not enough rights"
    )
    bot.send_message.side_effect = TelegramForbiddenError(method=MagicMock(), message="Forbidden: bot was blocked")

    await AdsDesk(bot, session_maker, GROUP).from_person([_private(1)])

    logger.warning.assert_called_once_with("ads_person_not_told", user_id=PERSON.id, error="Forbidden: bot was blocked")


async def test_a_long_wait_telegram_asks_for_is_reported_at_once(session_maker, monkeypatch) -> None:
    """Waiting holds the person's turn; past half a minute it is better to tell staff."""
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    desk, bot = await _desk_with_topic(session_maker)
    monkeypatch.setattr("app.ads.desk.asyncio.sleep", sleep)
    bot.copy_message.side_effect = [_flood(31), None]

    await desk.from_staff([_in_topic(50, 10)])

    assert slept == []
    assert bot.copy_message.await_count == 1
    assert "не доставлено" in bot.send_message.await_args.kwargs["text"].lower()


async def test_a_wait_of_up_to_half_a_minute_is_waited_out(session_maker, monkeypatch) -> None:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    desk, bot = await _desk_with_topic(session_maker)
    monkeypatch.setattr("app.ads.desk.asyncio.sleep", sleep)
    bot.copy_message.side_effect = [_flood(30), None]

    await desk.from_staff([_in_topic(50, 10)])

    assert slept == [30]
    bot.send_message.assert_not_awaited()


async def test_one_conversation_stuck_does_not_hold_up_another(session_maker) -> None:
    bot = _bot()
    stuck = asyncio.Event()
    other = PERSON.model_copy(update={"id": 556, "username": "other"})

    async def copy(**kw: Any) -> None:
        if kw["from_chat_id"] == PERSON.id:
            await stuck.wait()

    bot.copy_message.side_effect = copy
    desk = AdsDesk(bot, session_maker, GROUP)
    hanging = asyncio.create_task(desk.from_person([_private(1)]))
    await asyncio.sleep(0.01)

    other_message = _private(2, from_user=other, chat=Chat(id=other.id, type="private"))
    await asyncio.wait_for(desk.from_person([other_message]), timeout=1)

    assert any(call.kwargs["from_chat_id"] == other.id for call in bot.copy_message.await_args_list)
    stuck.set()
    await hanging


async def test_a_notice_that_cannot_be_sent_is_logged_not_raised(session_maker, monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr("app.ads.desk.logger", logger)
    desk, bot = await _desk_with_topic(session_maker)
    bot.copy_message.side_effect = TelegramForbiddenError(method=MagicMock(), message="Forbidden: bot was blocked")
    bot.send_message.side_effect = TelegramBadRequest(method=MagicMock(), message="Bad Request: TOPIC_CLOSED")

    await desk.from_staff([_in_topic(50, 10)])

    logger.warning.assert_called_once_with("ads_notice_failed", thread_id=10, error="Bad Request: TOPIC_CLOSED")


# --- Routing ----------------------------------------------------------------


class _RecordingBot(Bot):
    """A real bot whose API calls are recorded instead of sent."""

    def __init__(self) -> None:
        super().__init__(token=ADS)
        self.sent: list[TelegramMethod[Any]] = []

    async def __call__(self, method: TelegramMethod[Any], request_timeout: int | None = None) -> Any:
        self.sent.append(method)


@pytest.fixture
def routed() -> tuple[_RecordingBot, Any, AsyncMock]:
    desk = AsyncMock()
    dp = ads.build_dispatcher(desk, GROUP, album_wait=0)
    return _RecordingBot(), dp, desk


async def _feed(routed, message: Message) -> None:
    bot, dp, _ = routed
    await dp.feed_update(bot, Update(update_id=1, message=message))


async def test_start_is_greeted_and_not_relayed(routed) -> None:
    await _feed(routed, _private(1, text="/start", entities=[{"type": "bot_command", "offset": 0, "length": 6}]))

    bot, _, desk = routed
    (greeting,) = bot.sent
    assert "Konnekt" in greeting.text
    # The desk answers any question, advertising among them.
    assert "по любому вопросу" in greeting.text
    assert "реклама" in greeting.text
    desk.from_person.assert_not_awaited()


async def test_a_private_message_is_relayed(routed) -> None:
    await _feed(routed, _private(1))

    routed[2].from_person.assert_awaited_once()


@pytest.mark.parametrize(
    "author",
    # An administrator writing anonymously is shown as this bot.
    [STAFF, User(id=1087968824, is_bot=True, first_name="Group", username="GroupAnonymousBot")],
)
async def test_a_topic_message_goes_to_staff_handling(routed, author) -> None:
    await _feed(routed, _in_topic(50, 10, from_user=author))

    routed[2].from_staff.assert_awaited_once()


@pytest.mark.parametrize(
    "message",
    [
        # The General topic belongs to staff alone.
        _in_topic(50, None),
        # Telegram announces a new topic with a service message inside it.
        _in_topic(50, 10, text=None, forum_topic_created={"name": "x", "icon_color": 0}),
        _in_topic(50, 10, text=None, pinned_message=None, new_chat_members=[STAFF]),
        # Some other group the bot was added to.
        _in_topic(50, 10).model_copy(update={"chat": Chat(id=-100123, type="supergroup", is_forum=True)}),
    ],
)
async def test_what_is_not_a_conversation_is_ignored(routed, message) -> None:
    await _feed(routed, message)

    bot, _, desk = routed
    assert bot.sent == []
    desk.from_staff.assert_not_awaited()
    desk.from_person.assert_not_awaited()


async def test_an_album_arrives_as_one(routed) -> None:
    """Telegram sends an album as separate messages sharing a media group."""
    bot, _, desk = routed
    dp = ads.build_dispatcher(desk, GROUP, album_wait=0.05)
    photo = [PhotoSize(file_id="f", file_unique_id="u", width=1, height=1)]
    album = [_private(i, text=None, media_group_id="g", photo=photo) for i in (5, 6)]
    await asyncio.gather(*(dp.feed_update(bot, Update(update_id=i, message=m)) for i, m in enumerate(album)))

    ((messages,), _) = desk.from_person.await_args
    assert [m.message_id for m in messages] == [5, 6]
    assert desk.from_person.await_count == 1


async def _relayed_in_order(session_maker, messages: list[Message]) -> list[Any]:
    bot = _bot()
    desk = AdsDesk(bot, session_maker, GROUP)
    if messages[0].chat.id == GROUP:
        await desk.from_person([_private(1)])
        bot.reset_mock()
    dp = ads.build_dispatcher(desk, GROUP, album_wait=0.05)
    recording = _RecordingBot()
    await asyncio.gather(*(dp.feed_update(recording, Update(update_id=i, message=m)) for i, m in enumerate(messages)))
    return [
        call.kwargs.get("message_ids") or call.kwargs["message_id"]
        for call in bot.mock_calls
        if call[0] in {"copy_message", "copy_messages"}
    ]


PHOTO = [PhotoSize(file_id="f", file_unique_id="u", width=1, height=1)]


async def test_a_message_written_after_an_album_does_not_overtake_it(session_maker) -> None:
    album = [_private(i, text=None, media_group_id="g", photo=PHOTO) for i in (5, 6)]

    assert await _relayed_in_order(session_maker, [*album, _private(7)]) == [[5, 6], 7]


async def test_a_staff_answer_after_an_album_does_not_overtake_it(session_maker) -> None:
    album = [_in_topic(i, 10, text=None, media_group_id="s", photo=PHOTO) for i in (55, 56)]

    assert await _relayed_in_order(session_maker, [*album, _in_topic(57, 10)]) == [[55, 56], 57]


async def test_an_album_delivered_out_of_order_is_copied_in_order(session_maker) -> None:
    album = [_private(i, text=None, media_group_id="g", photo=PHOTO) for i in (6, 5)]

    assert await _relayed_in_order(session_maker, album) == [[5, 6]]


async def test_a_stuck_topic_does_not_hold_up_another_topic(routed) -> None:
    """Each topic is a conversation of its own, not the whole staff group."""
    bot, _, desk = routed
    stuck = asyncio.Event()
    reached: list[int] = []

    async def from_staff(messages: list[Message]) -> None:
        reached.append(messages[0].message_thread_id or 0)
        if messages[0].message_thread_id == 10:
            await stuck.wait()

    desk.from_staff.side_effect = from_staff
    dp = ads.build_dispatcher(desk, GROUP, album_wait=0)
    hanging = asyncio.create_task(dp.feed_update(bot, Update(update_id=1, message=_in_topic(50, 10))))
    await asyncio.sleep(0.05)

    await asyncio.wait_for(dp.feed_update(bot, Update(update_id=2, message=_in_topic(51, 11))), timeout=1)

    assert reached == [10, 11]
    stuck.set()
    await hanging


# --- Configuration ----------------------------------------------------------


def _settings(monkeypatch, **env: str) -> AdsBotSettings:
    for name in ("ADS_BOT_TOKEN", "ADS_BOT_GROUP_ID", "ADS_BOT_CONTACT", "ADS_BOT_NAME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return AdsBotSettings(_env_file=None)


def test_without_a_token_the_desk_is_off(monkeypatch) -> None:
    assert not _settings(monkeypatch).token
    # A secret that was never given a value arrives empty.
    assert _settings(monkeypatch, ADS_BOT_TOKEN="", ADS_BOT_GROUP_ID="").group_id == ""


def test_a_mistyped_group_does_not_stop_the_process_from_reading_its_settings(monkeypatch) -> None:
    """Moderation reads the same settings; a bad value here must not keep it from booting."""
    assert _settings(monkeypatch, ADS_BOT_GROUP_ID="https://t.me/c/123").group_id == "https://t.me/c/123"


def _configured(monkeypatch, token: str, group_id: str, retired: list[str] | None = None) -> MagicMock:
    monkeypatch.setattr(ads.settings.ads_bot, "token", token)
    monkeypatch.setattr(ads.settings.ads_bot, "group_id", group_id)
    monkeypatch.setattr(ads.settings.telegram, "retired_tokens", retired or [])
    logger = MagicMock()
    monkeypatch.setattr(ads, "logger", logger)
    return logger


def test_no_token_builds_no_bot(monkeypatch) -> None:
    _configured(monkeypatch, "", str(GROUP))

    assert ads.build_ads_bot(MagicMock()) is None


def test_a_token_without_a_group_builds_no_bot_and_says_so(monkeypatch) -> None:
    logger = _configured(monkeypatch, ADS, "")

    assert ads.build_ads_bot(MagicMock()) is None
    logger.warning.assert_called_once_with("ads_bot_without_group")


@pytest.mark.parametrize("group", ["@konnekt_ads", "https://t.me/c/9990001", "9990001", "-9990001", "-100abc"])
def test_a_group_that_is_not_a_supergroup_id_builds_no_bot(monkeypatch, group) -> None:
    logger = _configured(monkeypatch, ADS, group)

    assert ads.build_ads_bot(MagicMock()) is None
    logger.error.assert_called_once_with("ads_group_malformed")
    assert group not in str(logger.mock_calls)


@pytest.mark.parametrize("which", ["moderator", "retired"])
def test_a_token_another_poller_uses_is_refused(monkeypatch, which) -> None:
    """A second poller on one token takes turns with the first for its updates."""
    taken = ads.settings.telegram.token if which == "moderator" else "300:moder"
    logger = _configured(monkeypatch, taken, str(GROUP), retired=["300:moder"])

    assert ads.build_ads_bot(MagicMock()) is None
    logger.warning.assert_called_once_with("ads_token_is_moderators")
    assert taken not in str(logger.mock_calls)


def test_a_malformed_token_is_refused_without_being_logged(monkeypatch) -> None:
    logger = _configured(monkeypatch, "123:with spaces", str(GROUP))

    assert ads.build_ads_bot(MagicMock()) is None
    logger.error.assert_called_once_with("ads_token_malformed")
    assert "with spaces" not in str(logger.mock_calls)


def test_a_configured_desk_gets_a_bot_of_its_own(monkeypatch) -> None:
    _configured(monkeypatch, ADS, f" {GROUP} ")

    built = ads.build_ads_bot(MagicMock())

    assert built is not None
    assert built[0].token == ADS


def _member(can_manage_topics: bool) -> Any:
    from aiogram.types import ChatMemberAdministrator

    return ChatMemberAdministrator(
        user=User(id=400, is_bot=True, first_name="ads"),
        can_be_edited=False,
        is_anonymous=False,
        can_manage_chat=True,
        can_delete_messages=True,
        can_manage_video_chats=False,
        can_restrict_members=False,
        can_promote_members=False,
        can_change_info=False,
        can_invite_users=False,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
        can_manage_topics=can_manage_topics,
    )


@pytest.mark.parametrize(
    ("forum", "member", "warnings"),
    [
        (True, _member(can_manage_topics=True), []),
        (False, _member(can_manage_topics=True), ["ads_group_not_a_forum"]),
        (True, _member(can_manage_topics=False), ["ads_bot_cannot_manage_topics"]),
        (True, None, ["ads_bot_cannot_manage_topics"]),
    ],
)
async def test_the_group_is_checked_when_the_desk_starts(monkeypatch, forum, member, warnings) -> None:
    """Rather than at the first person who writes."""
    logger = MagicMock()
    monkeypatch.setattr(ads, "logger", logger)
    bot = AsyncMock()
    bot.id = 400
    bot.get_chat.return_value = SimpleNamespace(is_forum=forum)
    bot.get_chat_member.return_value = member or SimpleNamespace(status="member")

    await ads.build_dispatcher(AsyncMock(), GROUP).emit_startup(bot=bot)

    assert [c.args[0] for c in logger.warning.call_args_list] == warnings


async def test_an_unreachable_group_is_logged_and_the_desk_still_starts(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(ads, "logger", logger)
    bot = AsyncMock()
    bot.get_chat.side_effect = TelegramBadRequest(method=MagicMock(), message="Bad Request: chat not found")

    await ads.build_dispatcher(AsyncMock(), GROUP).emit_startup(bot=bot)

    logger.warning.assert_called_once_with("ads_group_unreachable", error="Bad Request: chat not found")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("konnekt_ads_bot", "konnekt_ads_bot"),
        (" @konnekt_ads_bot ", "konnekt_ads_bot"),
        ("", None),
        # A link or a typo offers nobody rather than a button that opens nothing.
        ("https://t.me/konnekt_ads_bot", None),
        ("konnekt ads", None),
    ],
)
def test_the_contact_is_a_username_or_nobody(monkeypatch, raw, expected) -> None:
    assert _settings(monkeypatch, ADS_BOT_CONTACT=raw).contact_username == expected


def test_a_mistyped_contact_does_not_stop_the_process_from_reading_its_settings(monkeypatch) -> None:
    assert _settings(monkeypatch, ADS_BOT_CONTACT="https://t.me/x").contact == "https://t.me/x"


# --- What Telegram shows about the desk -------------------------------------


def _profile_bot(name: str = "Konnekt · Ad", description: str = "", short: str = "") -> AsyncMock:
    bot = AsyncMock()
    bot.get_my_name.return_value = SimpleNamespace(name=name)
    bot.get_my_description.return_value = SimpleNamespace(description=description)
    bot.get_my_short_description.return_value = SimpleNamespace(short_description=short)
    return bot


async def test_the_desk_introduces_itself_as_the_way_to_reach_us(monkeypatch) -> None:
    monkeypatch.setattr(ads.settings.ads_bot, "name", "Konnekt · Связь")
    bot = _profile_bot()

    await ads.publish_profile(bot)

    bot.set_my_name.assert_awaited_once_with(name="Konnekt · Связь")
    description = bot.set_my_description.await_args.kwargs["description"]
    short = bot.set_my_short_description.await_args.kwargs["short_description"]
    assert "по любому вопросу" in description
    assert "по любому вопросу" in short
    # Telegram's limits.
    assert len(description) <= 512
    assert len(short) <= 120


def test_the_name_defaults_to_the_agreed_one(monkeypatch) -> None:
    assert _settings(monkeypatch).name == "Konnekt · Связь"
    assert _settings(monkeypatch, ADS_BOT_NAME="Konnekt · Команда").name == "Konnekt · Команда"
    # A variable that was never given a value keeps the default.
    assert _settings(monkeypatch, ADS_BOT_NAME="").name == "Konnekt · Связь"


async def test_a_profile_already_right_is_not_written_again(monkeypatch) -> None:
    """Every deploy restarts the bot, and setMyName is rate-limited for hours."""
    monkeypatch.setattr(ads.settings.ads_bot, "name", "Konnekt · Связь")
    bot = _profile_bot("Konnekt · Связь", ads.DESCRIPTION, ads.SHORT_DESCRIPTION)

    await ads.publish_profile(bot)

    bot.set_my_name.assert_not_awaited()
    bot.set_my_description.assert_not_awaited()
    bot.set_my_short_description.assert_not_awaited()


async def test_one_refused_profile_step_leaves_the_others_done(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(ads, "logger", logger)
    bot = _profile_bot()
    bot.set_my_description.side_effect = _flood(3600)

    await ads.publish_profile(bot)

    bot.set_my_short_description.assert_awaited()
    bot.set_my_name.assert_awaited()
    logger.warning.assert_called_once()


async def test_the_profile_is_published_when_the_desk_starts() -> None:
    dp = ads.build_dispatcher(AsyncMock(), GROUP)

    assert ads.publish_profile in [handler.callback for handler in dp.startup.handlers]


# --- In the bot process -----------------------------------------------------


@pytest.fixture
def serving(monkeypatch) -> list[dict]:
    from app.presentation.telegram import bot as bot_module
    from app.presentation.telegram import moved

    calls: list[dict] = []

    async def fake_run_polling(bot, dp, *, name, **kwargs):
        calls.append({"name": name, **kwargs})
        if name == "ads":
            raise ConnectionError("ads token revoked")
        # Long enough for an uncontained failure of the desk to end the process first.
        await asyncio.sleep(0.05)

    main_bot = AsyncMock()
    monkeypatch.setattr(bot_module, "_setup_main_bot", lambda _: (main_bot, AsyncMock()))
    monkeypatch.setattr(bot_module, "setup_container", lambda *_: None)
    monkeypatch.setattr(bot_module, "_run_polling", fake_run_polling)
    monkeypatch.setattr(bot_module, "close_db", AsyncMock())
    monkeypatch.setattr(moved, "build_moved_bots", lambda: [])

    async def idle(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.mcp.runner.run_mcp_server", idle)
    monkeypatch.setattr("app.moderation.pending_actions.run_expiry_sweep", idle)
    monkeypatch.setattr("app.moderation.history_service.run_history_retention", idle)
    monkeypatch.setattr("app.chats.snapshots.run_snapshot_loop", idle)
    monkeypatch.setattr("app.presentation.telegram.heartbeat.watch", idle)
    return calls


async def test_the_desk_polls_beside_moderation_and_its_failure_is_contained(monkeypatch, serving) -> None:
    from app.presentation.telegram import bot as bot_module

    monkeypatch.setattr(ads, "build_ads_bot", lambda _sm: (SimpleNamespace(id=400), AsyncMock()))

    await bot_module._serve()

    (desk,) = [c for c in serving if c["name"] == "ads"]
    # The main bot owns SIGTERM.
    assert desk["handle_signals"] is False
    assert desk["allowed_updates"] == ["message"]
    assert any(c["name"] == "main" for c in serving)


async def test_without_a_desk_nothing_extra_polls(monkeypatch, serving) -> None:
    from app.presentation.telegram import bot as bot_module

    monkeypatch.setattr(ads, "build_ads_bot", lambda _sm: None)

    await bot_module._serve()

    assert [c["name"] for c in serving] == ["main"]


def test_the_desk_is_configured_on_the_bot_process_only() -> None:
    """A second process polling the same token would take turns with it for updates."""
    import yaml

    from tests.unit.test_deploy_config import COMPOSE, _deploy_step

    services = yaml.safe_load(COMPOSE.read_text())["services"]
    forwarded = _deploy_step()["with"]["envs"].split(",")
    for name in ("ADS_BOT_TOKEN", "ADS_BOT_GROUP_ID", "ADS_BOT_NAME"):
        assert name in forwarded
        assert [s for s, spec in services.items() if name in (spec.get("environment") or {})] == ["bot"]
