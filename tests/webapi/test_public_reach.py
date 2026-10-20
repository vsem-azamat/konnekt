"""The figures an advertiser reads before asking for a price.

Two things are being pinned. What the number covers — the published catalogue
and nothing else, because reach counted over private chats a stranger cannot
see would be a claim about rooms we are not offering. And that the response
says how much of the catalogue it actually measured, since member counts come
from snapshots the userbot may not have managed to take.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from app.core.time import utc_now
from app.db.models import Chat, ChatMemberSnapshot
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

CVUT = -1001405134944
FIT = -1001370017010
FS = -1001370017011
VSE = -1001405134945
VSE_MAIN = -1001370017012
PRIVATE = -1001277626739


@pytest.fixture
def client_factory(db_session_maker: async_sessionmaker[AsyncSession]):
    from app.webapi.deps import get_session

    async def _override_get_session():
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make
    app.dependency_overrides.pop(get_session, None)


def _chat(chat_id: int, title: str, **kwargs) -> Chat:
    chat = Chat(id=chat_id, title=title, resource_status=kwargs.pop("status", Chat.STATUS_APPROVED))
    for key, value in kwargs.items():
        setattr(chat, key, value)
    return chat


async def _seed(session_maker, *chats: Chat) -> None:
    async with session_maker() as session:
        for chat in chats:
            session.add(chat)
        await session.commit()


async def _snapshot(session_maker, chat_id: int, count: int, *, hours_ago: int = 1) -> None:
    async with session_maker() as session:
        session.add(
            ChatMemberSnapshot(
                chat_id=chat_id,
                member_count=count,
                captured_at=utc_now() - datetime.timedelta(hours=hours_ago),
            )
        )
        await session.commit()


async def _reach(client_factory) -> dict:
    async with client_factory() as client:
        resp = await client.get("/api/public/reach")
    assert resp.status_code == 200
    return resp.json()


class TestWhatIsCounted:
    async def test_only_the_published_catalogue(self, client_factory, db_session_maker) -> None:
        """A private chat's size is not ours to advertise."""
        await _seed(
            db_session_maker,
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"),
            _chat(PRIVATE, "Закрытый"),
        )
        await _snapshot(db_session_maker, FIT, 1200)
        await _snapshot(db_session_maker, PRIVATE, 9000)

        body = await _reach(client_factory)

        assert body["chats"] == 1
        assert body["members"] == 1200

    async def test_a_discovered_chat_stays_out(self, client_factory, db_session_maker) -> None:
        await _seed(
            db_session_maker,
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"),
            _chat(FS, "ČVUT FS", public_link="https://t.me/cvut_fs", status=Chat.STATUS_DISCOVERED),
        )
        await _snapshot(db_session_maker, FIT, 1200)
        await _snapshot(db_session_maker, FS, 800)

        body = await _reach(client_factory)

        assert body["chats"] == 1
        assert body["members"] == 1200

    @pytest.mark.parametrize("status", [Chat.STATUS_OBSERVED, Chat.STATUS_EXTERNAL])
    async def test_a_listed_chat_we_do_not_run_is_not_reach(self, client_factory, db_session_maker, status) -> None:
        """Reach is quoted to somebody paying for a post, and nobody posts where the bot stays silent."""
        await _seed(
            db_session_maker,
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"),
            _chat(FS, "ČVUT FJFI", public_link="https://t.me/cvut_fjfi", status=status),
        )
        await _snapshot(db_session_maker, FIT, 1200)
        await _snapshot(db_session_maker, FS, 276)

        body = await _reach(client_factory)

        assert body["chats"] == 1
        assert body["members"] == 1200

    async def test_the_newest_snapshot_wins(self, client_factory, db_session_maker) -> None:
        """The loop writes a row per poll; a sum over all of them counts the
        same people once per observation."""
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))
        await _snapshot(db_session_maker, FIT, 1000, hours_ago=48)
        await _snapshot(db_session_maker, FIT, 1200, hours_ago=1)

        body = await _reach(client_factory)

        assert body["members"] == 1200

    async def test_a_count_older_than_three_days_is_not_reach(self, client_factory, db_session_maker) -> None:
        """The same window as the catalogue: a chat the bot stopped counting is
        unmeasured, not as large as it was a week ago."""
        await _seed(
            db_session_maker,
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"),
            _chat(FS, "ČVUT FS", public_link="https://t.me/cvut_fs"),
        )
        await _snapshot(db_session_maker, FIT, 1200, hours_ago=1)
        await _snapshot(db_session_maker, FS, 800, hours_ago=100)

        body = await _reach(client_factory)

        assert body["members"] == 1200
        assert body["measured_chats"] == 1


