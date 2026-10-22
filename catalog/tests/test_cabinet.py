"""The helper's own profile: reading it back, and publishing without a subject.

Two changes are under test here. `GET /helper` is a new door onto a profile
that `/helpers/{id}` deliberately refuses to open — drafts and hidden ones —
because the person who wrote it has to be able to read it back. And publishing
no longer requires a recognised subject: the catalog needs people in it before
it needs them classified.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import HelperProfile, Offer, ServiceType, Subject, User
from students_cz.db.models.enums import HideReason, PublishStatus

from .conftest import auth_header

pytestmark = pytest.mark.asyncio

OWNER = 91501


async def test_no_profile_answers_with_an_empty_shell(client: AsyncClient) -> None:
    """Not a 404: the screen behind this is a form, and a form always renders."""
    response = await client.get("/api/v1/helper", headers=auth_header(OWNER))

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is False
    assert body["status"] is None
    assert body["offers"] == []


async def test_reading_your_own_profile_needs_init_data(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/helper")).status_code == 401


async def test_a_draft_reads_back_with_ids_and_names(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A draft is invisible in the catalog and must still be editable."""
    subject = await session.scalar(
        select(Subject).where(Subject.slug == "matematicka-analyza")
    )
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    assert subject is not None and service is not None

    # Register the caller, then hand them a draft with one offer.
    await client.get("/api/v1/me", headers=auth_header(OWNER))
    from students_cz.db.models import User

    user = await session.scalar(select(User).where(User.tg_id == OWNER))
    assert user is not None
    session.add(HelperProfile(user_id=user.id, status=PublishStatus.DRAFT, about="Учу"))
    session.add(
        Offer(
            helper_id=user.id,
            service_type_id=service.id,
            subject_id=subject.id,
            price_amount=550,
            langs=["ru"],
        )
    )
    await session.flush()

    body = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()

    assert body["exists"] is True
    assert body["status"] == "draft"
    assert body["about"] == "Учу"
    assert len(body["offers"]) == 1
    offer = body["offers"][0]
    # Both halves: the id is what goes back on save, the name is what is read.
    assert offer["subject_id"] == subject.id
    assert offer["subject_name"]
    assert offer["service_type"] == "tutoring"
    assert offer["price_amount"] == 550


async def test_publishing_without_a_single_subject_is_allowed(
    client: AsyncClient,
) -> None:
    """The parser is no longer the gatekeeper.

    Someone teaching something the taxonomy has never heard of used to write a
    paragraph and watch the button stay grey. Now they get in, and the subject
    is a thing they add later.
    """
    saved = await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={"about": "Помогу с чем угодно по математике", "publish": True},
    )

    assert saved.status_code == 200
    assert saved.json()["helper_status"] == "published"

    body = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()
    assert body["exists"] is True
    assert body["offers"] == []


async def test_hiding_a_published_profile_keeps_it_readable(
    client: AsyncClient,
) -> None:
    """ "Hide me" has to take it out of the catalog, not out of the person's hands."""
    await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={"about": "Первая версия", "publish": True},
    )
    await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={"about": "Первая версия", "publish": False},
    )

    body = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()
    assert body["status"] == "hidden"
    assert body["about"] == "Первая версия"


async def test_a_field_the_payload_omits_survives(client: AsyncClient) -> None:
    """The cabinet sends no headline, and must not therefore erase one.

    `headline` is the line under a person's name on every card in the catalog.
    An unconditional write here wiped it the first time somebody edited a
    price on another screen.
    """
    await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={"headline": "ČVUT FEL, 3. ročník", "about": "Матан", "publish": True},
    )

    await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={"about": "Матан и линейка", "publish": True},
    )

    body = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()
    assert body["headline"] == "ČVUT FEL, 3. ročník"
    assert body["about"] == "Матан и линейка"


async def test_an_explicit_null_still_clears_a_field(client: AsyncClient) -> None:
    """Omitted and null have to stay different, or nothing can be erased."""
    await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={"headline": "ČVUT FEL", "publish": True},
    )
    await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={"headline": None, "publish": True},
    )

    body = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()
    assert body["headline"] is None


