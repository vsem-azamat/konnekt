"""The greeting a chat gives new members: one message per burst of joiners.

`Chat.welcome_message`, `is_welcome_enabled` and `time_delete` were stored and
ignored for a long time; these tests are what makes the toggle mean something.
A greeting per person turned a burst of joins into a wall of greetings, so
whoever joins while the last one is still up is added to it by an edit.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Chat, ChatMemberLeft, ChatMemberMember, ChatMemberUpdated, User
from app.chats import welcome
from app.core import intro
from app.core.config import settings
from app.db.models import Chat as DbChat
from app.presentation.telegram.handlers.events import user_joined
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit

CHAT_ID = -1001234
BOT_USERNAME = "konnekt_test_bot"
# The copy Azamat approved (W2), pinned here so a change of it is seen.
KONNEKT_LINE = (
    "<b>Konnekt</b> — всё для студентов в Чехии в одном приложении.\n\n"
    "💬 чат своего факультета в пару касаний\n"
    "🎓 репетиторы и помощь с экзаменами\n"
    "📄 страховка, справки, жильё\n"
    "🙋 умеешь то, что нужно другим? Предложи услугу"
)


def _join(user_id: int = 4242, name: str = "Marek") -> ChatMemberUpdated:
    """A join. Which transitions reach the handler is aiogram's filter, not ours."""
    user = User(id=user_id, is_bot=False, first_name=name, last_name="Novák")
    return ChatMemberUpdated(
        chat=Chat(id=CHAT_ID, type="supergroup", title="VUT FIT"),
        from_user=user,
        date=datetime.now(UTC),
        old_chat_member=ChatMemberLeft(user=user, status=ChatMemberStatus.LEFT),
        new_chat_member=ChatMemberMember(user=user, status=ChatMemberStatus.MEMBER),
    )


async def _seed(session: AsyncSession, **kwargs) -> DbChat:
    chat = DbChat(id=CHAT_ID, title="VUT FIT", resource_status=DbChat.STATUS_APPROVED, **kwargs)
    session.add(chat)
    await session.commit()
    return chat


@pytest.fixture
def bot() -> MagicMock:
    tg_bot = MagicMock()
    tg_bot.me = AsyncMock(return_value=User(id=1, is_bot=True, first_name="Konnekt", username=BOT_USERNAME))
    tg_bot.send_message = AsyncMock(return_value=MagicMock(message_id=9))
    tg_bot.send_video = AsyncMock(return_value=MagicMock(message_id=10))
    tg_bot.edit_message_text = AsyncMock()
    tg_bot.edit_message_caption = AsyncMock()
    tg_bot.delete_message = AsyncMock()
    return tg_bot


