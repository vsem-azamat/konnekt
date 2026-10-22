"""Tests for PATCH /api/chats/{id} — per-chat moderation toggles."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from app.core.config import settings
from app.db.models import Chat
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client_factory(db_session_maker: async_sessionmaker[AsyncSession]):
    from app.webapi.deps import get_session

    async def _override_session():
        async with db_session_maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    settings.admin.super_admins = [1]
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make
    app.dependency_overrides.pop(get_session, None)


async def test_update_chat_toggles(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2001, title="moderated"))
        await s.commit()

    async with client_factory() as client:
        resp = await client.patch(
            "/api/chats/-2001",
            json={
                "title": "renamed",
                "is_welcome_enabled": True,
                "is_captcha_enabled": True,
                "welcome_message": "hi",
                "time_delete": 120,
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "renamed"
    assert body["is_welcome_enabled"] is True
    assert body["is_captcha_enabled"] is True

    async with db_session_maker() as s:
        ch = (await s.execute(select(Chat).where(Chat.id == -2001))).scalar_one()
        assert ch.welcome_message == "hi"
        assert ch.time_delete == 120


async def test_update_chat_404(client_factory) -> None:
    async with client_factory() as client:
        resp = await client.patch("/api/chats/99999", json={"title": "x"})
    assert resp.status_code == 404


async def test_update_chat_negative_time_delete_422(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2002, title="x"))
        await s.commit()
    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2002", json={"time_delete": -5})
    assert resp.status_code == 422


async def test_update_chat_self_parent_422(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2003, title="x"))
        await s.commit()
    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2003", json={"parent_chat_id": -2003})
    assert resp.status_code == 422


async def test_update_chat_missing_parent_422(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2005, title="x"))
        await s.commit()
    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2005", json={"parent_chat_id": -9999})
    assert resp.status_code == 422


async def test_update_chat_parent_cycle_422(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2006, title="root"))
        s.add(Chat(id=-2007, title="child", parent_chat_id=-2006))
        await s.commit()
    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2006", json={"parent_chat_id": -2007})
    assert resp.status_code == 422


async def test_a_chat_goes_only_under_a_top_level_chat(client_factory, db_session_maker) -> None:
    """Both lists group by the parent and nothing deeper: a grandchild would
    appear under neither. The console offers only top-level chats, and this
    holds for whatever else sends the change."""
    async with db_session_maker() as s:
        s.add(Chat(id=-2010, title="ČVUT"))
        s.add(Chat(id=-2011, title="ČVUT FIT", parent_chat_id=-2010))
        s.add(Chat(id=-2012, title="FIT 2026"))
        await s.commit()
    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2012", json={"parent_chat_id": -2011})
    assert resp.status_code == 409, resp.text


async def test_a_chat_others_sit_under_stays_at_the_top(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2013, title="ČVUT"))
        s.add(Chat(id=-2014, title="ČVUT FIT", parent_chat_id=-2013))
        s.add(Chat(id=-2015, title="Praha"))
        await s.commit()
    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2013", json={"parent_chat_id": -2015})
        # Taking it out from under a parent is always allowed.
        out = await client.patch("/api/chats/-2014", json={"parent_chat_id": None})
    assert resp.status_code == 409, resp.text
    assert out.status_code == 200, out.text


@pytest.mark.parametrize(
    ("sent", "stored"),
    [("cvut", "cvut"), ("  VSE ", "vse"), ("", None), (None, None)],
)
async def test_a_chat_is_tied_to_a_university_by_the_catalogs_code(
    client_factory, db_session_maker, sent, stored
) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2020, title="ČVUT", institution_code="old"))
        await s.commit()
    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2020", json={"institution_code": sent})
    assert resp.status_code == 200, resp.text
    assert resp.json()["institution_code"] == stored


async def test_a_chat_under_a_parent_takes_its_university_from_it(client_factory, db_session_maker) -> None:
    """Refused on a child, and cleared when a chat goes under a parent."""
    async with db_session_maker() as s:
        s.add(Chat(id=-2030, title="ČVUT", institution_code="cvut"))
        s.add(Chat(id=-2031, title="ČVUT FIT", parent_chat_id=-2030))
        s.add(Chat(id=-2032, title="FEL", institution_code="cvut"))
        await s.commit()
    async with client_factory() as client:
        refused = await client.patch("/api/chats/-2031", json={"institution_code": "vse"})
        moved = await client.patch("/api/chats/-2032", json={"parent_chat_id": -2030})
    assert refused.status_code == 409, refused.text
    assert moved.status_code == 200, moved.text
    assert moved.json()["institution_code"] is None


@pytest.mark.parametrize("sent", ["čvut", "cvut fit", "x" * 33, "<b>"])
async def test_a_code_that_is_not_a_code_is_refused(client_factory, db_session_maker, sent) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2021, title="ČVUT"))
        await s.commit()
    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2021", json={"institution_code": sent})
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("sent", "stored"),
    [("Praha", "Praha"), ("  Brno ", "Brno"), ("Plzen\u030c", "Plze\u0148"), ("", None), (None, None)],
)
async def test_a_chat_is_placed_in_a_city_or_in_all_of_czechia(client_factory, db_session_maker, sent, stored) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2040, title="Strahov", city="Ostrava"))
        await s.commit()
    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2040", json={"city": sent})
    assert resp.status_code == 200, resp.text
    assert resp.json()["city"] == stored


@pytest.mark.parametrize("sent", ["dorms", "university", None])
async def test_a_chat_is_filed_under_a_topic(client_factory, db_session_maker, sent) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2041, title="Strahov", topic="general"))
        await s.commit()
    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2041", json={"topic": sent})
    assert resp.status_code == 200, resp.text
    assert resp.json()["topic"] == sent


@pytest.mark.parametrize("sent", ["sport", "Dorms", ""])
async def test_a_topic_outside_the_list_is_refused(client_factory, db_session_maker, sent) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2042, title="Strahov"))
        await s.commit()
    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2042", json={"topic": sent})
    assert resp.status_code == 422


async def test_a_city_name_is_not_a_paragraph(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2043, title="Strahov"))
        await s.commit()
    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2043", json={"city": "x" * 97})
    assert resp.status_code == 422


class TestPublishingAChat:
    """Setting the public link is what puts a chat on the public page.

    It is the only field on this endpoint whose value is rendered to strangers
    rather than shown back to the admin who typed it, so it is the only one with
    a shape.
    """

    async def test_a_telegram_link_publishes(self, client_factory, db_session_maker) -> None:
        async with db_session_maker() as s:
            s.add(Chat(id=-2101, title="ČVUT FIT"))
            await s.commit()

        async with client_factory() as client:
            resp = await client.patch("/api/chats/-2101", json={"public_link": "https://t.me/cvut_fit"})

        assert resp.status_code == 200, resp.text
        assert resp.json()["public_link"] == "https://t.me/cvut_fit"

    @pytest.mark.parametrize(
        "link",
        [
            "https://t.me/+AAAAAAAAAAAAAAAA",
            "https://t.me/joinchat/AAAAAAAAAAAAAAAA",
        ],
    )
    async def test_an_invite_link_publishes(self, client_factory, db_session_maker, link: str) -> None:
        """Closed chats have no username, so an invite hash is the only way in."""
        async with db_session_maker() as s:
            s.add(Chat(id=-2102, title="closed"))
            await s.commit()

        async with client_factory() as client:
            resp = await client.patch("/api/chats/-2102", json={"public_link": link})

        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize(
        "link",
        [
            "javascript:alert(1)",
            "http://t.me/cvut_fit",
            "https://evil.example/t.me/cvut_fit",
            "https://t.me.evil.example/cvut_fit",
            "не ссылка",
        ],
    )
    async def test_anything_that_is_not_a_chat_link_is_refused(
        self, client_factory, db_session_maker, link: str
    ) -> None:
        """This value ends up in an href on a page anybody can open."""
        async with db_session_maker() as s:
            s.add(Chat(id=-2103, title="x"))
            await s.commit()

        async with client_factory() as client:
            resp = await client.patch("/api/chats/-2103", json={"public_link": link})

        assert resp.status_code == 422
        async with db_session_maker() as s:
            ch = (await s.execute(select(Chat).where(Chat.id == -2103))).scalar_one()
            assert ch.public_link is None

    async def test_clearing_the_field_takes_the_chat_down(self, client_factory, db_session_maker) -> None:
        """A form sends an empty string for a cleared input, and it must mean
        "take it down" — not "publish with a link that goes nowhere"."""
        async with db_session_maker() as s:
            s.add(Chat(id=-2104, title="listed", public_link="https://t.me/listed_chat"))
            await s.commit()

        async with client_factory() as client:
            resp = await client.patch("/api/chats/-2104", json={"public_link": "   "})

        assert resp.status_code == 200, resp.text
        assert resp.json()["public_link"] is None
        async with db_session_maker() as s:
            ch = (await s.execute(select(Chat).where(Chat.id == -2104))).scalar_one()
            assert ch.public_link is None

    async def test_a_patch_that_says_nothing_about_it_leaves_it_alone(self, client_factory, db_session_maker) -> None:
        """Renaming a chat must not quietly unpublish it."""
        async with db_session_maker() as s:
            s.add(Chat(id=-2105, title="listed", public_link="https://t.me/listed_chat"))
            await s.commit()

        async with client_factory() as client:
            resp = await client.patch("/api/chats/-2105", json={"title": "renamed"})

        assert resp.status_code == 200, resp.text
        assert resp.json()["public_link"] == "https://t.me/listed_chat"


async def test_update_chat_partial_keeps_other_fields(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2004, title="orig", welcome_message="orig-welcome"))
        await s.commit()

    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2004", json={"is_welcome_enabled": True})
    assert resp.status_code == 200, resp.text

    async with db_session_maker() as s:
        ch = (await s.execute(select(Chat).where(Chat.id == -2004))).scalar_one()
        assert ch.welcome_message == "orig-welcome"
        assert ch.title == "orig"
        assert ch.is_welcome_enabled is True


def test_the_api_and_the_database_know_the_same_topics() -> None:
    """A topic the schema accepts and the CHECK refuses would answer 500, not 422."""
    from typing import get_args

    from app.webapi.schemas import ChatTopic
    from sqlalchemy import CheckConstraint

    checks = (c for c in Chat.__table_args__ if isinstance(c, CheckConstraint))
    check = next(c for c in checks if c.name == "ck_chats_topic")
    assert get_args(ChatTopic) == Chat.TOPICS
    assert str(check.sqltext) == "topic IN ({})".format(", ".join(f"'{topic}'" for topic in Chat.TOPICS))


async def test_the_join_mode_is_set_and_shown(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        chat = Chat(id=-2101, title="x", public_link="https://t.me/public_room")
        chat.join_by_request = True
        s.add(chat)
        await s.commit()

    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2101", json={"join_mode": "open"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["join_mode"] == "open"
    assert body["join_by_request"] is True
    assert body["is_captcha_enabled"] is False


async def test_an_unknown_join_mode_is_refused(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2102, title="x"))
        await s.commit()

    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2102", json={"join_mode": "everyone"})
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("link", "left"),
    [
        # The bot's own link asked for no request without the captcha: people walked in.
        ("https://t.me/+private_invite", "open"),
        # Telegram's own requests went to the admins.
        ("https://t.me/public_room", "admins"),
    ],
)
async def test_the_old_captcha_switch_turned_off_changes_nothing_else(
    client_factory, db_session_maker, link: str, left: str
) -> None:
    async with db_session_maker() as s:
        s.add(Chat(id=-2103, title="x", public_link=link, join_mode=Chat.JOIN_CAPTCHA))
        await s.commit()

    async with client_factory() as client:
        resp = await client.patch("/api/chats/-2103", json={"is_captcha_enabled": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["join_mode"] == left
