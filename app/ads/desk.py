"""The ads contact desk: one forum topic of the staff group per person.

Messages are copied both ways rather than forwarded, so that nothing depends on
the sender's forward privacy and staff answer as the bot, not as themselves.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import AdsTopic

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message, User
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger("ads_desk")

NOTE_PREFIX = "//"
# Telegram's limit on a topic name.
TOPIC_NAME_LIMIT = 128


def topic_name(person: User) -> str:
    name = f"{person.full_name} @{person.username}" if person.username else person.full_name
    return name[:TOPIC_NAME_LIMIT]


def card(person: User) -> str:
    return "\n".join(
        [
            "Новый собеседник",
            f"Имя: {person.full_name}",
            f"Username: @{person.username}" if person.username else "Username: —",
            f"ID: {person.id}",
            f"Язык: {person.language_code or '—'}",
        ]
    )


def _topic_is_gone(error: TelegramBadRequest) -> bool:
    text = error.message.lower()
    return "thread not found" in text or "topic_deleted" in text


class AdsDesk:
    """Relays a person's messages into their topic and staff's answers back.

    Each person's messages and answers go through one lock: two first messages
    arriving together must not open two topics, and copies must keep the order
    they were written in.
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
            thread = await self._thread_of(person.id)
            if thread is None:
                thread = await self._open_topic(person)
            try:
                await self._copy_into(thread, messages)
            except TelegramBadRequest as e:
                if not _topic_is_gone(e):
                    raise
                # Staff deleted the topic; the conversation starts over in a new one.
                await self._copy_into(await self._open_topic(person), messages)

    async def from_staff(self, messages: list[Message]) -> None:
        """Copy a staff message in a person's topic to that person, unless it is a note."""
        first = messages[0]
        thread = first.message_thread_id
        if thread is None or any((m.text or m.caption or "").startswith(NOTE_PREFIX) for m in messages):
            return
        person_id = await self._person_in(thread)
        if person_id is None:
            return
        async with self._locks[person_id]:
            try:
                if len(messages) == 1:
                    await self.bot.copy_message(
                        chat_id=person_id, from_chat_id=self.group_id, message_id=first.message_id
                    )
                else:
                    await self.bot.copy_messages(
                        chat_id=person_id, from_chat_id=self.group_id, message_ids=[m.message_id for m in messages]
                    )
            except (TelegramForbiddenError, TelegramBadRequest) as e:
                reason = "пользователь заблокировал бота" if isinstance(e, TelegramForbiddenError) else e.message
                await self.bot.send_message(
                    chat_id=self.group_id,
                    message_thread_id=thread,
                    reply_to_message_id=first.message_id,
                    text=f"Не доставлено: {reason}",
                )

    async def _copy_into(self, thread: int, messages: list[Message]) -> None:
        source = messages[0].chat.id
        if len(messages) == 1:
            await self.bot.copy_message(
                chat_id=self.group_id, from_chat_id=source, message_id=messages[0].message_id, message_thread_id=thread
            )
        else:
            await self.bot.copy_messages(
                chat_id=self.group_id,
                from_chat_id=source,
                message_ids=[m.message_id for m in messages],
                message_thread_id=thread,
            )

    async def _open_topic(self, person: User) -> int:
        topic = await self.bot.create_forum_topic(chat_id=self.group_id, name=topic_name(person))
        thread = topic.message_thread_id
        await self.bot.send_message(chat_id=self.group_id, message_thread_id=thread, text=card(person))
        async with self.session_maker() as session:
            await session.merge(AdsTopic(group_id=self.group_id, user_id=person.id, thread_id=thread))
            await session.commit()
        logger.info("ads_topic_opened", user_id=person.id, thread_id=thread)
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
