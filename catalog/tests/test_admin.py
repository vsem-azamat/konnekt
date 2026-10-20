"""What the operator reads and changes in the console, and who may.

The console lives in supervisor-telegram's app; the catalog's part of it is
two read-only lists and the partner cards, behind `ADMIN_TG_IDS`. See
docs/architecture.md, «The operator reads the catalog and runs the partner
cards».
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.core.config import Settings, get_settings
from students_cz.db.models import HelperProfile, Offer, User
from students_cz.db.models.enums import (
    PlacementEventKind,
    PlacementSlot,
    PublishStatus,
    RequestStatus,
    UiLang,
)
from students_cz.db.models.ops import SearchQuery
from students_cz.db.models.partners import (
    Partner,
    PartnerOffer,
    PartnerOfferI18n,
    Placement,
    PlacementEvent,
)
from students_cz.db.models.requests import HelpRequest, RequestResponse

from .conftest import app_for, auth_header

pytestmark = pytest.mark.asyncio

OPERATOR = 97001
STRANGER = 97002


def _client(
    session: AsyncSession, admins: tuple[int, ...] | str = (OPERATOR,)
) -> AsyncClient:
    app = app_for(session)
    ids = admins if isinstance(admins, str) else list(admins)
    configured = Settings(_env_file=None, admin_tg_ids=ids)
    app.dependency_overrides[get_settings] = lambda: configured
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── who ─────────────────────────────────────────────────────────────────


async def test_me_says_who_is_an_operator(session: AsyncSession) -> None:
    async with _client(session) as http:
        operator = await http.get("/api/v1/me", headers=auth_header(OPERATOR))
        stranger = await http.get("/api/v1/me", headers=auth_header(STRANGER))

    assert operator.json()["is_admin"] is True
    assert stranger.json()["is_admin"] is False


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/admin/catalog"),
        ("GET", "/api/v1/admin/partners"),
        ("POST", "/api/v1/admin/placements"),
        ("PATCH", "/api/v1/admin/placements/1"),
        ("GET", "/api/v1/admin/profiles/1"),
        ("POST", "/api/v1/admin/profiles/1/review"),
        ("POST", "/api/v1/admin/profiles/1/hide"),
        ("POST", "/api/v1/admin/profiles/1/restore"),
    ],
)
async def test_everybody_else_is_refused(
    session: AsyncSession, method: str, path: str
) -> None:
    async with _client(session) as http:
        response = await http.request(
            method, path, headers=auth_header(STRANGER), json={"is_active": False}
        )

    assert response.status_code == 403


async def test_nobody_is_an_operator_unless_named(session: AsyncSession) -> None:
    async with _client(session, admins="") as http:
        response = await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))

    assert response.status_code == 403


async def test_the_list_is_read_as_the_deploy_writes_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Comma-separated, like supervisor's ADMIN_SUPER_ADMINS; a typo refuses to start.

    Through the environment and a .env file, which is how the deploy and a
    developer set it, and where a list would otherwise be parsed as JSON.
    """
    monkeypatch.setenv("ADMIN_TG_IDS", "1, 22")
    assert Settings(_env_file=None).admin_tg_ids == [1, 22]
    monkeypatch.setenv("ADMIN_TG_IDS", "")
    assert Settings(_env_file=None).admin_tg_ids == []
    monkeypatch.setenv("ADMIN_TG_IDS", "1,@me")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

    monkeypatch.delenv("ADMIN_TG_IDS")
    env_file = tmp_path / ".env"
    env_file.write_text("ADMIN_TG_IDS=5, 6\n")
    assert Settings(_env_file=env_file).admin_tg_ids == [5, 6]


# ── the catalog ─────────────────────────────────────────────────────────


async def _person(session: AsyncSession, tg_id: int, name: str) -> User:
    user = User(tg_id=tg_id, first_name=name, ui_lang=UiLang.RU, spoken_langs=["ru"])
    session.add(user)
    await session.flush()
    return user


