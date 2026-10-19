"""Shared E2E test fixtures.

db_engine and db_session_maker are inherited from root conftest.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest_asyncio
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from tests.fake_telegram import FakeTelegramServer

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# The approved group the production dispatcher fixture seeds.
APPROVED_CHAT_ID = -1001234567890


@pytest_asyncio.fixture()
async def fake_tg():
    """Start fake Telegram server."""
    async with FakeTelegramServer() as server:
        yield server


@pytest_asyncio.fixture()
async def bot(fake_tg: FakeTelegramServer):
    """A bot whose every call lands on the fake server."""
    api = TelegramAPIServer(
        base=f"{fake_tg.base_url}/bot{{token}}/{{method}}",
        file=f"{fake_tg.base_url}/file/bot{{token}}/{{path}}",
        is_local=True,
    )
    b = Bot(
        token="123456:ABC-DEF1234567890",
        default=DefaultBotProperties(parse_mode="HTML"),
        session=AiohttpSession(api=api),
    )
    yield b
    await b.session.close()


@pytest_asyncio.fixture()
async def production_dispatcher(bot: Bot, db_session_maker: async_sessionmaker[AsyncSession]):
    """The dispatcher `build_dispatcher` gives production, over one approved group."""
    from app.db.models import Chat as DbChat
    from app.presentation.telegram.bot import build_dispatcher
    from app.presentation.telegram.handlers import router
    from app.presentation.telegram.middlewares.black_list import invalidate_blacklist_cache

    def restore_parents() -> None:
        # The handler routers are module singletons, and another test re-parents
        # them under a router of its own; put them back under ours.
        router._parent_router = None
        for sub in router.sub_routers:
            sub._parent_router = router

    restore_parents()
    invalidate_blacklist_cache()
    async with db_session_maker() as session:
        session.add(DbChat(id=APPROVED_CHAT_ID, title="Approved", resource_status=DbChat.STATUS_APPROVED))
        await session.commit()
    yield build_dispatcher(bot, db_session_maker)
    restore_parents()
    invalidate_blacklist_cache()