@pytest.fixture
def timers(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The lifetimes the greetings were given; none of them runs out unless a test says so."""
    asked: list[float] = []

    async def wait(seconds: float) -> None:
        asked.append(seconds)
        await asyncio.Event().wait()

    monkeypatch.setattr(welcome, "_sleep", wait)
    return asked


@pytest.fixture(autouse=True)
def _no_video(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.telegram, "intro_video", "")
    monkeypatch.setattr(settings.telegram, "intro_video_cover", "")


def _sent_text(bot) -> str:
    return bot.send_message.await_args.kwargs["text"]


# --- whether there is a greeting at all ----------------------------------------


async def test_an_enabled_chat_greets_the_newcomer(session: AsyncSession, bot, timers) -> None:
    await _seed(session, is_welcome_enabled=True)

    await user_joined(_join(), bot, session)

    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == CHAT_ID
    assert kwargs["text"] == '👋 <a href="tg://user?id=4242">Marek</a>, <b>добро пожаловать!</b>\n\n' + KONNEKT_LINE


async def test_the_chats_own_text_is_the_third_line(session: AsyncSession, bot, timers) -> None:
    await _seed(session, is_welcome_enabled=True, welcome_message="Правила: без рекламы")

    await user_joined(_join(), bot, session)

    assert _sent_text(bot).endswith(KONNEKT_LINE + "\n\nПравила: без рекламы")


async def test_disabled_welcome_stays_silent(session: AsyncSession, bot, timers) -> None:
    await _seed(session, welcome_message="Добро пожаловать!", is_welcome_enabled=False)

    await user_joined(_join(), bot, session)

    bot.send_message.assert_not_awaited()
    bot.send_video.assert_not_awaited()


async def test_unknown_chat_stays_silent(session: AsyncSession, bot, timers) -> None:
    await user_joined(_join(), bot, session)

    bot.send_message.assert_not_awaited()


async def test_the_button_opens_konnekt_through_the_bot_link(session: AsyncSession, bot, timers) -> None:
    """A Mini App button is refused in a group; the link opens it and records the source."""
    await _seed(session, is_welcome_enabled=True)

    await user_joined(_join(), bot, session)

    [[button]] = bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard
    assert button.text == "Открыть Konnekt 📱"
    assert button.url == f"https://t.me/{BOT_USERNAME}?startapp=welcome"


# --- one message per burst -------------------------------------------------------


async def test_a_second_joiner_is_added_to_the_greeting_by_an_edit(session: AsyncSession, bot, timers) -> None:
    await _seed(session, is_welcome_enabled=True)

    await user_joined(_join(1, "Marek"), bot, session)
    await user_joined(_join(2, "Tereza"), bot, session)

    bot.send_message.assert_awaited_once()
    edit = bot.edit_message_text.await_args.kwargs
    assert edit["chat_id"] == CHAT_ID
    assert edit["message_id"] == 9
    assert edit["text"].startswith(
        '👋 <a href="tg://user?id=1">Marek</a>, <a href="tg://user?id=2">Tereza</a>, <b>добро пожаловать!</b>'
    )
    assert edit["reply_markup"].inline_keyboard[0][0].text == "Открыть Konnekt 📱"


async def test_past_three_names_the_rest_are_counted(session: AsyncSession, bot, timers) -> None:
    await _seed(session, is_welcome_enabled=True)

    for user_id, name in enumerate(["Marek", "Tereza", "Jakub", "Petr", "Eva"], start=1):
        await user_joined(_join(user_id, name), bot, session)

    text = bot.edit_message_text.await_args.kwargs["text"]
    assert "Jakub</a> и ещё 2, <b>добро пожаловать!</b>" in text
    assert "Petr" not in text


async def test_the_greeting_lives_its_time_from_the_last_joiner(session: AsyncSession, bot, timers) -> None:
    await _seed(session, is_welcome_enabled=True, time_delete=45)

    await user_joined(_join(1), bot, session)
    await user_joined(_join(2), bot, session)
    await asyncio.sleep(0)

    assert timers == [45, 45]


async def test_once_the_greeting_is_gone_the_next_joiner_gets_a_new_one(
    session: AsyncSession, bot, monkeypatch
) -> None:
    ran_out = asyncio.Event()

    async def wait(seconds: float) -> None:
        await ran_out.wait()

    monkeypatch.setattr(welcome, "_sleep", wait)
    await _seed(session, is_welcome_enabled=True, time_delete=45)
    await user_joined(_join(1), bot, session)

    ran_out.set()
    for _ in range(5):
        await asyncio.sleep(0)

    ran_out.clear()
    await user_joined(_join(2), bot, session)
    assert bot.send_message.await_count == 2
    bot.edit_message_text.assert_not_awaited()


async def test_zero_lifetime_keeps_the_message(session: AsyncSession, bot, monkeypatch) -> None:
    """Kept, but a joiner long after is not added to a greeting nobody scrolls back to."""
    ran_out = asyncio.Event()
    asked: list[float] = []

    async def wait(seconds: float) -> None:
        asked.append(seconds)
        await ran_out.wait()

    monkeypatch.setattr(welcome, "_sleep", wait)
    await _seed(session, is_welcome_enabled=True, time_delete=0)
    await user_joined(_join(1), bot, session)
    await asyncio.sleep(0)

    ran_out.set()
    for _ in range(5):
        await asyncio.sleep(0)

    assert asked == [welcome.BURST_SECONDS]
    bot.delete_message.assert_not_awaited()
    await user_joined(_join(2), bot, session)
    assert bot.send_message.await_count == 2


async def test_a_greeting_deleted_by_hand_is_replaced_not_lost(session: AsyncSession, bot, timers) -> None:
    await _seed(session, is_welcome_enabled=True)
    await user_joined(_join(1), bot, session)
    bot.edit_message_text.side_effect = TelegramBadRequest(method=MagicMock(), message="message to edit not found")

    await user_joined(_join(2, "Tereza"), bot, session)

    assert bot.send_message.await_count == 2
    assert 'tg://user?id=2">Tereza' in _sent_text(bot)
    assert "tg://user?id=1" not in _sent_text(bot)


async def test_chats_do_not_share_a_burst(session: AsyncSession, bot, timers) -> None:
    await _seed(session, is_welcome_enabled=True)
    other = DbChat(id=CHAT_ID - 1, title="VUT FEKT", resource_status=DbChat.STATUS_APPROVED, is_welcome_enabled=True)
    session.add(other)
    await session.commit()

    await user_joined(_join(1), bot, session)
    elsewhere = _join(2).model_copy(update={"chat": Chat(id=CHAT_ID - 1, type="supergroup", title="VUT FEKT")})
    await user_joined(elsewhere, bot, session)

    assert bot.send_message.await_count == 2
    bot.edit_message_text.assert_not_awaited()


async def test_joiners_arriving_together_get_one_greeting(session: AsyncSession, bot, timers) -> None:
    joiners = [_join(i).new_chat_member.user for i in range(1, 4)]

    await asyncio.gather(*(welcome.greet(bot, CHAT_ID, user, chat_text=None, lifetime=60) for user in joiners))

    bot.send_message.assert_awaited_once()
    assert bot.edit_message_text.await_count == 2


@pytest.fixture
def clocks(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.Event]:
    """One per greeting clock started, in order; setting it runs that clock out."""
    started: list[asyncio.Event] = []

    async def wait(seconds: float) -> None:
        ran_out = asyncio.Event()
        started.append(ran_out)
        await ran_out.wait()

    monkeypatch.setattr(welcome, "_sleep", wait)
    return started


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_a_later_joiner_restarts_the_clock_instead_of_adding_one(session: AsyncSession, bot, clocks) -> None:
    await _seed(session, is_welcome_enabled=True, time_delete=45)
    await user_joined(_join(1), bot, session)
    await _settle()
    await user_joined(_join(2), bot, session)
    await _settle()

    clocks[0].set()
    await _settle()

    bot.delete_message.assert_not_awaited()
    await user_joined(_join(3), bot, session)
    bot.send_message.assert_awaited_once()


async def test_the_clock_of_a_replaced_greeting_leaves_the_new_one_alone(session: AsyncSession, bot, clocks) -> None:
    await _seed(session, is_welcome_enabled=True, time_delete=45)
    await user_joined(_join(1), bot, session)
    bot.edit_message_text.side_effect = TelegramBadRequest(method=MagicMock(), message="message to edit not found")
    bot.send_message.return_value = MagicMock(message_id=11)
    await user_joined(_join(2), bot, session)
    await _settle()
    bot.edit_message_text.side_effect = None

    clocks[0].set()
    await _settle()
    await user_joined(_join(3), bot, session)

    assert bot.edit_message_text.await_args.kwargs["message_id"] == 11
    assert bot.send_message.await_count == 2


async def test_flood_control_on_an_edit_still_counts_the_joiner(session: AsyncSession, bot, timers) -> None:
    await _seed(session, is_welcome_enabled=True)
    await user_joined(_join(1, "Marek"), bot, session)
    bot.edit_message_text.side_effect = TelegramRetryAfter(
        method=MagicMock(), message="Too Many Requests", retry_after=5
    )
    await user_joined(_join(2, "Tereza"), bot, session)
    bot.edit_message_text.side_effect = None

    await user_joined(_join(3, "Jakub"), bot, session)

    bot.send_message.assert_awaited_once()
    text = bot.edit_message_text.await_args.kwargs["text"]
    assert "Marek</a>, " in text
    assert "Tereza</a>, " in text
    assert "Jakub</a>, <b>" in text


async def test_someone_who_rejoins_is_named_once(session: AsyncSession, bot, timers) -> None:
    await _seed(session, is_welcome_enabled=True)

    await user_joined(_join(1), bot, session)
    await user_joined(_join(1), bot, session)

    bot.edit_message_text.assert_not_awaited()


# --- the video ---------------------------------------------------------------------


async def test_with_a_video_configured_the_greeting_is_its_caption(
    session: AsyncSession, bot, timers, monkeypatch
) -> None:
    monkeypatch.setattr(settings.telegram, "intro_video", "video-file-id")
    await _seed(session, is_welcome_enabled=True)

    await user_joined(_join(1), bot, session)
    await user_joined(_join(2), bot, session)

    bot.send_message.assert_not_awaited()
    sent = bot.send_video.await_args.kwargs
    assert sent["video"] == "video-file-id"
    assert sent["cover"] is None
    assert sent["supports_streaming"] is True
    assert sent["caption"].startswith("👋 ")
    [[button]] = sent["reply_markup"].inline_keyboard
    assert button.url == f"https://t.me/{BOT_USERNAME}?startapp=welcome"
    edit = bot.edit_message_caption.await_args.kwargs
    assert edit["message_id"] == 10
    assert "tg://user?id=2" in edit["caption"]
    bot.edit_message_text.assert_not_awaited()


async def test_the_video_shows_its_cover_before_it_plays(session: AsyncSession, bot, timers, monkeypatch) -> None:
    monkeypatch.setattr(settings.telegram, "intro_video", "video-file-id")
    monkeypatch.setattr(settings.telegram, "intro_video_cover", "cover-file-id")
    await _seed(session, is_welcome_enabled=True)

    await user_joined(_join(), bot, session)

    assert bot.send_video.await_args.kwargs["cover"] == "cover-file-id"


async def test_a_refused_video_falls_back_to_text(session: AsyncSession, bot, timers, monkeypatch) -> None:
    monkeypatch.setattr(settings.telegram, "intro_video", "file-of-another-bot")
    bot.send_video.side_effect = TelegramBadRequest(method=MagicMock(), message="wrong file identifier")
    await _seed(session, is_welcome_enabled=True)

    await user_joined(_join(1), bot, session)
    await user_joined(_join(2), bot, session)

    bot.send_message.assert_awaited_once()
    bot.edit_message_text.assert_awaited_once()


async def test_a_text_too_long_for_a_caption_goes_without_the_video(
    session: AsyncSession, bot, timers, monkeypatch
) -> None:
    monkeypatch.setattr(settings.telegram, "intro_video", "video-file-id")
    await _seed(session, is_welcome_enabled=True, welcome_message="Правила. " * 150)

    await user_joined(_join(), bot, session)

    bot.send_video.assert_not_awaited()
    bot.send_message.assert_awaited_once()


async def test_names_that_would_not_fit_under_the_video_are_counted(
    session: AsyncSession, bot, timers, monkeypatch
) -> None:
    monkeypatch.setattr(settings.telegram, "intro_video", "video-file-id")
    long_text = "П" * (intro.CAPTION_LIMIT - 300)
    await _seed(session, is_welcome_enabled=True, welcome_message=long_text)

    await user_joined(_join(1, "M" * 60), bot, session)
    await user_joined(_join(2, "T" * 60), bot, session)
    await user_joined(_join(3, "J" * 60), bot, session)

    bot.send_video.assert_awaited_once()
    caption = bot.edit_message_caption.await_args.kwargs["caption"]
    assert intro.fits_caption(caption)
    assert " и ещё " in caption


async def test_a_greeting_telegram_refuses_does_not_break_the_join(session: AsyncSession, bot, timers) -> None:
    """One bad stored value used to fail every join in the chat."""
    await _seed(session, welcome_message="Привет", is_welcome_enabled=True)
    bot.send_message.side_effect = TelegramBadRequest(method=MagicMock(), message="not enough rights to send")

    await user_joined(_join(), bot, session)
    await user_joined(_join(2), bot, session)

    assert bot.send_message.await_count == 2


async def test_a_raw_text_telegram_cannot_parse_is_shown_as_typed(session: AsyncSession, bot, timers) -> None:
    """The console stores what the admin typed, `<` included; the greeting goes out as HTML."""
    await _seed(session, welcome_message="Q&A <3", is_welcome_enabled=True)

    def parse(**kwargs):
        if "<3" in kwargs["text"]:
            raise TelegramBadRequest(method=MagicMock(), message="can't parse entities")
        return MagicMock(message_id=9)

    bot.send_message.side_effect = parse

    await user_joined(_join(1), bot, session)
    await user_joined(_join(2), bot, session)

    assert _sent_text(bot).endswith(KONNEKT_LINE + "\n\nQ&amp;A &lt;3")
    assert bot.edit_message_text.await_args.kwargs["text"].endswith("\n\nQ&amp;A &lt;3")


async def test_a_refusal_for_another_reason_is_not_retried(session: AsyncSession, bot, timers) -> None:
    await _seed(session, welcome_message="Q&A", is_welcome_enabled=True)
    bot.send_message.side_effect = TelegramBadRequest(method=MagicMock(), message="not enough rights to send")

    await user_joined(_join(), bot, session)

    bot.send_message.assert_awaited_once()


async def test_a_text_that_breaks_the_caption_is_not_blamed_on_the_video(
    session: AsyncSession, bot, timers, monkeypatch
) -> None:
    """The video stays: only the text is escaped, and the video is sent once more with it."""
    monkeypatch.setattr(settings.telegram, "intro_video", "video-file-id")
    await _seed(session, welcome_message="a < b", is_welcome_enabled=True)

    def parse(**kwargs):
        if "a < b" in kwargs["caption"]:
            raise TelegramBadRequest(method=MagicMock(), message="Bad Request: can't parse entities")
        return MagicMock(message_id=10)

    bot.send_video.side_effect = parse

    await user_joined(_join(), bot, session)

    assert bot.send_video.await_count == 2
    bot.send_message.assert_not_awaited()
    assert bot.send_video.await_args.kwargs["caption"].endswith("\n\na &lt; b")


async def test_a_captcha_closed_by_the_join_still_greets(session: AsyncSession, bot, timers) -> None:
    """Let in by an admin while their captcha waited: the captcha closes and the greeting follows."""
    from app.db.models import JoinCaptcha

    await _seed(session, is_welcome_enabled=True)
    session.add(
        JoinCaptcha(
            chat_id=CHAT_ID,
            user_id=4242,
            user_chat_id=4242,
            answer="cat",
            options=["cat", "dog"],
            attempts_left=2,
            created_at=datetime.now(UTC).replace(tzinfo=None),
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            status=JoinCaptcha.STATUS_PENDING,
        )
    )
    await session.commit()

    await user_joined(_join(), bot, session)

    assert (await session.scalar(select(JoinCaptcha.status))) == JoinCaptcha.STATUS_GONE
    bot.send_message.assert_awaited_once()


# --- deleted on time, by the sweep, restart or not --------------------------


def _rows(session: AsyncSession):
    from app.db.models import WelcomeGreeting

    return session.scalars(select(WelcomeGreeting))


async def test_a_greeting_is_deleted_on_time_after_a_restart(session: AsyncSession, bot, timers) -> None:
    """The process that posted it is gone; the row it left still deletes it."""
    await _seed(session, is_welcome_enabled=True, time_delete=900)
    await user_joined(_join(1), bot, session)
    (row,) = (await _rows(session)).all()
    welcome.forget()  # the restart

    await welcome.sweep(bot, session, now=row.delete_at - timedelta(seconds=1))
    bot.delete_message.assert_not_awaited()

    await welcome.sweep(bot, session, now=row.delete_at)
    bot.delete_message.assert_awaited_once_with(chat_id=CHAT_ID, message_id=9)
    assert (await _rows(session)).all() == []


async def test_the_last_joiner_decides_when_the_greeting_goes(session: AsyncSession, bot, timers, monkeypatch) -> None:
    t0 = datetime(2026, 10, 29, 12, 0)
    monkeypatch.setattr(welcome, "utc_now", lambda: t0)
    await _seed(session, is_welcome_enabled=True, time_delete=900)
    await user_joined(_join(1), bot, session)
    monkeypatch.setattr(welcome, "utc_now", lambda: t0 + timedelta(minutes=10))
    await user_joined(_join(2), bot, session)

    await welcome.sweep(bot, session, now=t0 + timedelta(minutes=20))
    bot.delete_message.assert_not_awaited()
    await welcome.sweep(bot, session, now=t0 + timedelta(minutes=25))
    bot.delete_message.assert_awaited_once_with(chat_id=CHAT_ID, message_id=9)


async def test_a_greeting_telegram_no_longer_has_is_forgotten(session: AsyncSession, bot, timers) -> None:
    """Deleted by an admin, or past the 48 hours a bot may delete its own message in."""
    await _seed(session, is_welcome_enabled=True, time_delete=60)
    await user_joined(_join(1), bot, session)
    bot.delete_message.side_effect = TelegramBadRequest(method=MagicMock(), message="message to delete not found")

    await welcome.sweep(bot, session, now=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1))

    assert (await _rows(session)).all() == []


async def test_flood_control_on_a_delete_tries_again_next_run(session: AsyncSession, bot, timers) -> None:
    await _seed(session, is_welcome_enabled=True, time_delete=60)
    await user_joined(_join(1), bot, session)
    bot.delete_message.side_effect = TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=5)
    later = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

    await welcome.sweep(bot, session, now=later)
    assert len((await _rows(session)).all()) == 1

    bot.delete_message.side_effect = None
    await welcome.sweep(bot, session, now=later)
    assert (await _rows(session)).all() == []


async def test_a_chat_that_keeps_its_greetings_records_none(session: AsyncSession, bot, timers) -> None:
    await _seed(session, is_welcome_enabled=True, time_delete=0)

    await user_joined(_join(1), bot, session)

    bot.send_message.assert_awaited_once()
    assert (await _rows(session)).all() == []
