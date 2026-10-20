"""The console's view of the audience: the summary, the list and one person's card."""

from __future__ import annotations

import datetime

import pytest
from app.audience import record
from app.audience.record import Person
from app.core.enums import Touchpoint
from app.core.time import utc_now
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio

NOW = utc_now()
DAY = datetime.timedelta(days=1)

ANNA = Person(id=1, username="anna_n", first_name="Anna", language_code="ru")
TARAS = Person(id=2, first_name="Тарас", language_code="uk")
JAN = Person(id=3, username="jans", first_name="Jan", language_code="cs")
MARIA = Person(id=4, username="mariab", first_name="Мария", language_code="ru")
PETR = Person(id=5, first_name="Petr", language_code="cs")


@pytest.fixture
async def audience(db_session_maker):
    """Five people, one of each kind the summary tells apart."""
    async with db_session_maker() as db:
        # Can be written to by the main bot; came by the bot weeks ago, uses the Mini App now.
        await record.seen(
            db, ANNA, Touchpoint.MAIN_BOT, at=NOW - 30 * DAY, started=Touchpoint.MAIN_BOT, source="matfyz"
        )
        await record.seen(db, ANNA, Touchpoint.MINI_APP, at=NOW)
        # Only the contact bot: the main bot has never been opened.
        await record.seen(db, TARAS, Touchpoint.CONTACT_BOT, at=NOW - DAY, started=Touchpoint.CONTACT_BOT)
        # Opened the Mini App and did not let the bot write.
        await record.seen(db, JAN, Touchpoint.MINI_APP, at=NOW - 2 * DAY)
        # Started the main bot, then blocked it.
        await record.seen(db, MARIA, Touchpoint.MAIN_BOT, at=NOW - 3 * DAY, started=Touchpoint.MAIN_BOT)
        await record.blocked(db, MARIA.id, Touchpoint.MAIN_BOT, at=NOW - 2 * DAY)
        # Started the main bot and asked not to hear from us.
        await record.seen(db, PETR, Touchpoint.MAIN_BOT, at=NOW - 60 * DAY, started=Touchpoint.MAIN_BOT)
        await record.opted_out(db, PETR.id, at=NOW - 10 * DAY)
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


async def test_the_summary_splits_everyone_by_whether_the_bot_may_write(client, audience) -> None:
    summary = (await client.get("/api/audience/summary")).json()

    assert summary["total"] == 5
    assert summary["reach"] == {"reachable": 1, "never_started": 2, "blocked": 1, "opted_out": 1}
    # Where each person came from first.
    assert summary["first_touch"] == {"main_bot": 3, "contact_bot": 1, "mini_app": 1, "moved_bot": 0}
    assert summary["languages"] == [{"code": "cs", "count": 2}, {"code": "ru", "count": 2}, {"code": "uk", "count": 1}]
    # Eight weeks, oldest first; Anna came a month ago, so this week is the other three.
    assert len(summary["new_by_week"]) == 8
    assert summary["new_by_week"][-1] == 3
    assert summary["new_this_week"] == 3


async def test_an_empty_audience_still_names_every_status(client) -> None:
    summary = (await client.get("/api/audience/summary")).json()

    assert summary["total"] == 0
    assert summary["reach"] == {"reachable": 0, "never_started": 0, "blocked": 0, "opted_out": 0}
    assert summary["new_by_week"] == [0] * 8


async def test_the_list_is_newest_activity_first_with_each_persons_status(client, audience) -> None:
    page = (await client.get("/api/audience")).json()

    assert page["total"] == 5
    assert [p["user_id"] for p in page["items"]] == [1, 2, 3, 4, 5]
    anna = page["items"][0]
    assert anna["touchpoints"] == ["main_bot", "mini_app"]
    assert anna["status"] == "reachable"
    assert [p["status"] for p in page["items"]] == [
        "reachable",
        "never_started",
        "never_started",
        "blocked",
        "opted_out",
    ]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("touchpoint=mini_app", [1, 3]),
        ("touchpoint=contact_bot", [2]),
        ("status=reachable", [1]),
        ("language=cs", [3, 5]),
        ("q=anna", [1]),
        ("q=%40jans", [3]),
        ("q=4", [4]),
        ("q=Тара", [2]),
        (f"first_seen_after={(NOW - 5 * DAY).isoformat()}", [2, 3, 4]),
        ("limit=2&offset=2", [3, 4]),
    ],
)
async def test_the_list_filters(client, audience, query, expected) -> None:
    page = (await client.get(f"/api/audience?{query}")).json()

    assert [p["user_id"] for p in page["items"]] == expected


async def test_one_persons_card(client, audience) -> None:
    card = (await client.get("/api/audience/1")).json()

    assert (card["username"], card["source"], card["status"]) == ("anna_n", "matfyz", "reachable")
    touches = {t["touchpoint"]: t["count"] for t in card["touches"]}
    assert touches == {"main_bot": 1, "mini_app": 1}
    reach = {r["bot"]: r for r in card["reach"]}
    assert reach["main_bot"]["blocked_at"] is None
    assert "contact_bot" not in reach


async def test_someone_never_seen_has_no_card(client, audience) -> None:
    assert (await client.get("/api/audience/999")).status_code == 404
