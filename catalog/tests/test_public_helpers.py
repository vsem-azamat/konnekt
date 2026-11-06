"""The helpers the public site may show, and only those.

The site renders these pages for people outside Telegram and for search
engines, so they are read with no init data. That makes the rows public in the
fullest sense, and the rules here are what keeps a person off the open web
until they asked to be on it: their own switch, a listed profile an operator
has looked at, and something to offer. What reaches the page is only what a
stranger needs to choose someone, never a way around the app to reach them.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import HelperProfile, Offer, User
from students_cz.db.models.enums import HideReason, PublishStatus
from students_cz.services.site import helper_slug
from tests.conftest import auth_header

LIST = "/api/v1/public/helpers"


async def _on_site(session: AsyncSession, user: User, **values) -> None:
    await session.execute(
        update(HelperProfile)
        .where(HelperProfile.user_id == user.id)
        .values(**{"show_on_site": True, "reviewed_at": datetime.now(UTC), **values})
    )


async def test_anyone_may_read_them(client: AsyncClient) -> None:
    response = await client.get(LIST)

    assert response.status_code == 200
    assert "Authorization" not in response.request.headers


async def test_a_profile_stays_off_the_site_until_its_owner_asks(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """Listed, looked at, offering something: the switch alone keeps it off."""
    user = await helper_factory(tg_id=70001)
    await _on_site(session, user, show_on_site=False)

    assert (await client.get(LIST)).json() == []
    assert (await client.get(f"{LIST}/{user.id}")).status_code == 404


async def test_a_profile_its_owner_put_on_the_site_is_listed(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    anna = await helper_factory(tg_id=70002, first_name="Анна", last_name="Ковальова")
    await _on_site(session, anna)

    response = await client.get(LIST)

    [card] = response.json()
    assert card["user_id"] == anna.id
    assert card["slug"] == f"anna-k-{anna.id}"
    assert card["name"] == "Анна К."


async def test_an_unreviewed_profile_waits_for_an_operator(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """The app lists a new profile at once; search engines get it once looked at."""
    user = await helper_factory(tg_id=70003)
    await _on_site(session, user, reviewed_at=None)

    assert (await client.get(LIST)).json() == []
    assert (await client.get(f"{LIST}/{user.id}")).status_code == 404


@pytest.mark.parametrize("status", [PublishStatus.DRAFT, PublishStatus.BANNED])
async def test_an_unlisted_profile_is_not_on_the_site(
    client: AsyncClient,
    session: AsyncSession,
    helper_factory,
    status: PublishStatus,
) -> None:
    user = await helper_factory(tg_id=70004)
    hidden = {"hidden_reason": HideReason.SPAM} if status == PublishStatus.BANNED else {}
    await _on_site(session, user, status=status, **hidden)

    assert (await client.get(LIST)).json() == []
    assert (await client.get(f"{LIST}/{user.id}")).status_code == 404


async def test_a_profile_with_nothing_on_offer_is_not_on_the_site(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """A page with a name and nothing else is not worth a search result."""
    user = await helper_factory(tg_id=70005)
    await _on_site(session, user)
    await session.execute(
        update(Offer).where(Offer.helper_id == user.id).values(is_active=False)
    )

    assert (await client.get(LIST)).json() == []
    assert (await client.get(f"{LIST}/{user.id}")).status_code == 404


async def test_a_blocked_account_is_not_on_the_site(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    user = await helper_factory(tg_id=70006)
    await _on_site(session, user)
    await session.execute(update(User).where(User.id == user.id).values(is_blocked=True))

    assert (await client.get(LIST)).json() == []
    assert (await client.get(f"{LIST}/{user.id}")).status_code == 404


async def test_a_card_carries_what_the_list_shows(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    user = await helper_factory(
        tg_id=70007, first_name="Marek", last_name="Novák", price=450, langs=("cs",)
    )
    await _on_site(session, user, city="Praha")

    [card] = (await client.get(LIST, params={"lang": "en"})).json()

    assert card == {
        "user_id": user.id,
        "slug": f"marek-n-{user.id}",
        "name": "Marek N.",
        "initials": "MN",
        "tone": 70007 % 6,
        "headline": "Marek teaches things",
        "services": ["Subject tutoring"],
        "subjects": ["Calculus / Mathematical Analysis"],
        "price_from": {"amount": 450.0, "currency": "CZK", "unit": "hour"},
        "langs": ["cs"],
        "work_format": "both",
        "city": "Praha",
        "rating": None,
        "deals_count": 0,
    }


async def test_a_page_carries_what_a_stranger_needs_to_choose(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    user = await helper_factory(tg_id=70008, first_name="Ivan", last_name=None)
    await _on_site(session, user, about="Учу матанализу пятый год.")

    response = await client.get(f"{LIST}/{user.id}")

    assert response.status_code == 200
    page = response.json()
    assert page["slug"] == f"ivan-{user.id}"
    assert page["name"] == "Ivan"
    assert page["about"] == "Учу матанализу пятый год."
    assert [offer["service_type"] for offer in page["offers"]] == ["tutoring"]


async def test_nothing_on_the_page_reaches_the_person_around_the_app(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """Contact is the app's: there it is counted, and there it can be refused.

    A handle on an open page would also be one a scraper collects.
    """
    user = await helper_factory(tg_id=70009)
    await session.execute(
        update(User).where(User.id == user.id).values(tg_username="marek_private")
    )
    await _on_site(session, user)

    page = (await client.get(f"{LIST}/{user.id}")).json()
    [card] = (await client.get(LIST)).json()

    for body in (page, card):
        assert "marek_private" not in str(body)
        assert "telegram_url" not in body
        assert "intro_context" not in body
        assert "free_slots" not in body
        assert "tg_id" not in body
        # Telegram's avatar links expire, and a cached page would keep a dead one.
        assert "photo_url" not in str(body)


async def test_reading_the_page_records_no_view(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """A view is somebody in the app; a crawler is not somebody."""
    from sqlalchemy import func, select

    from students_cz.db.models import UserEvent

    user = await helper_factory(tg_id=70010)
    await _on_site(session, user)
    before = await session.scalar(select(func.count()).select_from(UserEvent))

    await client.get(f"{LIST}/{user.id}")

    assert await session.scalar(select(func.count()).select_from(UserEvent)) == before


async def test_an_unknown_helper_is_not_found(client: AsyncClient) -> None:
    assert (await client.get(f"{LIST}/999999999")).status_code == 404


# ── the switch ──────────────────────────────────────────────────────────


async def test_the_switch_is_off_until_turned_on(
    client: AsyncClient, helper_factory
) -> None:
    await client.put("/api/v1/helper", json={}, headers=auth_header(70011))

    mine = (await client.get("/api/v1/helper", headers=auth_header(70011))).json()

    assert mine["show_on_site"] is False


async def test_the_owner_turns_it_on_and_off(client: AsyncClient) -> None:
    headers = auth_header(70012)
    await client.put("/api/v1/helper", json={}, headers=headers)

    await client.put("/api/v1/helper", json={"show_on_site": True}, headers=headers)
    on = (await client.get("/api/v1/helper", headers=headers)).json()
    await client.put("/api/v1/helper", json={"show_on_site": False}, headers=headers)
    off = (await client.get("/api/v1/helper", headers=headers)).json()

    assert on["show_on_site"] is True
    assert off["show_on_site"] is False


async def test_a_screen_that_does_not_send_it_leaves_it_alone(
    client: AsyncClient,
) -> None:
    """Every field of the profile is partial: each screen sends what it knows."""
    headers = auth_header(70013)
    await client.put("/api/v1/helper", json={"show_on_site": True}, headers=headers)

    await client.put("/api/v1/helper", json={"headline": "New"}, headers=headers)

    mine = (await client.get("/api/v1/helper", headers=headers)).json()
    assert mine["show_on_site"] is True


# ── the slug ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Анна К.", "anna-k-7"),
        ("Юлія Щ.", "yuliya-shch-7"),
        ("Jiří Ž.", "jiri-z-7"),
        ("Marek", "marek-7"),
        ("Łukasz Ż.", "lukasz-z-7"),
        ("Søren Weiß", "soren-weiss-7"),
        ("Đorđe Æ.", "dorde-ae-7"),
        ("Айгүл Ө.", "aygul-o-7"),
        ("Ұлан Қ.", "ulan-k-7"),
        ("Ўладзіслаў", "uladzislau-7"),
        ("🙂", "7"),
        ("", "7"),
    ],
)
def test_a_slug_is_the_name_in_latin_letters_and_the_id(name: str, slug: str) -> None:
    assert helper_slug(name, 7) == slug


async def test_turning_it_on_asks_an_operator_to_look_again(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """A search engine keeps what it read: consent to the open web is looked at.

    The profile stays listed in the app meanwhile, as any profile on review.
    """
    user = await helper_factory(tg_id=70014)
    await _on_site(session, user, show_on_site=False)
    headers = auth_header(70014)

    await client.put(
        "/api/v1/helper", json={"show_on_site": True, "publish": True}, headers=headers
    )

    mine = (await client.get("/api/v1/helper", headers=headers)).json()
    assert mine["status"] == "published"
    assert mine["show_on_site"] is True
    assert mine["under_review"] is True
    assert (await client.get(LIST)).json() == []


async def test_saving_with_it_on_does_not_ask_again(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """Only turning it on is the new consent; a screen resending `true` is not."""
    user = await helper_factory(tg_id=70015)
    await _on_site(session, user)

    await client.put(
        "/api/v1/helper",
        json={"show_on_site": True, "publish": True},
        headers=auth_header(70015),
    )

    assert [card["user_id"] for card in (await client.get(LIST)).json()] == [user.id]