async def test_saving_again_keeps_the_same_offer_rows(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Rows are matched on their axes and updated, not deleted and remade.

    `contacts.offer_id` is ON DELETE SET NULL, so recreating the rows quietly
    detached every past contact from the offer it came through — and the
    cabinet turns saving into something people do often.
    """
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    subject = await session.scalar(
        select(Subject).where(Subject.slug == "matematicka-analyza")
    )
    assert service is not None and subject is not None

    offer = {
        "service_type_id": service.id,
        "subject_id": subject.id,
        "price_amount": 600,
        "price_unit": "hour",
    }
    await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={"about": "Матан", "publish": True, "offers": [offer]},
    )
    user = await session.scalar(select(User).where(User.tg_id == OWNER))
    assert user is not None
    before = await session.scalar(select(Offer.id).where(Offer.helper_id == user.id))

    await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={
            "about": "Матан",
            "publish": True,
            "offers": [{**offer, "price_amount": 700}],
        },
    )

    rows = (await session.scalars(select(Offer).where(Offer.helper_id == user.id))).all()
    assert len(rows) == 1
    assert rows[0].id == before, "the row was recreated instead of updated"
    assert float(rows[0].price_amount or 0) == 700


async def test_an_offer_the_payload_drops_is_deleted(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The set is still authoritative — updating in place must not mean keeping."""
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    subjects = (
        await session.scalars(
            select(Subject).where(
                Subject.slug.in_(["matematicka-analyza", "linearni-algebra"])
            )
        )
    ).all()
    assert service is not None and len(subjects) == 2

    await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={
            "publish": True,
            "offers": [
                {"service_type_id": service.id, "subject_id": s.id} for s in subjects
            ],
        },
    )
    await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={
            "publish": True,
            "offers": [{"service_type_id": service.id, "subject_id": subjects[0].id}],
        },
    )

    body = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()
    assert [o["subject_id"] for o in body["offers"]] == [subjects[0].id]


async def test_the_owner_reads_whether_an_operator_has_looked_yet(
    client: AsyncClient,
) -> None:
    """Listed at once, and «на проверке» until an operator kept it: no
    pre-moderation, only a word for the owner."""
    await client.put("/api/v1/helper", headers=auth_header(OWNER), json={"publish": True})
    fresh = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()

    assert fresh["status"] == "published"
    assert fresh["under_review"] is True
    assert fresh["hidden_reason"] is None


async def test_a_profile_an_operator_hid_reads_back_as_hidden_and_why(
    client: AsyncClient, session: AsyncSession
) -> None:
    await client.put("/api/v1/helper", headers=auth_header(OWNER), json={"publish": True})
    user = await session.scalar(select(User).where(User.tg_id == OWNER))
    assert user is not None
    profile = await session.get(HelperProfile, user.id)
    assert profile is not None
    profile.status = PublishStatus.BANNED
    profile.hidden_reason = HideReason.OTHER
    profile.hidden_note = "Чужие фото"
    profile.reviewed_at = datetime.now(UTC)
    await session.flush()

    body = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()
    me = (await client.get("/api/v1/me", headers=auth_header(OWNER))).json()

    assert body["status"] == "banned"
    assert body["hidden_reason"] == "other"
    assert body["hidden_note"] == "Чужие фото"
    assert body["under_review"] is False
    assert me["helper_status"] == "banned"

    # An edit is saved and sent back to the operator; it stays hidden.
    saved = await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={"about": "Свои фото", "publish": True},
    )
    after = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()

    assert saved.status_code == 200, saved.text
    assert after["status"] == "banned"
    assert after["about"] == "Свои фото"
    assert after["under_review"] is True
    assert after["hidden_reason"] == "other"


