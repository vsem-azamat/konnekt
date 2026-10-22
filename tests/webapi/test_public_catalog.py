"""The catalogue a stranger sees.

Two things are being pinned here. What gets in — approved, and carrying a link,
with neither condition sufficient alone. And what comes back for each row, which
is eleven fields: a page cannot leak a Telegram id or who is in a room when the
response never contained them.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from app.core.config import settings
from app.core.time import utc_now
from app.db.models import Chat, ChatMemberSnapshot, Message
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

    @pytest.mark.parametrize("status", [Chat.STATUS_OBSERVED, Chat.STATUS_EXTERNAL])
    async def test_a_chat_we_do_not_moderate_is_listed_once_decided(
        self, client_factory, db_session_maker, status: str
    ) -> None:
        """Listing and moderating are separate decisions: observing or not being in a chat still lists it."""
        await _seed(db_session_maker, _chat(FIT, "ČVUT FJFI", status=status, public_link="https://t.me/cvut_fjfi"))

        async with client_factory() as client:
            resp = await client.get("/api/public/catalog")

        assert [row["title"] for row in resp.json()] == ["ČVUT FJFI"]


class TestWhatComesBack:
    async def test_the_row_carries_twelve_fields_and_no_more(self, client_factory, db_session_maker) -> None:
        """Whatever a page does with this, it cannot show what is not here."""
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))

        async with client_factory() as client:
            resp = await client.get("/api/public/catalog")

        assert set(resp.json()[0]) == {
            "title",
            "link",
            "group",
            "institution",
            "activity",
            "member_count",
            "is_forum",
            "kind",
            "external",
            "avatar",
            "city",
            "topic",
        }

    @pytest.mark.parametrize(
        ("status", "external"),
        [(Chat.STATUS_APPROVED, False), (Chat.STATUS_OBSERVED, False), (Chat.STATUS_EXTERNAL, True)],
    )
    async def test_a_chat_that_is_not_ours_says_so(self, client_factory, db_session_maker, status, external) -> None:
        """Only external is marked: a chat we observe is still ours, and how we run it is nobody's business."""
        await _seed(db_session_maker, _chat(FIT, "ČVUT FJFI", status=status, public_link="https://t.me/cvut_fjfi"))

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert rows[0]["external"] is external

    async def test_an_external_university_still_names_its_section(self, client_factory, db_session_maker) -> None:
        await _seed(
            db_session_maker,
            _chat(CVUT, "VŠE Chat", status=Chat.STATUS_EXTERNAL, public_link="https://t.me/vse_v_praze_chat"),
            _chat(FIT, "VŠE FIS", status=Chat.STATUS_EXTERNAL, public_link="https://t.me/vse_fis", parent_chat_id=CVUT),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert {row["group"] for row in rows} == {"VŠE Chat"}

    async def test_a_chat_says_how_many_people_are_in_it_by_its_newest_snapshot(
        self, client_factory, db_session_maker
    ) -> None:
        """The preview tells a stranger how big the room is before they leave for it.

        The bot writes a row per poll; the newest is the answer, not a sum of them.
        """
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))
        async with db_session_maker() as session:
            session.add(
                ChatMemberSnapshot(chat_id=FIT, member_count=1200, captured_at=utc_now() - datetime.timedelta(hours=2))
            )
            session.add(ChatMemberSnapshot(chat_id=FIT, member_count=1248, captured_at=utc_now()))
            await session.commit()

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert rows[0]["member_count"] == 1248

    async def test_a_count_older_than_three_days_is_not_shown_as_today_s(
        self, client_factory, db_session_maker
    ) -> None:
        """The bot left a chat or stopped polling it: the last number it saw is history, not size."""
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))
        async with db_session_maker() as session:
            session.add(
                ChatMemberSnapshot(chat_id=FIT, member_count=1248, captured_at=utc_now() - datetime.timedelta(days=4))
            )
            await session.commit()

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert rows[0]["member_count"] is None

    async def test_a_chat_never_measured_has_no_count_rather_than_zero(self, client_factory, db_session_maker) -> None:
        """Empty and unknown are different claims; a preview shows nothing for the second."""
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert rows[0]["member_count"] is None

    async def test_a_chat_says_whether_it_has_topics(self, client_factory, db_session_maker) -> None:
        await _seed(
            db_session_maker,
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", is_forum=True),
            _chat(FS, "ČVUT FS", public_link="https://t.me/cvut_fs"),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert {row["title"]: row["is_forum"] for row in rows} == {"ČVUT FIT": True, "ČVUT FS": False}

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

    async def test_a_chat_names_its_city_or_none_for_all_of_czechia(self, client_factory, db_session_maker) -> None:
        await _seed(
            db_session_maker,
            _chat(-1001, "Strahov", public_link="https://t.me/strahov", city="Praha"),
            _chat(-1002, "Fyzika v ČR", public_link="https://t.me/fyzika"),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert {row["title"]: row["city"] for row in rows} == {"Strahov": "Praha", "Fyzika v ČR": None}

    async def test_a_chat_under_a_parent_is_in_the_parent_s_city_unless_it_names_its_own(
        self, client_factory, db_session_maker
    ) -> None:
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT | ЧВУТ", public_link="https://t.me/cvut_chat", city="Praha"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT),
            _chat(FS, "ČVUT Děčín", public_link="https://t.me/cvut_decin", parent_chat_id=CVUT, city="Děčín"),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        by_title = {row["title"]: row["city"] for row in rows}
        assert by_title == {"ČVUT | ЧВУТ": "Praha", "ČVUT FIT": "Praha", "ČVUT Děčín": "Děčín"}

    async def test_a_university_s_chats_are_university_chats_without_being_told(
        self, client_factory, db_session_maker
    ) -> None:
        """The institution says what the chat is; a topic set on it says otherwise.

        Strahov carries ČVUT's code because its residents study there, but it is
        a dormitory and is filed with the dormitories.
        """
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT | ЧВУТ", public_link="https://t.me/cvut_chat", institution_code="cvut"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT),
            _chat(FS, "PODOLI", public_link="https://t.me/podoli", parent_chat_id=CVUT, topic="dorms"),
            _chat(-1001, "Strahov", public_link="https://t.me/strahov", institution_code="cvut", topic="dorms"),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert {row["title"]: row["topic"] for row in rows} == {
            "ČVUT | ЧВУТ": "university",
            "ČVUT FIT": "university",
            "PODOLI": "dorms",
            "Strahov": "dorms",
        }

    async def test_a_chat_under_a_parent_takes_its_topic(self, client_factory, db_session_maker) -> None:
        await _seed(
            db_session_maker,
            _chat(-1001, "IT Чехия", public_link="https://t.me/it", topic="work_it"),
            _chat(-1002, "IT Чехия: вакансии", public_link="https://t.me/it_jobs", parent_chat_id=-1001),
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert {row["topic"] for row in rows} == {"work_it"}

    async def test_a_chat_nobody_filed_has_no_topic(self, client_factory, db_session_maker) -> None:
        """Not "general": the page decides where an unfiled chat goes, the API does not pretend it was filed."""
        await _seed(db_session_maker, _chat(-1001, "Flood", public_link="https://t.me/flood"))

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert rows[0]["topic"] is None

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

        assert [(row["title"], row["group"]) for row in rows] == [("Its faculty", None)]

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


class TestOrder:
    """Ours before somebody else's, then the larger first, at every level (Azamat, 2026-10-22).

    Before, groups were alphabetical, and somebody else's ČZU opened the list.
    """

    async def _counts(self, session_maker, **by_id: int) -> None:
        async with session_maker() as session:
            for chat_id, count in by_id.items():
                session.add(ChatMemberSnapshot(chat_id=int(chat_id), member_count=count, captured_at=utc_now()))
            await session.commit()

    async def test_our_groups_come_first_then_the_larger(self, client_factory, db_session_maker) -> None:
        czu, vse, small = -1001141940639, -1001292637469, -1001198485843
        await _seed(
            db_session_maker,
            _chat(czu, "ČZU", public_link="https://t.me/czu_chat", status=Chat.STATUS_EXTERNAL),
            _chat(FIT, "ČZU PEF", public_link="https://t.me/czu_pef", parent_chat_id=czu),
            _chat(CVUT, "ČVUT", public_link="https://t.me/cvut_chat"),
            _chat(FS, "ČVUT FS", public_link="https://t.me/cvut_fs", parent_chat_id=CVUT),
            _chat(vse, "VŠE", public_link="https://t.me/vse_chat"),
            _chat(small, "Strahov", public_link="https://t.me/strahov"),
        )
        # The external ČZU is the largest, and ČVUT's faculty outnumbers VŠE: neither moves its group.
        await self._counts(
            db_session_maker,
            **{str(czu): 2400, str(FIT): 1600, str(CVUT): 1500, str(FS): 2000, str(vse): 900, str(small): 1000},
        )

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert [row["title"] for row in rows] == ["ČVUT FS", "ČVUT", "Strahov", "VŠE", "ČZU PEF", "ČZU"]

    async def test_inside_a_group_ours_come_first_then_the_larger(self, client_factory, db_session_maker) -> None:
        await _seed(
            db_session_maker,
            _chat(CVUT, "ČVUT", public_link="https://t.me/cvut_chat"),
            _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit", parent_chat_id=CVUT),
            _chat(FS, "ČVUT FS", public_link="https://t.me/cvut_fs", parent_chat_id=CVUT),
            _chat(
                PRIVATE, "FEL OI", public_link="https://t.me/fel_oi", parent_chat_id=CVUT, status=Chat.STATUS_EXTERNAL
            ),
        )
        await self._counts(db_session_maker, **{str(CVUT): 1500, str(FIT): 300, str(FS): 900, str(PRIVATE): 5000})

        async with client_factory() as client:
            rows = (await client.get("/api/public/catalog")).json()

        assert [row["title"] for row in rows] == ["ČVUT", "ČVUT FS", "ČVUT FIT", "FEL OI"]


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


async def test_strangers_asking_again_do_not_reach_the_database(client_factory, db_session_maker) -> None:
    """The endpoint is open to anyone and aggregates messages; a loop of requests was a loop of scans."""
    await _seed(db_session_maker, _chat(CVUT, "ČVUT | ЧВУТ", public_link="https://t.me/cvut_chat"))

    async with client_factory() as client:
        first = (await client.get("/api/public/catalog")).json()
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))
        again = (await client.get("/api/public/catalog")).json()

    assert again == first


async def test_a_remembered_answer_runs_out(client_factory, db_session_maker, monkeypatch) -> None:
    from app.webapi.services import public_answers

    await _seed(db_session_maker, _chat(CVUT, "ČVUT | ЧВУТ", public_link="https://t.me/cvut_chat"))
    async with client_factory() as client:
        await client.get("/api/public/catalog")
        await _seed(db_session_maker, _chat(FIT, "ČVUT FIT", public_link="https://t.me/cvut_fit"))
        later = public_answers.time.monotonic() + public_answers.SECONDS + 1
        monkeypatch.setattr(public_answers.time, "monotonic", lambda: later)
        rows = (await client.get("/api/public/catalog")).json()

    assert {row["title"] for row in rows} == {"ČVUT | ЧВУТ", "ČVUT FIT"}


async def test_a_console_edit_shows_on_the_public_page_at_once(client_factory, db_session_maker) -> None:
    """The console refreshes the public directory after an edit; it must not get the old answer."""
    from app.webapi.deps import require_super_admin

    await _seed(db_session_maker, _chat(CVUT, "ČVUT | ЧВУТ", public_link="https://t.me/cvut_chat"))
    # The edit is the console's, so it comes from a signed-in super admin.
    app.dependency_overrides[require_super_admin] = lambda: 1
    try:
        async with client_factory() as client:
            await client.get("/api/public/catalog")
            edited = await client.patch(f"/api/chats/{CVUT}", json={"public_link": None})
            rows = (await client.get("/api/public/catalog")).json()
    finally:
        app.dependency_overrides.pop(require_super_admin, None)

    assert edited.status_code == 200, edited.text
    assert rows == []
