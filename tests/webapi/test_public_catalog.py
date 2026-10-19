"""The catalogue a stranger sees.

Two things are being pinned here. What gets in — approved, and carrying a link,
with neither condition sufficient alone. And what comes back for each row, which
is four fields: a page cannot leak a Telegram id or a member count that the
response never contained.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from app.core.config import settings
from app.core.time import utc_now
from app.db.models import Chat, Message
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

FIT = -1001370017010
FS = -1001370017011
CVUT = -1001405134944
PRIVATE = -1001277626739


@pytest.fixture
def client_factory(db_session_maker: async_sessionmaker[AsyncSession]):
    from app.webapi.deps import get_session

    async def _override_get_session():
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    orig_admins = list(settings.admin.super_admins)
    settings.admin.super_admins = [1]
    from app.webapi.deps import require_super_admin

    app.dependency_overrides.pop(require_super_admin, None)
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make
    app.dependency_overrides.pop(get_session, None)
    settings.admin.super_admins = orig_admins


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


async def _messages(session_maker, chat_id: int, count: int, *, days_ago: int = 1) -> None:
    when = utc_now() - datetime.timedelta(days=days_ago)
    async with session_maker() as session:
        for n in range(count):
            message = Message(chat_id=chat_id, user_id=7, message_id=n + 1, message="hi")
            # `timestamp` defaults to now and the constructor does not take it,
            # so age has to be set after construction.
            message.timestamp = when
            session.add(message)
        await session.commit()


async def _recorded_for_days(session_maker, days: int, *, chat_id: int = CVUT) -> None:
    """One message on each of the last `days` days, so the window has ground.

    Every activity assertion needs this. Without it the endpoint answers
    "unknown" for everybody, which is the whole point of the rule and would
    otherwise make each band test pass or fail for the wrong reason.
    """
    async with session_maker() as session:
        session.add(Chat(id=chat_id, title="ground", resource_status=Chat.STATUS_APPROVED))
        for day in range(days):
            message = Message(chat_id=chat_id, user_id=7, message_id=900_000 + day, message="ground")
            message.timestamp = utc_now() - datetime.timedelta(days=day)
            session.add(message)
        await session.commit()


class TestWhatGetsIn:
    async def test_an_approved_chat_with_a_link_is_listed(self, client_factory, db_session_maker) -> None:
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))

        async with client_factory() as client:
            resp = await client.get("/api/public/catalog")

        assert resp.status_code == 200
        assert [row["title"] for row in resp.json()] == ["ČVUT FIT"]

    async def test_a_chat_without_a_link_stays_out(self, client_factory, db_session_maker) -> None:
        """The link is the decision to publish. No link, no decision, no listing."""
        await _seed(db_session_maker, _chat(PRIVATE, "MUNI: Právnická fakulta"))

        async with client_factory() as client:
            resp = await client.get("/api/public/catalog")

        assert resp.json() == []

    @pytest.mark.parametrize("status", [Chat.STATUS_DISCOVERED, Chat.STATUS_DISABLED])
    async def test_a_link_alone_is_not_enough(self, client_factory, db_session_maker, status: str) -> None:
        """A chat the bot does not moderate is not one to send strangers to."""
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", status=status, public_link="https://t.me/cvut_fit"))

        async with client_factory() as client:
            resp = await client.get("/api/public/catalog")

        assert resp.json() == []


class TestWhatComesBack:
    async def test_the_row_carries_five_fields_and_no_more(self, client_factory, db_session_maker) -> None:
        """Whatever a page does with this, it cannot show what is not here."""
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))

        async with client_factory() as client:
            resp = await client.get("/api/public/catalog")

        assert set(resp.json()[0]) == {"title", "link", "group", "institution", "activity"}

    async def test_a_chat_names_the_university_its_group_belongs_to(self, client_factory, db_session_maker) -> None:
        """The catalog's code for it, so the app can put a student's own first.
        Set on the chat at the top; the chats under it carry it without being told."""
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT | ЧВУТ", public_link="https://t.me/cvut_chat", institution_code="cvut"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT),
            _chat(-1001, "Flood", public_link="https://t.me/flood"),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        by_title = {row["title"]: row["institution"] for row in rows}
        assert by_title == {"ČVUT | ЧВУТ": "cvut", "ČVUT FIT": "cvut", "Flood": None}

    async def test_the_parent_decides_even_when_a_child_has_a_code_of_its_own(
        self, client_factory, db_session_maker
    ) -> None:
        """A code left over from when a chat stood at the top is not published."""
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT | ЧВУТ", public_link="https://t.me/cvut_chat", institution_code="cvut"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT, institution_code="vse"),
            _chat(-1002, "Kolej", public_link="https://t.me/kolej"),
            _chat(-1003, "Kolej 7", public_link="https://t.me/kolej7", parent_chat_id=-1002, institution_code="uk"),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        by_title = {row["title"]: row["institution"] for row in rows}
        assert by_title["ČVUT FIT"] == "cvut"
        assert by_title["Kolej 7"] is None

    async def test_the_university_above_it_is_named(self, client_factory, db_session_maker) -> None:
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT | ЧВУТ", public_link="https://t.me/cvut_chat"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        by_title = {row["title"]: row for row in rows}
        assert by_title["ČVUT FIT"]["group"] == "ČVUT | ЧВУТ"

    @pytest.mark.parametrize(
        ("status", "link"),
        [(Chat.STATUS_DISCOVERED, None), (Chat.STATUS_DISCOVERED, "https://t.me/secret"), (Chat.STATUS_DISABLED, None)],
    )
    async def test_a_parent_nobody_published_does_not_name_the_section(
        self, client_factory, db_session_maker, status, link
    ) -> None:
        """Its Telegram title is not for a public page until its owner agreed: approval is that agreement."""
        await _seed(
            db_session_maker,
            _chat(CVUT, "Secret University", resource_status=status, public_link=link),
            _chat(FIT, "Its faculty", public_link="https://t.me/faculty", parent_chat_id=CVUT),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert all("Secret" not in str(row["group"]) for row in rows)

    async def test_a_university_is_filed_under_itself(self, client_factory, db_session_maker) -> None:
        """The chat with faculties beneath it is the section, not a loose row.

        Nothing sits above a university, so filing by the parent alone sent
        ČVUT's own chat to "Остальные" while the section named after it held
        ČVUT's faculties. In production that put eleven of nineteen published
        chats in one bucket — five of them universities — and left the page
        showing three sections instead of seven.
        """
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT | ЧВУТ", public_link="https://t.me/cvut_chat"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        by_title = {row["title"]: row for row in rows}
        assert by_title["ČVUT | ЧВУТ"]["group"] == "ČVUT | ЧВУТ"

    async def test_a_chat_with_nothing_under_it_stays_loose(self, client_factory, db_session_maker) -> None:
        """Only a chat that actually leads others gets a section of its own."""
        await _seed(db_session_maker, _chat(FIT, "Kolej Hvězda", public_link="https://t.me/hvezda"))

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert rows[0]["group"] is None

    async def test_a_faculty_that_is_not_published_still_makes_its_university_a_section(
        self, client_factory, db_session_maker
    ) -> None:
        """Leading a section is about the tree, not about who else got a link.

        MUNI's ten faculty chats have no public link, so the university's own
        chat is the only row of that university on the page. It is still MUNI's
        row, and a reader looking for MUNI should find the heading.
        """
        await _seed(
            db_session_maker,
            _chat(CVUT, "Masarykova univerzita", public_link="https://t.me/muni"),
            _chat(FIT, "MUNI: Fakulta informatiky", parent_chat_id=CVUT),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert [(row["title"], row["group"]) for row in rows] == [("Masarykova univerzita", "Masarykova univerzita")]

    async def test_a_section_opens_with_its_own_chat(self, client_factory, db_session_maker) -> None:
        """The general room first, then the faculties under it.

        Alphabetically "ČVUT | ЧВУТ" sorts after "ČVUT FA", which would bury the
        one chat a reader who does not know their faculty yet actually wants.
        """
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT | ЧВУТ", public_link="https://t.me/cvut_chat"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT),
            _chat(FS, "ČVUT FA", public_link="https://t.me/cvut_fa", parent_chat_id=CVUT),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert [row["title"] for row in rows] == ["ČVUT | ЧВУТ", "ČVUT FA", "ČVUT FIT"]

    async def test_grouped_chats_come_before_ungrouped_ones(self, client_factory, db_session_maker) -> None:
        """The page renders the order it is given rather than sorting again."""
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT | ЧВУТ", public_link="https://t.me/cvut_chat"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT),
            _chat(FS, "Kolej Hvězda", public_link="https://t.me/hvezda"),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert [row["title"] for row in rows] == ["ČVUT | ЧВУТ", "ČVUT FIT", "Kolej Hvězda"]


class TestActivityIsWithheldUntilItMeansSomething:
    async def test_a_fresh_database_claims_nothing(self, client_factory, db_session_maker) -> None:
        """The failure this rule exists for.

        When the bot returned after ten weeks away, a thirty-day count held one
        day of traffic, and every chat that had seen a single message read
        "active" — including the busiest in the network and one with two
        messages to its name. The number was right and the claim was false.
        """
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))
        await _messages(db_session_maker, FIT, 5)

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert rows[0]["activity"] == "unknown"

    async def test_a_fortnight_of_recording_is_enough_to_speak(self, client_factory, db_session_maker) -> None:
        await _recorded_for_days(db_session_maker, 14)
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert {row["activity"] for row in rows} != {"unknown"}

    async def test_the_gap_is_judged_across_the_network_not_per_chat(self, client_factory, db_session_maker) -> None:
        """A silent chat is a fact about the chat. A silent database is not."""
        await _recorded_for_days(db_session_maker, 14)
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        by_title = {row["title"]: row for row in rows}
        assert by_title["ČVUT FIT"]["activity"] == "quiet"


class TestTheBands:
    async def test_a_silent_chat_says_so(self, client_factory, db_session_maker) -> None:
        """Joining a room where nobody has spoken since March should be a choice."""
        await _recorded_for_days(db_session_maker, 20)
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert next(r for r in rows if r["title"] == "ČVUT FIT")["activity"] == "quiet"

    async def test_a_message_a_month_is_not_activity(self, client_factory, db_session_maker) -> None:
        """One message in thirty days used to read "active". It is nearly dead."""
        await _recorded_for_days(db_session_maker, 20)
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))
        await _messages(db_session_maker, FIT, 1)

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert next(r for r in rows if r["title"] == "ČVUT FIT")["activity"] == "quiet"

    async def test_a_dozen_messages_reads_as_active(self, client_factory, db_session_maker) -> None:
        await _recorded_for_days(db_session_maker, 20)
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))
        await _messages(db_session_maker, FIT, 12)

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert next(r for r in rows if r["title"] == "ČVUT FIT")["activity"] == "active"

    async def test_a_hundred_messages_reads_as_busy(self, client_factory, db_session_maker) -> None:
        await _recorded_for_days(db_session_maker, 20)
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))
        await _messages(db_session_maker, FIT, 100)

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert next(r for r in rows if r["title"] == "ČVUT FIT")["activity"] == "busy"

    async def test_old_traffic_does_not_keep_a_dead_chat_alive(self, client_factory, db_session_maker) -> None:
        """A chat busy last spring and silent since is silent."""
        await _recorded_for_days(db_session_maker, 20)
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))
        await _messages(db_session_maker, FIT, 200, days_ago=90)

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert next(r for r in rows if r["title"] == "ČVUT FIT")["activity"] == "quiet"


async def test_public_catalog_does_not_open_admin_routes(client_factory) -> None:
    async with client_factory() as client:
        catalog = await client.get("/api/public/catalog")
        me = await client.get("/api/auth/me")
        admin_chats = await client.get("/api/chats")

    assert catalog.status_code == 200
    assert me.status_code == 401
    assert admin_chats.status_code == 401
