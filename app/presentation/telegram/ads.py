"""@konnekt_ads_bot, the ads contact desk, polling next to the main bot.

What it does with a message is `app.ads.desk`; this is which messages reach it.
It is off unless `ADS_BOT_TOKEN` and `ADS_BOT_GROUP_ID` are both set.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from functools import partial
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.enums import ContentType
from aiogram.filters import CommandStart
from aiogram.types import ChatMemberAdministrator, Message, TelegramObject
from aiogram.utils.token import TokenValidationError

from app.ads.desk import AdsDesk
from app.core.config import settings
from app.core.enums import Touchpoint
from app.core.logging import get_logger
from app.presentation.telegram.middlewares.audience import AudienceMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger("ads_bot")

GREETING = (
    "Здравствуйте! Это команда Konnekt.\n\n"
    "Напишите здесь по любому вопросу — о чатах, рекламе и сотрудничестве, помощи с учёбой или о чём-то ещё. "
    "Ответим в этом чате."
)
DESCRIPTION = (
    "Konnekt — студенческие чаты Чехии. Здесь можно написать нашей команде по любому вопросу: "
    "о чатах, о рекламе и сотрудничестве, о помощи с учёбой или о чём-то ещё.\n\n"
    "Отправьте сообщение — ответим здесь же."
)
SHORT_DESCRIPTION = (
    "Связь с командой Konnekt по любому вопросу: чаты, реклама, сотрудничество, помощь с учёбой. Ответим здесь."
)

# What copyMessage can carry. Everything else is a service message: a topic
# being created, a member joining, a pin.
COPYABLE = {
    ContentType.TEXT,
    ContentType.PHOTO,
    ContentType.VIDEO,
    ContentType.ANIMATION,
    ContentType.DOCUMENT,
    ContentType.AUDIO,
    ContentType.VOICE,
    ContentType.VIDEO_NOTE,
    ContentType.STICKER,
    ContentType.CONTACT,
    ContentType.LOCATION,
    ContentType.VENUE,
    ContentType.POLL,
    ContentType.DICE,
    ContentType.STORY,
}

# How long to wait for the rest of an album after its first message.
ALBUM_WAIT = 1.0
# A supergroup's id as the Bot API writes it.
GROUP_ID = re.compile(r"-100\d+")


class Conversations(BaseMiddleware):
    """Hands on each conversation's messages one at a time, in arrival order, an album as one.

    An outer middleware because it must see messages in the order they came:
    aiogram runs a plain filter in a thread, so by the time a message reaches
    its handler, a later one may have got there first. Telegram also delivers
    an album as separate messages; its first message waits for the rest
    inside its conversation's turn, so nothing written after the album can
    overtake it, and the rest only join it. The handler gets them all as
    `messages`.
    """

    def __init__(self, wait: float) -> None:
        self.wait = wait
        self._turns: defaultdict[tuple[int, int | None], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._albums: dict[tuple[int, int | None, str], list[Message]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
        key = (event.chat.id, event.message_thread_id)
        album = (*key, event.media_group_id) if event.media_group_id is not None else None
        if album is not None:
            if album in self._albums:
                self._albums[album].append(event)
                return None
            # Before waiting for the turn, so the rest join this message rather than start an album of their own.
            self._albums[album] = [event]
        async with self._turns[key]:
            if album is None:
                data["messages"] = [event]
            else:
                await asyncio.sleep(self.wait)
                data["messages"] = sorted(self._albums.pop(album), key=lambda m: m.message_id)
            return await handler(event, data)


async def greet(message: Message) -> None:
    await message.answer(GREETING)


def build_dispatcher(
    desk: AdsDesk,
    group_id: int,
    session_maker: async_sessionmaker[AsyncSession],
    *,
    album_wait: float = ALBUM_WAIT,
) -> Dispatcher:
    async def from_person(_message: Message, messages: list[Message]) -> None:
        await desk.from_person(messages)

    async def from_staff(_message: Message, messages: list[Message]) -> None:
        await desk.from_staff(messages)

    router = Router(name="ads")
    private = F.chat.type == "private"
    router.message.register(greet, private, CommandStart())
    router.message.register(from_person, private, F.content_type.in_(COPYABLE))
    # The General topic is staff's own: only a person's topic is a conversation.
    router.message.register(
        from_staff,
        F.chat.id == group_id,
        F.is_topic_message,
        F.content_type.in_(COPYABLE),
    )

    dp = Dispatcher()
    dp.update.outer_middleware(AudienceMiddleware(session_maker, Touchpoint.CONTACT_BOT))
    dp.message.outer_middleware(Conversations(album_wait))
    dp.include_router(router)
    dp.startup.register(partial(check_group, group_id=group_id))
    dp.startup.register(publish_profile)
    return dp


async def publish_profile(bot: Bot) -> None:
    """Write the desk's name and descriptions to Telegram, as `profile.py` does for the main bot.

    Compared first, since every deploy restarts the bot and setMyName is
    rate-limited for hours. Each step stands alone and is only logged, whatever
    it raised: an HTML error page from Telegram is not a TelegramAPIError, and
    a startup handler that raises stops the desk from polling.
    """
    name = settings.ads_bot.name

    async def description() -> None:
        if (await bot.get_my_description()).description != DESCRIPTION:
            await bot.set_my_description(description=DESCRIPTION)

    async def short_description() -> None:
        if (await bot.get_my_short_description()).short_description != SHORT_DESCRIPTION:
            await bot.set_my_short_description(short_description=SHORT_DESCRIPTION)

    async def display_name() -> None:
        if (await bot.get_my_name()).name != name:
            await bot.set_my_name(name=name)

    for step, run in (
        ("description", description),
        ("short_description", short_description),
        ("name", display_name),
    ):
        try:
            await run()
        except Exception as e:
            logger.warning("ads_profile_step_failed", step=step, error=str(e))


async def check_group(bot: Bot, group_id: int) -> None:
    """Say in the log if the desk cannot open topics, rather than at the first person who writes."""
    try:
        chat = await bot.get_chat(group_id)
        member = await bot.get_chat_member(group_id, bot.id)
    except Exception as e:
        # Anything, as in `publish_profile`: this is a startup handler.
        logger.warning("ads_group_unreachable", error=str(e))
        return
    if not chat.is_forum:
        logger.warning("ads_group_not_a_forum")
    if not (isinstance(member, ChatMemberAdministrator) and member.can_manage_topics):
        logger.warning("ads_bot_cannot_manage_topics")


def build_ads_bot(session_maker: async_sessionmaker[AsyncSession]) -> tuple[Bot, Dispatcher] | None:
    """The desk's bot and dispatcher, or None when it is not configured."""
    config = settings.ads_bot
    if not config.token:
        return None
    if not config.group_id:
        logger.warning("ads_bot_without_group")
        return None
    if not GROUP_ID.fullmatch(config.group_id.strip()):
        # Not the value: what was pasted there might be anything.
        logger.error("ads_group_malformed")
        return None
    group_id = int(config.group_id)
    if config.token == settings.telegram.token or config.token in settings.telegram.retired_tokens:
        # A second poller on one token takes turns with the first for its updates.
        logger.warning("ads_token_is_moderators")
        return None
    try:
        bot = Bot(token=config.token)
    except TokenValidationError:
        # Never the token itself: it is a secret.
        logger.error("ads_token_malformed")
        return None
    return bot, build_dispatcher(AdsDesk(bot, session_maker, group_id), group_id, session_maker)