async def test_new_profiles_wait_for_an_operator_newest_first(
    session: AsyncSession, helper_factory
) -> None:
    now = datetime.now(UTC)
    fresh = await helper_factory(tg_id=97101, first_name="Marina", last_name="Kovalenko")
    older = await helper_factory(tg_id=97102, first_name="Olga", last_name=None)
    stale = await helper_factory(tg_id=97103, first_name="Petr", last_name=None)
    hidden = await helper_factory(tg_id=97104, first_name="Irina", last_name=None)
    for user, age in ((fresh, 1), (older, 3), (stale, 10), (hidden, 1)):
        profile = await session.get(HelperProfile, user.id)
        assert profile is not None
        profile.published_at = now - timedelta(days=age)
    hidden_profile = await session.get(HelperProfile, hidden.id)
    assert hidden_profile is not None
    hidden_profile.status = PublishStatus.HIDDEN
    # Olga switched her only service off: the catalog does not list it.
    for offer in await session.scalars(select(Offer).where(Offer.helper_id == older.id)):
        offer.is_active = False
    await session.flush()

    async with _client(session) as http:
        body = (
            await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        ).json()

    names = [row["name"] for row in body["profiles"]]
    ours = [name for name in names if name in {"Marina K.", "Olga", "Petr"}]
    assert ours == ["Marina K.", "Olga", "Petr"], (
        "first name and an initial, newest first"
    )
    # Older than a week and still nobody looked: it stays until somebody does.
    assert "Irina" not in names, "hidden since"
    assert body["profiles"][0]["services"], "what they offer, by service name"
    assert body["profiles"][1]["services"] == [], "a service switched off is not offered"
    assert body["counts"]["profiles_week"] >= 2
    # A display name, as the catalog shows it, and nothing to reach them by.
    assert set(body["profiles"][0]) == {"user_id", "name", "services", "published_at"}


async def test_unanswered_requests_are_open_ones_nobody_answered_oldest_first(
    session: AsyncSession, helper_factory
) -> None:
    now = datetime.now(UTC)
    author = await _person(session, 97201, "Anna")
    helper = await helper_factory(tg_id=97202)

    def ask(text: str, status: RequestStatus = RequestStatus.OPEN) -> HelpRequest:
        return HelpRequest(author_id=author.id, raw_text=text, status=status)

    waiting_long = ask("курсовая по микроэкономике")
    waiting = ask("přijímačky на медицину")
    answered = ask("матан к экзамену")
    closed = ask("уже не надо", RequestStatus.CLOSED)
    draft = ask("ещё пишу", RequestStatus.DRAFT)
    # Still says open, but its deadline passed: nobody can answer it any more.
    expired = ask("прошлогодняя сессия")
    expired.expires_at = now - timedelta(days=40)
    for request in (waiting_long, waiting, answered, closed, draft, expired):
        session.add(request)
    await session.flush()
    waiting_long.created_at = now - timedelta(days=5)
    waiting.created_at = now - timedelta(days=1)
    session.add(
        RequestResponse(request_id=answered.id, helper_id=helper.id, message="могу")
    )
    await session.flush()

    async with _client(session) as http:
        body = (
            await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        ).json()

    texts = [row["text"] for row in body["unanswered"]]
    assert texts.index("курсовая по микроэкономике") < texts.index(
        "přijímačky на медицину"
    )
    assert "матан к экзамену" not in texts
    assert "уже не надо" not in texts
    assert "ещё пишу" not in texts, "a draft is not a request yet"
    assert "прошлогодняя сессия" not in texts, "expired: it refuses answers"
    assert body["counts"]["unanswered"] == len(texts)


