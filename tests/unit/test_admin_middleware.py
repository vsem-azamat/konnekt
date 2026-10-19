"""Who gets past the two guards.

The interesting case is the one the old flat list could not express: a moderator
of one chat, standing in another, being told no. Everything else here exists so
that case cannot be made to pass by accident.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import types
from app.db.models import Chat
from app.db.repositories import AdminRepository
from app.presentation.telegram.middlewares.admin import (
    AdminMiddleware,
    SuperAdminMiddleware,
    you_are_not_admin,
)

pytestmark = pytest.mark.unit

SUPER = 111
OTHER_SUPER = 222
MODERATOR = 555
STRANGER = 999

HOME = -1001370017010  # ČVUT FIT
ELSEWHERE = -1001497722835  # Strahov


def _message(user_id: int, chat_id: int | None = HOME) -> MagicMock:
    msg = MagicMock(spec=types.Message)
    msg.from_user = MagicMock(spec=types.User)
    msg.from_user.id = user_id
    msg.chat = MagicMock(spec=types.Chat)
    msg.chat.id = chat_id
    msg.answer = AsyncMock(return_value=MagicMock(spec=types.Message))
    msg.answer.return_value.delete = AsyncMock()
    msg.delete = AsyncMock()
    msg.sender_chat = None
    return msg


def _callback(user_id: int, chat_id: int | None = HOME) -> MagicMock:
    cb = MagicMock(spec=types.CallbackQuery)
    cb.from_user = MagicMock(spec=types.User)
    cb.from_user.id = user_id
    cb.message = _message(user_id, chat_id) if chat_id is not None else None
    return cb


def _supers(*ids: int):
    """Pin the configured super administrators for one test."""
    patched = patch("app.presentation.telegram.middlewares.admin.settings")
    mock = patched.start()
    mock.admin.super_admins = list(ids)
    return patched


async def _seed(session, *, moderates: list[int]) -> dict:
    for chat_id in {HOME, ELSEWHERE}:
        session.add(Chat(id=chat_id, title=str(chat_id), resource_status=Chat.STATUS_APPROVED))
    await session.commit()

    repo = AdminRepository(session)
    for chat_id in moderates:
        await repo.grant(MODERATOR, chat_id, granted_by=SUPER)
    return {"admin_repo": repo, "db": session}


class TestSuperAdminMiddleware:
    async def test_a_super_admin_gets_through(self) -> None:
        handler, msg = AsyncMock(), _message(SUPER)
        patched = _supers(SUPER, OTHER_SUPER)
        try:
            await SuperAdminMiddleware()(handler, msg, {})
        finally:
            patched.stop()

        handler.assert_awaited_once_with(msg, {})

    async def test_both_configured_accounts_get_through(self) -> None:
        """Two accounts, not just the first one listed."""
        handler, msg = AsyncMock(), _message(OTHER_SUPER)
        patched = _supers(SUPER, OTHER_SUPER)
        try:
            await SuperAdminMiddleware()(handler, msg, {})
        finally:
            patched.stop()

        handler.assert_awaited_once()

    async def test_a_chat_moderator_is_not_a_super_admin(self, session) -> None:
        """The blacklist reaches every chat, so moderating one is not enough."""
        data = await _seed(session, moderates=[HOME])
        handler, msg = AsyncMock(), _message(MODERATOR)
        patched = _supers(SUPER)
        try:
            result = await SuperAdminMiddleware()(handler, msg, data)
        finally:
            patched.stop()

        handler.assert_not_awaited()
        assert result is None

    async def test_a_callback_is_judged_the_same_way(self) -> None:
        handler, cb = AsyncMock(), _callback(SUPER)
        patched = _supers(SUPER)
        try:
            await SuperAdminMiddleware()(handler, cb, {})
        finally:
            patched.stop()

        handler.assert_awaited_once()


class TestAdminMiddleware:
    async def test_a_moderator_acts_in_their_own_chat(self, session) -> None:
        data = await _seed(session, moderates=[HOME])
        handler, msg = AsyncMock(), _message(MODERATOR, HOME)
        patched = _supers(SUPER)
        try:
            await AdminMiddleware()(handler, msg, data)
        finally:
            patched.stop()

        handler.assert_awaited_once_with(msg, data)

    async def test_a_moderator_is_refused_in_a_chat_they_do_not_moderate(self, session) -> None:
        """The reason this table exists. One chat's moderator is not the other's."""
        data = await _seed(session, moderates=[HOME])
        handler, msg = AsyncMock(), _message(MODERATOR, ELSEWHERE)
        patched = _supers(SUPER)
        try:
            result = await AdminMiddleware()(handler, msg, data)
        finally:
            patched.stop()

        handler.assert_not_awaited()
        assert result is None

    async def test_a_super_admin_acts_anywhere(self, session) -> None:
        data = await _seed(session, moderates=[])
        handler, msg = AsyncMock(), _message(SUPER, ELSEWHERE)
        patched = _supers(SUPER)
        try:
            await AdminMiddleware()(handler, msg, data)
        finally:
            patched.stop()

        handler.assert_awaited_once()

    async def test_a_stranger_is_refused(self, session) -> None:
        data = await _seed(session, moderates=[HOME])
        handler, msg = AsyncMock(), _message(STRANGER, HOME)
        patched = _supers(SUPER)
        try:
            result = await AdminMiddleware()(handler, msg, data)
        finally:
            patched.stop()

        handler.assert_not_awaited()
        assert result is None

    async def test_a_revoked_moderator_is_refused_at_once(self, session) -> None:
        """No cache to go stale: the answer is read fresh on every command."""
        data = await _seed(session, moderates=[HOME])
        repo: AdminRepository = data["admin_repo"]
        patched = _supers(SUPER)
        try:
            handler, msg = AsyncMock(), _message(MODERATOR, HOME)
            await AdminMiddleware()(handler, msg, data)
            handler.assert_awaited_once()

            await repo.revoke(MODERATOR, HOME)

            handler, msg = AsyncMock(), _message(MODERATOR, HOME)
            await AdminMiddleware()(handler, msg, data)
        finally:
            patched.stop()

        handler.assert_not_awaited()

    async def test_a_callback_is_scoped_by_its_message(self, session) -> None:
        data = await _seed(session, moderates=[HOME])
        handler, cb = AsyncMock(), _callback(MODERATOR, ELSEWHERE)
        patched = _supers(SUPER)
        try:
            result = await AdminMiddleware()(handler, cb, data)
        finally:
            patched.stop()

        handler.assert_not_awaited()
        assert result is None

    async def test_a_moderator_gets_nothing_where_there_is_no_chat(self, session) -> None:
        """A scoped right cannot be exercised somewhere the scope does not reach."""
        data = await _seed(session, moderates=[HOME])
        handler, cb = AsyncMock(), _callback(MODERATOR, chat_id=None)
        patched = _supers(SUPER)
        try:
            result = await AdminMiddleware()(handler, cb, data)
        finally:
            patched.stop()

        handler.assert_not_awaited()
        assert result is None


class TestTheRefusal:
    async def test_it_speaks_russian_and_clears_up_after_itself(self) -> None:
        """Both messages go: a refusal left on screen is noise plus an invitation."""
        msg = _message(STRANGER)

        with patch("app.presentation.telegram.middlewares.admin.asyncio.sleep", new_callable=AsyncMock):
            await you_are_not_admin(msg)

        said = msg.answer.await_args.args[0]
        assert said.isascii() is False
        assert "Admin" not in said
        msg.delete.assert_awaited_once()
        msg.answer.return_value.delete.assert_awaited_once()