async def test_a_reason_reaches_only_its_owner(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A draft or a profile its owner hid has no reason to show."""
    await client.put(
        "/api/v1/helper", headers=auth_header(OWNER), json={"publish": False}
    )
    body = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()

    assert body["status"] == "draft"
    assert body["under_review"] is False
    assert body["hidden_reason"] is None
    assert body["hidden_note"] is None


# ── pausing one offer ───────────────────────────────────────────────────


async def _listed(client: AsyncClient, subject_id: int, user_id: int) -> bool:
    found = await client.get(
        "/api/v1/search",
        params={"subject_id": subject_id, "limit": 50},
        headers=auth_header(91599),
    )
    assert found.status_code == 200, found.text
    return user_id in [card["user_id"] for card in found.json()["results"]]


async def test_a_paused_offer_leaves_the_catalog_and_stays_in_the_profile(
    client: AsyncClient, helper_factory
) -> None:
    helper = await helper_factory(tg_id=OWNER)
    [offer] = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()[
        "offers"
    ]
    assert offer["paused"] is False
    assert await _listed(client, offer["subject_id"], helper.id)

    paused = await client.patch(
        f"/api/v1/helper/offers/{offer['id']}",
        json={"paused": True},
        headers=auth_header(OWNER),
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["paused"] is True
    [kept] = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()[
        "offers"
    ]
    assert kept["id"] == offer["id"]
    assert kept["paused"] is True
    assert kept["price_amount"] == offer["price_amount"]
    assert not await _listed(client, offer["subject_id"], helper.id)

    await client.patch(
        f"/api/v1/helper/offers/{offer['id']}",
        json={"paused": False},
        headers=auth_header(OWNER),
    )
    assert await _listed(client, offer["subject_id"], helper.id)


async def test_saving_the_profile_keeps_a_pause_it_does_not_mention(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=OWNER)
    [offer] = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()[
        "offers"
    ]
    await client.patch(
        f"/api/v1/helper/offers/{offer['id']}",
        json={"paused": True},
        headers=auth_header(OWNER),
    )
    sent = {
        key: offer[key]
        for key in ("service_type_id", "subject_id", "institution_id", "price_amount")
    }

    saved = await client.put(
        "/api/v1/helper", json={"offers": [sent]}, headers=auth_header(OWNER)
    )
    assert saved.status_code == 200, saved.text
    [kept] = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()[
        "offers"
    ]
    assert kept["paused"] is True

    await client.put(
        "/api/v1/helper",
        json={"offers": [{**sent, "paused": False}]},
        headers=auth_header(OWNER),
    )
    [resumed] = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()[
        "offers"
    ]
    assert resumed["paused"] is False


async def test_only_the_owner_may_pause_an_offer(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=OWNER)
    [offer] = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()[
        "offers"
    ]

    refused = await client.patch(
        f"/api/v1/helper/offers/{offer['id']}",
        json={"paused": True},
        headers=auth_header(91598),
    )
    assert refused.status_code == 404
    [kept] = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()[
        "offers"
    ]
    assert kept["paused"] is False


async def test_a_paused_offer_leaves_the_public_profile_and_its_languages(
    client: AsyncClient, helper_factory
) -> None:
    helper = await helper_factory(tg_id=OWNER, langs=("en",))
    [offer] = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()[
        "offers"
    ]
    page = (
        await client.get(f"/api/v1/helpers/{helper.id}", headers=auth_header(91599))
    ).json()
    assert len(page["offers"]) == 1
    assert page["langs"] == ["en"]

    await client.patch(
        f"/api/v1/helper/offers/{offer['id']}",
        json={"paused": True},
        headers=auth_header(OWNER),
    )

    page = (
        await client.get(f"/api/v1/helpers/{helper.id}", headers=auth_header(91599))
    ).json()
    assert page["offers"] == []
    assert page["langs"] == []


async def test_a_paused_offer_no_longer_brings_requests_up_the_feed(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=OWNER)
    [offer] = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()[
        "offers"
    ]
    posted = await client.post(
        "/api/v1/requests",
        json={"text": "нужна помощь с матаном"},
        headers=auth_header(91599),
    )
    assert posted.status_code == 201, posted.text

    async def reason() -> dict | None:
        feed = (
            await client.get(
                "/api/v1/requests/feed",
                params={"limit": 50},
                headers=auth_header(OWNER, username="owner91501"),
            )
        ).json()
        [item] = [item for item in feed if item["id"] == posted.json()["id"]]
        return item["reason"]

    assert (await reason() or {}).get("code") == "feed.same_subject"
    await client.patch(
        f"/api/v1/helper/offers/{offer['id']}",
        json={"paused": True},
        headers=auth_header(OWNER),
    )
    assert (await reason() or {}).get("code") != "feed.same_subject"
