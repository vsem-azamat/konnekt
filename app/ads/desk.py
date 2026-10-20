"""The ads contact desk: one forum topic of the staff group per person.

Messages are copied both ways rather than forwarded, so that nothing depends on
the sender's forward privacy and staff answer as the bot, not as themselves.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import AdsTopic

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message, User
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger("ads_desk")

NOTE_PREFIX = "//"
NOT_PASSED_ON = "Не получилось передать сообщение, попробуйте чуть позже"
# Seconds.
MAX_RETRY_AFTER = 30
# Telegram's limit on a topic name.
TOPIC_NAME_LIMIT = 128


def topic_name(person: User) -> str:
    name = f"{person.full_name} @{person.username}" if person.username else person.full_name
    return name[:TOPIC_NAME_LIMIT]


def card(person: User) -> str:
    return "\n".join(
        [
            "Новое обращение",
            f"Имя: {person.full_name}",
            f"Username: @{person.username}" if person.username else "Username: —",
            f"ID: {person.id}",
            f"Язык: {person.language_code or '—'}",
        ]
    )


def _topic_is_gone(error: TelegramAPIError | None) -> bool:
    if not isinstance(error, TelegramBadRequest):
        return False
    text = error.message.lower()
    return any(sign in text for sign in ("thread not found", "topic_deleted", "topic_id_invalid"))


class AdsDesk:
    """Relays a person's messages into their topic and staff's answers back.

    A person's messages go through one lock, so that two first messages
    arriving together do not open two topics. Their order is kept before they
    get here (`Conversations`).
    """

    def __init__(self, bot: Bot, session_maker: async_sessionmaker[AsyncSession], group_id: int) -> None:
        self.bot = bot
        self.session_maker = session_maker
        self.group_id = group_id
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def from_person(self, messages: list[Message]) -> None:
        """Copy a private message, or an album, into the person's topic, opening one if needed."""
        person = messages[0].from_user
        if person is None:
            return
        async with self._locks[person.id]:
            try:
                thread = await self._thread_of(person.id)
                if thread is None:
                    thread = await self._open_topic(person)
                error = await self._copy(self.group_id, messages, thread)
                if _topic_is_gone(error):
                    # Staff deleted the topic; the conversation starts over in a new one.
                    thread = await self._open_topic(person)
                    error = await self._copy(self.group_id, messages, thread)
            except TelegramAPIError as e:
                # No topic to tell staff in, so the person is told instead.
                logger.error("ads_topic_not_opened", user_id=person.id, error=e.message)
                try:
                    await self.bot.send_message(chat_id=person.id, text=NOT_PASSED_ON)
                except TelegramAPIError as told:
                    logger.warning("ads_person_not_told", user_id=person.id, error=told.message)
                return
            if error is not None:
                await self._notice(thread, f"Сообщение не скопировано: {error.message}")

    async def from_staff(self, messages: list[Message]) -> None:
        """Copy a staff message in a person's topic to that person, unless it is a note."""
        first = messages[0]
        thread = first.message_thread_id
        if thread is None or any((m.text or m.caption or "").startswith(NOTE_PREFIX) for m in messages):
            return
        person_id = await self._person_in(thread)
        if person_id is None:
            return
        error = await self._copy(person_id, messages)
        if error is not None:
            reason = "пользователь заблокировал бота" if isinstance(error, TelegramForbiddenError) else error.message
            await self._notice(thread, f"Не доставлено: {reason}", reply_to=first.message_id)

    async def _copy(self, chat_id: int, messages: list[Message], thread: int | None = None) -> TelegramAPIError | None:
        """Copy messages, an album whole, retrying once when Telegram asks to wait; the error if it failed."""
        source = messages[0].chat.id
        for attempt in (1, 2):
            try:
                if len(messages) == 1:
                    await self.bot.copy_message(
                        chat_id=chat_id,
                        from_chat_id=source,
                        message_id=messages[0].message_id,
                        message_thread_id=thread,
                    )
                else:
                    await self.bot.copy_messages(
                        chat_id=chat_id,
                        from_chat_id=source,
                        message_ids=[m.message_id for m in messages],
                        message_thread_id=thread,
                    )
            except TelegramRetryAfter as e:
                # Waiting holds up the rest of the conversation, so only a short wait is waited out.
                if attempt == 2 or e.retry_after > MAX_RETRY_AFTER:
                    return e
                await asyncio.sleep(e.retry_after)
            except TelegramAPIError as e:
                return e
            else:
                return None
        return None

    async def _notice(self, thread: int, text: str, reply_to: int | None = None) -> None:
        """Tell staff in the topic; a notice that cannot be sent is only logged."""
        try:
            await self.bot.send_message(
                chat_id=self.group_id, message_thread_id=thread, reply_to_message_id=reply_to, text=text
            )
        except TelegramAPIError as e:
            logger.warning("ads_notice_failed", thread_id=thread, error=e.message)

    async def _open_topic(self, person: User) -> int:
        topic = await self.bot.create_forum_topic(chat_id=self.group_id, name=topic_name(person))
        thread = topic.message_thread_id
        # Stored before anything else can fail: a topic nobody remembers is
        # opened again by the next message, and staff see two.
        async with self.session_maker() as session:
            await session.merge(AdsTopic(group_id=self.group_id, user_id=person.id, thread_id=thread))
            await session.commit()
        logger.info("ads_topic_opened", user_id=person.id, thread_id=thread)
        try:
            await self.bot.send_message(chat_id=self.group_id, message_thread_id=thread, text=card(person))
        except TelegramAPIError as e:
            logger.warning("ads_card_failed", thread_id=thread, error=e.message)
        return thread

    async def _thread_of(self, person_id: int) -> int | None:
        async with self.session_maker() as session:
            return await session.scalar(
                select(AdsTopic.thread_id).where(AdsTopic.group_id == self.group_id, AdsTopic.user_id == person_id)
            )

    async def _person_in(self, thread: int) -> int | None:
        async with self.session_maker() as session:
            return await session.scalar(
                select(AdsTopic.user_id).where(AdsTopic.group_id == self.group_id, AdsTopic.thread_id == thread)
            )
