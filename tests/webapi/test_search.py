"""The console's search across chats and people, from the top bar."""

from __future__ import annotations

import pytest
from app.audience import record
from app.audience.record import Person
from app.core.enums import Touchpoint
from app.core.time import utc_now
from app.db.models import Chat
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient

from tests.factories import ChatFactory, UserFactory

pytestmark = pytest.mark.asyncio

MATFYZ = -1001234567890
HVEZDA = -987654


@pytest.fixture
async def world(db_session_maker):
    async with db_session_maker() as db:
        matfyz = ChatFactory.create(id=MATFYZ, title="Matfyz | Karlova univerzita")
        matfyz.resource_status = Chat.STATUS_APPROVED
        matfyz.public_link = "https://t.me/matfyz_chat"
        db.add(matfyz)
        db.add(ChatFactory.create(id=HVEZDA, title="Kolej Hvězda"))
        db.add(ChatFactory.create(id=-111, title="100% flood"))
        # In the chats and in the audience, under another name there.
        db.add(UserFactory.create(id=11, username="anna_n", first_name="Anna", last_name="Novak"))
        # Only in the chats, and blacklisted.
        db.add(UserFactory.create_blocked(id=12, username="spammer", first_name="Cheap", last_name="Ads"))
        await record.seen(db, Person(id=11, username="anna_n", first_name="Аня"), Touchpoint.MINI_APP, at=utc_now())
        # Only in the audience.
        await record.seen(db, Person(id=13, username="jans", first_name="Jan"), Touchpoint.MAIN_BOT, at=utc_now())
        await db.commit()


@pytest.fixture
def client(db_session_maker):
    from app.webapi.deps import get_session

    async def _session():
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.pop(get_session, None)


async def _search(client: AsyncClient, q: str) -> dict:
    response = await client.get("/api/search", params={"q": q})
    assert response.status_code == 200
    return response.json()


async def test_nothing_typed_finds_nothing(client, world) -> None:
    assert await _search(client, "  @ ") == {"chats": [], "people": []}


async def test_a_chat_is_found_by_its_title_its_link_or_its_id(client, world) -> None:
    for q in ("karlova", "matfyz_chat", str(MATFYZ), "1234567890"):
        found = await _search(client, q)
        assert [chat["id"] for chat in found["chats"]] == [MATFYZ], q
    found = await _search(client, "987654")
    assert [chat["id"] for chat in found["chats"]] == [HVEZDA]
    assert found["chats"][0]["resource_status"] == Chat.STATUS_DISCOVERED


async def test_a_percent_sign_is_a_letter_not_a_wildcard(client, world) -> None:
    found = await _search(client, "100%")
    assert [chat["title"] for chat in found["chats"]] == ["100% flood"]


async def test_a_person_is_one_entry_with_their_card_and_blacklist(client, world) -> None:
    found = await _search(client, "@anna")
    assert found["people"] == [
        {
            "user_id": 11,
            "username": "anna_n",
            "first_name": "Аня",
            "last_name": None,
            "in_audience": True,
            "blocked": False,
        }
    ]
    # Found by the name the chats know, Anna still has her card.
    assert (await _search(client, "Novak"))["people"][0]["in_audience"] is True

    spammer = (await _search(client, "12"))["people"]
    assert [(p["user_id"], p["in_audience"], p["blocked"]) for p in spammer] == [(12, False, True)]
    jan = (await _search(client, "jans"))["people"]
    assert [(p["user_id"], p["in_audience"], p["blocked"]) for p in jan] == [(13, True, False)]


async def test_the_search_is_for_the_console_only(client, world, authenticated_super_admin) -> None:
    from app.webapi.deps import require_super_admin

    app.dependency_overrides.pop(require_super_admin, None)
    response = await client.get("/api/search", params={"q": "anna"})
    assert response.status_code in (401, 403)