class TestHowMuchItMeasured:
    async def test_a_chat_without_a_snapshot_counts_as_unmeasured(self, client_factory, db_session_maker) -> None:
        """Telegram does not answer for every chat, and the page has to be able
        to say the total covers part of the catalogue."""
        await _seed(
            db_session_maker,
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"),
            _chat(FS, "ČVUT FS", public_link="https://t.me/cvut_fs"),
        )
        await _snapshot(db_session_maker, FIT, 1200)

        body = await _reach(client_factory)

        assert body["chats"] == 2
        assert body["measured_chats"] == 1
        assert body["members"] == 1200

    async def test_an_empty_catalogue_answers_zeroes(self, client_factory) -> None:
        body = await _reach(client_factory)

        assert body["chats"] == 0
        assert body["members"] == 0
        assert body["groups"] == []


class TestTheBreakdown:
    async def test_grouped_by_the_parent_chat(self, client_factory, db_session_maker) -> None:
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT"),
            _chat(VSE, "VŠE"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT),
            _chat(FS, "ČVUT FS", public_link="https://t.me/cvut_fs", parent_chat_id=CVUT),
            _chat(VSE_MAIN, "VŠE общий", public_link="https://t.me/vse_main", parent_chat_id=VSE),
        )
        await _snapshot(db_session_maker, FIT, 1200)
        await _snapshot(db_session_maker, FS, 800)
        await _snapshot(db_session_maker, VSE_MAIN, 500)

        body = await _reach(client_factory)

        by_name = {group["name"]: group for group in body["groups"]}
        assert by_name["ČVUT"] == {"name": "ČVUT", "chats": 2, "members": 2000}
        assert by_name["VŠE"] == {"name": "VŠE", "chats": 1, "members": 500}

    async def test_a_parent_awaiting_approval_does_not_name_the_group(self, client_factory, db_session_maker) -> None:
        await _seed(
            db_session_maker,
            _chat(CVUT, "Secret University", status=Chat.STATUS_DISCOVERED),
            _chat(FIT, "Its faculty", public_link="https://t.me/faculty", parent_chat_id=CVUT),
        )

        body = await _reach(client_factory)

        assert [(group["name"], group["chats"]) for group in body["groups"]] == [("Остальные", 1)]

    async def test_biggest_group_first(self, client_factory, db_session_maker) -> None:
        """Read as a table of where a post would land, largest first."""
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT"),
            _chat(VSE, "VŠE"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT),
            _chat(VSE_MAIN, "VŠE общий", public_link="https://t.me/vse_main", parent_chat_id=VSE),
        )
        await _snapshot(db_session_maker, FIT, 300)
        await _snapshot(db_session_maker, VSE_MAIN, 900)

        body = await _reach(client_factory)

        assert [group["name"] for group in body["groups"]] == ["VŠE", "ČVUT"]

    async def test_a_university_counts_towards_its_own_row(self, client_factory, db_session_maker) -> None:
        """The reach table and the catalogue split the rows the same way.

        Filed by the parent alone, ČVUT's own chat — the largest room in the
        network — was counted under "Остальные" while the row named after it
        held only its faculties. The table is read as "where would this post
        land", and it was pointing at the wrong place.
        """
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT", public_link="https://t.me/cvut_chat"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT),
        )
        await _snapshot(db_session_maker, CVUT, 5000)
        await _snapshot(db_session_maker, FIT, 1200)

        body = await _reach(client_factory)

        assert body["groups"] == [{"name": "ČVUT", "chats": 2, "members": 6200}]

    async def test_a_chat_with_no_parent_is_bucketed(self, client_factory, db_session_maker) -> None:
        await _seed(db_session_maker, _chat(FIT, "Чешский язык", public_link="https://t.me/czech_lang"))
        await _snapshot(db_session_maker, FIT, 400)

        body = await _reach(client_factory)

        assert body["groups"] == [{"name": "Остальные", "chats": 1, "members": 400}]


class TestWhatItDoesNotSay:
    async def test_no_chat_ids_and_no_per_chat_counts(self, client_factory, db_session_maker) -> None:
        """The response shape is the safety. A page cannot leak what it never got."""
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT),
        )
        await _snapshot(db_session_maker, FIT, 1200)

        async with client_factory() as client:
            raw = (await client.get("/api/public/reach")).text

        assert str(FIT) not in raw
        assert "ČVUT FIT" not in raw


async def test_reach_is_served_from_memory_for_a_while(client_factory, db_session_maker) -> None:
    await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))

    first = await _reach(client_factory)
    await _seed(db_session_maker, _chat(FS, "ČVUT FS", public_link="https://t.me/cvut_fs"))
    again = await _reach(client_factory)

    assert again == first
