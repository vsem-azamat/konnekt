"""A chat's photo, as a stranger gets it.

The catalog points at an address, never at Telegram: a file id is useless to a
browser and the only URL Telegram offers contains the bot token. The address is
made from `file_unique_id`, so it changes when the photo does and can be cached
for good. What is pinned here is that, and that the address leaks nothing that
the catalog row would not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from app.core.config import settings
from app.db.models import Chat, ChatAvatar
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

FIT = -1001370017010
JPEG = b"\xff\xd8\xff\xe0" + b"photo" * 20


@pytest.fixture
def client_factory(db_session_maker: async_sessionmaker[AsyncSession]):
    from app.webapi.deps import get_session

    async def _override_get_session():
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    orig_admins = list(settings.admin.super_admins)
    settings.admin.super_admins = [1]
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make
    app.dependency_overrides.pop(get_session, None)
    settings.admin.super_admins = orig_admins


async def _seed(
    session_maker,
    *,
    status: str = Chat.STATUS_APPROVED,
    link: str | None = "https://t.me/cvut_fit",
    unique: str | None = "AQAD-uniq",
) -> None:
    async with session_maker() as session:
        session.add(Chat(id=FIT, title="ČVUT FIT", resource_status=status, public_link=link))
        await session.flush()
        if unique:
            session.add(ChatAvatar(chat_id=FIT, unique_id=unique, content=JPEG))
        await session.commit()


class TestTheCatalogPointsAtTheAddress:
    async def test_a_chat_with_a_photo_carries_its_address(self, client_factory, db_session_maker) -> None:
        await _seed(db_session_maker)

        async with client_factory() as client:
            row = (await client.get("/api/public/catalog")).json()[0]

        assert row["avatar"] == "/api/public/avatars/AQAD-uniq"

    async def test_a_chat_without_one_says_null_so_the_app_keeps_its_letters(
        self, client_factory, db_session_maker
    ) -> None:
        await _seed(db_session_maker, unique=None)

        async with client_factory() as client:
            row = (await client.get("/api/public/catalog")).json()[0]

        assert row["avatar"] is None

    async def test_no_telegram_file_id_or_token_is_in_the_answer(self, client_factory, db_session_maker) -> None:
        await _seed(db_session_maker)
        async with db_session_maker() as session:
            chat = await session.get(Chat, FIT)
            assert chat is not None
            chat.photo_file_id = "BQACAgIAAx-secret-file-id"
            await session.commit()

        async with client_factory() as client:
            body = (await client.get("/api/public/catalog")).text

        assert "secret-file-id" not in body
        assert "api.telegram.org" not in body
        assert settings.telegram.token not in body


class TestServingIt:
    async def test_the_picture_is_served_to_be_cached_for_good(self, client_factory, db_session_maker) -> None:
        await _seed(db_session_maker)

        async with client_factory() as client:
            resp = await client.get("/api/public/avatars/AQAD-uniq")

        assert resp.status_code == 200
        assert resp.content == JPEG
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert resp.headers["etag"] == '"AQAD-uniq"'
        assert resp.headers["x-content-type-options"] == "nosniff"

    async def test_a_browser_that_has_it_is_told_so(self, client_factory, db_session_maker) -> None:
        await _seed(db_session_maker)

        async with client_factory() as client:
            resp = await client.get("/api/public/avatars/AQAD-uniq", headers={"If-None-Match": '"AQAD-uniq"'})

        assert resp.status_code == 304
        assert resp.content == b""

    async def test_an_address_from_before_the_photo_changed_is_gone(self, client_factory, db_session_maker) -> None:
        await _seed(db_session_maker)
        async with db_session_maker() as session:
            avatar = await session.get(ChatAvatar, FIT)
            assert avatar is not None
            avatar.unique_id = "AQAD-new"
            await session.commit()

        async with client_factory() as client:
            old = await client.get("/api/public/avatars/AQAD-uniq")
            new = await client.get("/api/public/avatars/AQAD-new")

        assert old.status_code == 404
        assert new.status_code == 200

    async def test_a_missing_picture_is_not_remembered_for_a_year(self, client_factory) -> None:
        async with client_factory() as client:
            resp = await client.get("/api/public/avatars/nothing")

        assert resp.status_code == 404
        assert "immutable" not in resp.headers.get("cache-control", "")

    @pytest.mark.parametrize(
        ("status", "link"),
        [
            (Chat.STATUS_DISCOVERED, "https://t.me/cvut_fit"),
            (Chat.STATUS_DISABLED, "https://t.me/cvut_fit"),
            (Chat.STATUS_APPROVED, None),
        ],
        ids=["undecided", "taken-down", "no-link"],
    )
    async def test_a_chat_that_is_not_listed_has_no_public_picture(
        self, client_factory, db_session_maker, status, link
    ) -> None:
        """The catalog is the decision to publish; its pictures follow the same decision."""
        await _seed(db_session_maker, status=status, link=link)

        async with client_factory() as client:
            resp = await client.get("/api/public/avatars/AQAD-uniq")

        assert resp.status_code == 404

    @pytest.mark.parametrize("bad", ["a b", "a%00b", "x" * 65, "é"])
    async def test_an_address_that_cannot_be_an_id_is_refused_before_the_database(self, client_factory, bad) -> None:
        async with client_factory() as client:
            resp = await client.get(f"/api/public/avatars/{bad}")

        assert resp.status_code in {404, 422}
