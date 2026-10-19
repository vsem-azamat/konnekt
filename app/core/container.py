"""Application-wide singleton holder.

Two long-lived objects the bot process wires once at startup: the session maker
and the bot. Not a DI container — the generic register/resolve API it once had
never had a caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class Container:
    """Holds the long-lived singletons wired at bot startup."""

    def __init__(self) -> None:
        self._session_maker: async_sessionmaker[AsyncSession] | None = None
        self._bot: Bot | None = None

    def set_session_maker(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self._session_maker = session_maker

    def get_session_maker(self) -> async_sessionmaker[AsyncSession]:
        if not self._session_maker:
            raise ValueError("Session maker not set")
        return self._session_maker

    def set_bot(self, bot: Bot) -> None:
        self._bot = bot

    def try_get_bot(self) -> Bot | None:
        return self._bot


container = Container()


def setup_container(session_maker: async_sessionmaker[AsyncSession], bot: Bot) -> None:
    container.set_session_maker(session_maker)
    container.set_bot(bot)
