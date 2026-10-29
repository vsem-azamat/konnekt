"""The faces the console shows: a chat's photo and a person's.

Both are for an admin only. A chat's comes from what the bot already keeps, for
any chat, listed or not. A person's is asked of Telegram the first time the
console shows them, then kept: a page of fifty authors must not be fifty calls
on every load, and "no photo" is an answer worth keeping too.
"""

from __future__ import annotations

import datetime
import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from app.core.time import utc_now
from app.db.models import Chat, ChatAvatar, UserPhoto
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio

JPEG = b"\xff\xd8\xff\xe0" + b"face" * 20
PERSON = 5001
CHAT = -1001370017010


def _size(width: int, unique: str) -> MagicMock:
    return MagicMock(file_id=f"file-{width}", file_unique_id=unique, width=width, height=width)


def _bot(*, photos: list | None = None) -> MagicMock:
    """A bot whose person has one photo in three sizes, unless told otherwise."""
    bot = MagicMock()
    sizes = [_size(160, "uniq-160"), _size(320, "uniq-320"), _size(640, "uniq-640")]
    bot.get_user_profile_photos = AsyncMock(return_value=MagicMock(photos=[sizes] if photos is None else photos))
    bot.download = AsyncMock(return_value=io.BytesIO(JPEG))
    return bot


@pytest.fixture
def client_factory(db_session_maker):
    from app.webapi.deps import get_publish_bot, get_session

    holder: dict[str, MagicMock] = {"bot": _bot()}

    async def _override_session():
        async with db_session_maker() as s:
            yield s

    async def _override_bot():
        return holder["bot"]

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_publish_bot] = _override_bot
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make, holder
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_publish_bot, None)


class TestAChatsPhoto:
    async def test_any_chat_the_bot_keeps_a_photo_for_has_one_here(self, client_factory, db_session_maker) -> None:
        make, _ = client_factory
        async with db_session_maker() as s:
            # Not listed and without a link: the public address would refuse it.
            s.add(Chat(id=CHAT, title="ČVUT FIT", resource_status=Chat.STATUS_DISCOVERED))
            await s.flush()
            s.add(ChatAvatar(chat_id=CHAT, unique_id="AQAD", content=JPEG))
            await s.commit()

        async with make() as client:
            resp = await client.get(f"/api/chats/{CHAT}/photo")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content == JPEG
        assert resp.headers["cache-control"].startswith("private")

    async def test_a_chat_without_one_is_not_found(self, client_factory, db_session_maker) -> None:
        make, _ = client_factory
        async with db_session_maker() as s:
            s.add(Chat(id=CHAT, title="ČVUT FIT"))
            await s.commit()

        async with make() as client:
            resp = await client.get(f"/api/chats/{CHAT}/photo")

        assert resp.status_code == 404


class TestAPersonsPhoto:
    async def test_the_first_look_asks_telegram_and_keeps_the_small_size(
        self, client_factory, db_session_maker
    ) -> None:
        make, holder = client_factory

        async with make() as client:
            resp = await client.get(f"/api/users/{PERSON}/photo")

        assert resp.status_code == 200
        assert resp.content == JPEG
        holder["bot"].download.assert_awaited_once_with("file-160")
        async with db_session_maker() as s:
            kept = await s.get(UserPhoto, PERSON)
        assert kept is not None
        assert kept.unique_id == "uniq-160"

    async def test_the_next_look_does_not_ask_again(self, client_factory) -> None:
        make, holder = client_factory

        async with make() as client:
            await client.get(f"/api/users/{PERSON}/photo")
            resp = await client.get(f"/api/users/{PERSON}/photo")

        assert resp.status_code == 200
        assert holder["bot"].get_user_profile_photos.await_count == 1

    async def test_no_photo_is_kept_as_an_answer_too(self, client_factory) -> None:
        """None set, or hidden by their privacy settings: Telegram shows the bot nothing."""
        make, holder = client_factory
        holder["bot"] = _bot(photos=[])

        async with make() as client:
            first = await client.get(f"/api/users/{PERSON}/photo")
            second = await client.get(f"/api/users/{PERSON}/photo")

        assert first.status_code == second.status_code == 404
        assert holder["bot"].get_user_profile_photos.await_count == 1

    async def test_a_refusal_is_not_kept_so_the_next_look_asks_again(self, client_factory) -> None:
        make, holder = client_factory
        holder["bot"].get_user_profile_photos = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="Bad Request: user not found")
        )

        async with make() as client:
            first = await client.get(f"/api/users/{PERSON}/photo")
            second = await client.get(f"/api/users/{PERSON}/photo")

        assert first.status_code == second.status_code == 404
        assert holder["bot"].get_user_profile_photos.await_count == 2
        # Nor by the browser: an hour of letters for a passing flood wait.
        assert first.headers["cache-control"] == "no-store"

    async def test_no_photo_may_be_remembered_by_the_browser(self, client_factory) -> None:
        make, holder = client_factory
        holder["bot"] = _bot(photos=[])

        async with make() as client:
            resp = await client.get(f"/api/users/{PERSON}/photo")

        assert resp.headers["cache-control"].startswith("private, max-age=")

    async def test_an_old_answer_is_asked_again(self, client_factory, db_session_maker) -> None:
        make, holder = client_factory
        async with db_session_maker() as s:
            s.add(
                UserPhoto(
                    user_id=PERSON,
                    unique_id=None,
                    content=None,
                    fetched_at=utc_now() - datetime.timedelta(days=30),
                )
            )
            await s.commit()

        async with make() as client:
            resp = await client.get(f"/api/users/{PERSON}/photo")

        assert resp.status_code == 200
        assert holder["bot"].get_user_profile_photos.await_count == 1

    async def test_a_photo_that_is_not_a_small_jpeg_is_not_served(self, client_factory) -> None:
        make, holder = client_factory
        holder["bot"].download = AsyncMock(return_value=io.BytesIO(b"<svg>not a photo</svg>"))

        async with make() as client:
            resp = await client.get(f"/api/users/{PERSON}/photo")

        assert resp.status_code == 404
        assert resp.headers["cache-control"] == "no-store"


class TestOnlyForAnAdmin:
    @pytest.mark.parametrize("path", [f"/api/users/{PERSON}/photo", f"/api/chats/{CHAT}/photo"])
    async def test_without_a_session_there_is_no_face(self, client_factory, path: str) -> None:
        from app.webapi.deps import require_super_admin

        make, holder = client_factory
        app.dependency_overrides.pop(require_super_admin, None)

        async with make() as client:
            resp = await client.get(path)

        assert resp.status_code == 401
        holder["bot"].get_user_profile_photos.assert_not_awaited()
