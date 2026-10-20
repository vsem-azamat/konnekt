"""@konnekt_ads_bot, the ads contact desk, polling next to the main bot.

What it does with a message is `app.ads.desk`; this is which messages reach it.
It is off unless `ADS_BOT_TOKEN` and `ADS_BOT_GROUP_ID` are both set.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ContentType
from aiogram.filters import CommandStart
from aiogram.utils.token import TokenValidationError

from app.ads.desk import AdsDesk
from app.core.config import settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from aiogram.types import Message
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger("ads_bot")

GREETING = (
    "Здравствуйте! Это команда Konnekt.\n\n"
    "Напишите здесь о рекламе в наших чатах, о сотрудничестве или задайте вопрос — мы ответим в этом чате."
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


class Albums:
    """Gathers the messages of one album, which Telegram delivers one by one.

    The first message waits for the others and hands them all on; the rest hand
    on nothing. That relies on updates being handled concurrently, which is
    aiogram's polling default.
    """

    def __init__(self, wait: float) -> None:
        self.wait = wait
        self._pending: dict[tuple[int, str], list[Message]] = {}

    async def collect(self, message: Message) -> list[Message] | None:
        if message.media_group_id is None:
            return [message]
        key = (message.chat.id, message.media_group_id)
        if key in self._pending:
            self._pending[key].append(message)
            return None
        self._pending[key] = [message]
        await asyncio.sleep(self.wait)
        return sorted(self._pending.pop(key), key=lambda m: m.message_id)


async def greet(message: Message) -> None:
    await message.answer(GREETING)


def build_dispatcher(desk: AdsDesk, group_id: int, *, album_wait: float = ALBUM_WAIT) -> Dispatcher:
    albums = Albums(album_wait)

    async def from_person(message: Message) -> None:
        if messages := await albums.collect(message):
            await desk.from_person(messages)

    async def from_staff(message: Message) -> None:
        if messages := await albums.collect(message):
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
    dp.include_router(router)
    return dp


def build_ads_bot(session_maker: async_sessionmaker[AsyncSession]) -> tuple[Bot, Dispatcher] | None:
    """The desk's bot and dispatcher, or None when it is not configured."""
    config = settings.ads_bot
    if not config.token:
        return None
    if config.group_id is None:
        logger.warning("ads_bot_without_group")
        return None
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
    return bot, build_dispatcher(AdsDesk(bot, session_maker, config.group_id), config.group_id)