async def test_requests_this_week_count_what_was_posted(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    author = await _person(session, 97301, "Oleg")
    rows = [
        ("posted", RequestStatus.OPEN, 1),
        ("closed since", RequestStatus.CLOSED, 2),
        ("a draft", RequestStatus.DRAFT, 1),
        ("last month", RequestStatus.OPEN, 20),
    ]
    for text, status, age in rows:
        request = HelpRequest(author_id=author.id, raw_text=text, status=status)
        session.add(request)
        await session.flush()
        request.created_at = now - timedelta(days=age)
    await session.flush()

    async with _client(session) as http:
        body = (
            await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        ).json()
    assert body["counts"]["requests_week"] == 2


async def test_failed_searches_are_grouped_by_text_most_frequent_first(
    session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    rows = [
        ("AutoCAD", 0, 2),
        ("autocad ", 0, 3),
        ("микроэкономика", 0, 5),
        ("микроэкономика", 0, 6),
        ("микроэкономика", 0, 7),
        ("матан", 5, 1),
        ("латынь", 0, 40),
    ]
    for text, found, age in rows:
        query = SearchQuery(raw_text=text, results_count=found)
        session.add(query)
        await session.flush()
        query.created_at = now - timedelta(days=age)
    await session.flush()

    async with _client(session) as http:
        body = (
            await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        ).json()

    failed = {row["text"].lower(): row["times"] for row in body["failed_searches"]}
    assert list(failed)[:2] == ["микроэкономика", "autocad"]
    assert failed["микроэкономика"] == 3
    assert failed["autocad"] == 2, "case and trailing spaces are the same search"
    assert "матан" not in failed, "it found something"
    assert "латынь" not in failed, "older than 30 days"
    assert body["counts"]["failed_searches"] == 2


# ── the partners ────────────────────────────────────────────────────────


async def test_placements_carry_their_last_months_impressions_and_clicks(
    session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    partner = Partner(code="admin-test-insurer", name="Insurer")
    session.add(partner)
    await session.flush()
    offer = PartnerOffer(partner_id=partner.id, url="https://example.test/offer")
    session.add(offer)
    await session.flush()
    session.add(PartnerOfferI18n(offer_id=offer.id, lang=UiLang.RU, title="Страховка"))
    live = Placement(offer_id=offer.id, slot=PlacementSlot.SCREEN_LIFE)
    off = Placement(offer_id=offer.id, slot=PlacementSlot.PROFILE_FOOTER, is_active=False)
    session.add_all([live, off])
    await session.flush()
    events = [
        (PlacementEventKind.IMPRESSION, 1),
        (PlacementEventKind.IMPRESSION, 2),
        (PlacementEventKind.IMPRESSION, 45),
        (PlacementEventKind.CLICK, 3),
    ]
    for kind, age in events:
        event = PlacementEvent(placement_id=live.id, kind=kind)
        session.add(event)
        await session.flush()
        event.created_at = now - timedelta(days=age)
    await session.flush()

    async with _client(session) as http:
        body = (
            await http.get("/api/v1/admin/partners", headers=auth_header(OPERATOR))
        ).json()

    rows = {row["placement_id"]: row for row in body}
    assert rows[live.id]["impressions"] == 2
    assert rows[live.id]["clicks"] == 1
    assert rows[live.id]["partner"] == "Insurer"
    assert rows[live.id]["title"] == "Страховка"
    assert rows[live.id]["slot"] == "screen_life"
    assert rows[live.id]["is_active"] is True
    assert rows[off.id]["is_active"] is False
    assert rows[off.id]["impressions"] == 0


async def test_counts_are_the_full_lengths_when_the_lists_are_cut(
    session: AsyncSession, helper_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from students_cz.services import admin

    monkeypatch.setattr(admin, "LIST_CAP", 1)
    monkeypatch.setattr(admin, "SEARCH_CAP", 1)
    now = datetime.now(UTC)
    # The database may hold profiles of its own (demo data): count from them.
    async with _client(session) as http:
        before = (
            await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        ).json()["counts"]
    author = await _person(session, 97401, "Vera")
    for tg_id in (97402, 97403, 97404):
        user = await helper_factory(tg_id=tg_id)
        profile = await session.get(HelperProfile, user.id)
        assert profile is not None
        profile.published_at = now - timedelta(days=1)
        # Looked at already: off the list and out of its count.
        if tg_id == 97404:
            profile.reviewed_at = now
    for text in ("one", "two"):
        session.add(
            HelpRequest(author_id=author.id, raw_text=text, status=RequestStatus.OPEN)
        )
        session.add(SearchQuery(raw_text=text, results_count=0))
    await session.flush()

    async with _client(session) as http:
        body = (
            await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        ).json()

    counts = body["counts"]
    assert len(body["profiles"]) == 1
    assert counts["profiles_to_review"] - before["profiles_to_review"] == 2
    assert counts["profiles_week"] - before["profiles_week"] == 3
    assert (len(body["unanswered"]), body["counts"]["unanswered"]) == (1, 2)
    assert (len(body["failed_searches"]), body["counts"]["failed_searches"]) == (1, 2)


# ── moderating a profile ────────────────────────────────────────────────


async def _fresh_helper(helper_factory, session: AsyncSession, tg_id: int) -> User:
    user = await helper_factory(tg_id=tg_id, first_name="Ekaterina", last_name="Kova")
    profile = await session.get(HelperProfile, user.id)
    assert profile is not None
    profile.published_at = datetime.now(UTC) - timedelta(days=1)
    profile.about = "Помогу подготовиться к зачёту по матанализу"
    await session.flush()
    return user


async def test_a_profile_opens_for_the_operator_as_the_catalog_names_it(
    session: AsyncSession, helper_factory
) -> None:
    user = await _fresh_helper(helper_factory, session, 97601)

    async with _client(session) as http:
        response = await http.get(
            f"/api/v1/admin/profiles/{user.id}", headers=auth_header(OPERATOR)
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Ekaterina K."
    assert body["status"] == "published"
    assert body["about"] == "Помогу подготовиться к зачёту по матанализу"
    assert body["services"], "what they offer"
    assert body["reviewed_at"] is None
    # Nothing to reach them by: the console moderates, it does not contact.
    assert not {"tg_id", "tg_username", "photo_url"} & set(body)


async def test_an_unknown_profile_is_404(session: AsyncSession) -> None:
    async with _client(session) as http:
        response = await http.get(
            "/api/v1/admin/profiles/999999999", headers=auth_header(OPERATOR)
        )
    assert response.status_code == 404


async def test_keeping_a_profile_takes_it_off_the_new_list_and_leaves_it_listed(
    session: AsyncSession, helper_factory
) -> None:
    user = await _fresh_helper(helper_factory, session, 97602)

    async with _client(session) as http:
        kept = await http.post(
            f"/api/v1/admin/profiles/{user.id}/review", headers=auth_header(OPERATOR)
        )
        body = (
            await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        ).json()

    assert kept.status_code == 200, kept.text
    assert kept.json()["reviewed_at"] is not None
    assert kept.json()["status"] == "published"
    assert user.id not in [row["user_id"] for row in body["profiles"]]
    # Still one of the week's new profiles: reviewing it does not unpublish it.
    assert body["counts"]["profiles_week"] >= 1


async def test_hiding_a_profile_bans_it_so_its_owner_cannot_publish_it_again(
    session: AsyncSession, helper_factory
) -> None:
    user_id = (await _fresh_helper(helper_factory, session, 97603)).id
    # Taken down by its owner: hidden too, but not the operator's doing.
    own = await _fresh_helper(helper_factory, session, 97607)
    own_profile = await session.get(HelperProfile, own.id)
    assert own_profile is not None
    own_profile.status = PublishStatus.HIDDEN
    await session.flush()

    async with _client(session) as http:
        hidden = await http.post(
            f"/api/v1/admin/profiles/{user_id}/hide", headers=auth_header(OPERATOR)
        )
        body = (
            await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        ).json()
        again = await http.put(
            "/api/v1/helper", headers=auth_header(97603), json={"publish": True}
        )

    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["status"] == "banned"
    assert body["counts"]["hidden"] == 1
    assert user_id not in [row["user_id"] for row in body["profiles"]]
    assert [row["user_id"] for row in body["hidden"]] == [user_id]
    assert again.status_code == 403


async def test_a_hidden_profile_comes_back_as_it_was(
    session: AsyncSession, helper_factory
) -> None:
    user = await _fresh_helper(helper_factory, session, 97604)

    async with _client(session) as http:
        await http.post(
            f"/api/v1/admin/profiles/{user.id}/hide", headers=auth_header(OPERATOR)
        )
        restored = await http.post(
            f"/api/v1/admin/profiles/{user.id}/restore", headers=auth_header(OPERATOR)
        )
        body = (
            await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        ).json()

    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "published"
    assert body["hidden"] == []
    # Hiding was a look at it: back in the catalog, not back on the new list.
    assert user.id not in [row["user_id"] for row in body["profiles"]]


@pytest.mark.parametrize("status", [PublishStatus.DRAFT, PublishStatus.HIDDEN])
async def test_only_a_listed_profile_can_be_hidden(
    session: AsyncSession, helper_factory, status: PublishStatus
) -> None:
    """A ban is lifted back to «published», so it may only be put on one: a
    profile its owner took down must not come back listed by «Вернуть»."""
    user = await _fresh_helper(helper_factory, session, 97605)
    profile = await session.get(HelperProfile, user.id)
    assert profile is not None
    profile.status = status
    await session.flush()

    async with _client(session) as http:
        response = await http.post(
            f"/api/v1/admin/profiles/{user.id}/hide", headers=auth_header(OPERATOR)
        )

    assert response.status_code == 409


async def test_only_a_listed_profile_can_be_kept(
    session: AsyncSession, helper_factory
) -> None:
    user = await _fresh_helper(helper_factory, session, 97608)
    profile = await session.get(HelperProfile, user.id)
    assert profile is not None
    profile.status = PublishStatus.BANNED
    await session.flush()

    async with _client(session) as http:
        response = await http.post(
            f"/api/v1/admin/profiles/{user.id}/review", headers=auth_header(OPERATOR)
        )

    assert response.status_code == 409


async def test_a_profile_banned_before_it_was_ever_out_is_out_from_its_restore(
    session: AsyncSession, helper_factory
) -> None:
    """So the owner's next save is not taken for a first publication."""
    user = await _fresh_helper(helper_factory, session, 97609)
    profile = await session.get(HelperProfile, user.id)
    assert profile is not None
    profile.status = PublishStatus.BANNED
    profile.published_at = None
    await session.flush()

    async with _client(session) as http:
        restored = await http.post(
            f"/api/v1/admin/profiles/{user.id}/restore", headers=auth_header(OPERATOR)
        )

    assert restored.json()["published_at"] is not None


async def test_only_a_hidden_profile_can_be_restored(
    session: AsyncSession, helper_factory
) -> None:
    user = await _fresh_helper(helper_factory, session, 97606)
    async with _client(session) as http:
        response = await http.post(
            f"/api/v1/admin/profiles/{user.id}/restore", headers=auth_header(OPERATOR)
        )
    assert response.status_code == 409


# ── partner cards ───────────────────────────────────────────────────────


CARD = {
    "partner": "Pojišťovna VZP",
    "url": "https://example.test/vzp",
    "title": "Страховка для студентов",
    "subtitle": "Комплексная, для визы",
    "price_text": "от 8 900 Kč",
    "context_note": "Без неё не продлят визу.",
    "logo_text": "VZP",
}


async def test_a_new_card_goes_on_the_life_screen(session: AsyncSession) -> None:
    async with _client(session) as http:
        response = await http.post(
            "/api/v1/admin/placements", headers=auth_header(OPERATOR), json=CARD
        )
        listed = (
            await http.get("/api/v1/admin/partners", headers=auth_header(OPERATOR))
        ).json()

    assert response.status_code == 201, response.text
    card = response.json()
    assert card["partner"] == "Pojišťovna VZP"
    assert card["title"] == "Страховка для студентов"
    assert card["slot"] == "screen_life"
    assert card["is_active"] is True
    assert card["impressions"] == 0
    assert any(row["placement_id"] == card["placement_id"] for row in listed)

    placement = await session.get(Placement, card["placement_id"])
    assert placement is not None
    offer = await session.get(PartnerOffer, placement.offer_id)
    assert offer is not None
    assert offer.url == "https://example.test/vzp"
    assert offer.logo_text == "VZP"
    text = (
        await session.scalars(
            select(PartnerOfferI18n).where(PartnerOfferI18n.offer_id == offer.id)
        )
    ).one()
    assert (text.lang, text.price_text, text.context_note) == (
        UiLang.RU,
        "от 8 900 Kč",
        "Без неё не продлят визу.",
    )


async def test_the_card_is_what_the_life_screen_then_shows(session: AsyncSession) -> None:
    reader = await _person(session, STRANGER, "Jana")
    reader.ui_lang = UiLang.CS
    # The slot shows three cards; the seeded ones would crowd this one out.
    for other in (await session.scalars(select(Placement))).all():
        other.is_active = False
    await session.flush()
    async with _client(session) as http:
        await http.post(
            "/api/v1/admin/placements", headers=auth_header(OPERATOR), json=CARD
        )
        shown = (
            await http.get(
                "/api/v1/placements",
                params={"slot": "screen_life"},
                headers=auth_header(STRANGER),
            )
        ).json()

    # In Czech too: a card shows the first text it has when none is in yours.
    assert any(row["title"] == "Страховка для студентов" for row in shown)


async def test_a_partner_of_the_same_name_is_reused(session: AsyncSession) -> None:
    async with _client(session) as http:
        for name in ("Pojišťovna VZP", "  pojišťovna vzp "):
            response = await http.post(
                "/api/v1/admin/placements",
                headers=auth_header(OPERATOR),
                json={**CARD, "partner": name},
            )
            assert response.status_code == 201, response.text

    partners = (
        await session.scalars(
            select(Partner).where(func.lower(Partner.name) == "pojišťovna vzp")
        )
    ).all()
    assert len(partners) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"url": "http://example.test/vzp"},
        {"url": "javascript:alert(1)"},
        {"title": "   "},
        {"partner": ""},
        {"logo_text": "TOOLONG"},
        {"url": "https://exa mple.test/vzp"},
    ],
)
async def test_a_card_that_would_mislead_is_refused(
    session: AsyncSession, change: dict[str, str]
) -> None:
    async with _client(session) as http:
        response = await http.post(
            "/api/v1/admin/placements",
            headers=auth_header(OPERATOR),
            json={**CARD, **change},
        )

    assert response.status_code == 422


async def test_a_new_card_goes_first(session: AsyncSession) -> None:
    """A slot shows three; the one just added must be among them, whatever the
    others' priorities."""
    async with _client(session) as http:
        for title in ("Первая", "Вторая", "Третья"):
            await http.post(
                "/api/v1/admin/placements",
                headers=auth_header(OPERATOR),
                json={**CARD, "title": title},
            )
        latest = (
            await http.post(
                "/api/v1/admin/placements",
                headers=auth_header(OPERATOR),
                json={**CARD, "title": "Новейшая"},
            )
        ).json()
        shown = (
            await http.get(
                "/api/v1/placements",
                params={"slot": "screen_life"},
                headers=auth_header(STRANGER),
            )
        ).json()

    assert shown[0]["id"] == latest["placement_id"]


async def test_a_card_is_switched_off_and_on(session: AsyncSession) -> None:
    # Only this card on the screen, so its absence means it is off.
    for other in (await session.scalars(select(Placement))).all():
        other.is_active = False
    await session.flush()
    async with _client(session) as http:
        card = (
            await http.post(
                "/api/v1/admin/placements", headers=auth_header(OPERATOR), json=CARD
            )
        ).json()
        off = await http.patch(
            f"/api/v1/admin/placements/{card['placement_id']}",
            headers=auth_header(OPERATOR),
            json={"is_active": False},
        )
        shown = (
            await http.get(
                "/api/v1/placements",
                params={"slot": "screen_life"},
                headers=auth_header(STRANGER),
            )
        ).json()
        on = await http.patch(
            f"/api/v1/admin/placements/{card['placement_id']}",
            headers=auth_header(OPERATOR),
            json={"is_active": True},
        )
        shown_again = (
            await http.get(
                "/api/v1/placements",
                params={"slot": "screen_life"},
                headers=auth_header(STRANGER),
            )
        ).json()

    assert off.status_code == 200, off.text
    assert off.json()["is_active"] is False
    assert all(row["title"] != CARD["title"] for row in shown)
    assert on.json()["is_active"] is True
    assert any(row["title"] == CARD["title"] for row in shown_again)


async def test_switching_a_card_that_does_not_exist_is_a_404(
    session: AsyncSession,
) -> None:
    async with _client(session) as http:
        response = await http.patch(
            "/api/v1/admin/placements/999999",
            headers=auth_header(OPERATOR),
            json={"is_active": False},
        )

    assert response.status_code == 404
