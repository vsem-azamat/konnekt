from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus
from aiogram.types import TelegramObject, Update

from app.audience import record
from app.audience.record import Person
from app.core.logging import get_logger
from app.core.time import utc_now

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.enums import Touchpoint

logger = get_logger("middleware.audience")


class AudienceMiddleware(BaseMiddleware):
    """Record each private use of a bot, and each block or unblock of it, in the audience.

    An outer update middleware with a session of its own, so it sees every
    update whichever handler takes it, works on the dispatchers that have no
    database middleware, and cannot leave a failed transaction behind for the
    handler. Recording is never worth an unanswered person: failures are only
    logged, without anything that names them.
    """

    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        touchpoint: Touchpoint,
        *,
        reach: bool = True,
    ) -> None:
        super().__init__()
        self.session_maker = session_maker
        self.touchpoint = touchpoint
        # A retired bot is somewhere people came, but not a way to write to them.
        self.reach = touchpoint if reach else None

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Update):
            try:
                await self._record(event)
            except Exception as err:
                logger.error("audience_not_recorded", touchpoint=self.touchpoint, error=type(err).__name__)
        return await handler(event, data)

    async def _record(self, update: Update) -> None:
        at = utc_now()
        if (change := update.my_chat_member) is not None:
            if change.chat.type != "private" or self.reach is None:
                return
            async with self.session_maker() as db:
                if change.new_chat_member.status == ChatMemberStatus.KICKED:
                    await record.blocked(db, change.from_user.id, self.reach, at=at)
                else:
                    await record.seen(
                        db, Person.from_user(change.from_user), self.touchpoint, at=at, started=self.reach
                    )
                await db.commit()
            return

        message = update.message
        pressed = update.callback_query
        chat = message.chat if message else pressed.message.chat if pressed and pressed.message else None
        user = message.from_user if message else pressed.from_user if pressed else None
        if chat is None or chat.type != "private" or user is None:
            return
        source = None
        if message and message.text and message.text.startswith("/start "):
            source = message.text.removeprefix("/start ").strip()[:64] or None
        async with self.session_maker() as db:
            await record.seen(db, Person.from_user(user), self.touchpoint, at=at, source=source, started=self.reach)
            await db.commit()
