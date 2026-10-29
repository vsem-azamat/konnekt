import pytest

from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio


async def test_health_needs_no_auth(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


async def test_everything_else_needs_auth(client):
    for path in ("/api/v1/me", "/api/v1/home", "/api/v1/taxonomy/service-types"):
        assert (await client.get(path)).status_code == 401, path


async def test_wrong_scheme_is_rejected(client):
    response = await client.get(
        "/api/v1/me", headers={"Authorization": "Bearer something"}
    )
    assert response.status_code == 401
    assert "tma" in response.json()["detail"]


async def test_first_request_registers_the_user(client):
    response = await client.get(
        "/api/v1/me", headers=auth_header(90101, first_name="Nová")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tg_id"] == 90101
    assert body["name"] == "Nová"
    assert body["is_helper"] is False
    assert body["avatar"]["initials"] == "N"


async def test_language_preference_persists(client):
    headers = auth_header(90102)
    assert (
        await client.patch("/api/v1/me", json={"ui_lang": "cs"}, headers=headers)
    ).status_code == 200
    body = (await client.get("/api/v1/me", headers=headers)).json()
    assert body["ui_lang"] == "cs"


async def test_service_types_are_localised(client):
    headers = auth_header(90103)
    ru = (await client.get("/api/v1/taxonomy/service-types", headers=headers)).json()
    await client.patch("/api/v1/me", json={"ui_lang": "cs"}, headers=headers)
    cs = (await client.get("/api/v1/taxonomy/service-types", headers=headers)).json()

    assert [s["code"] for s in ru] == [s["code"] for s in cs]
    ru_names = {s["code"]: s["name"] for s in ru}
    cs_names = {s["code"]: s["name"] for s in cs}
    assert ru_names["tutoring"] == "Репетитор по предмету"
    assert cs_names["tutoring"] == "Doučování předmětu"


async def test_service_types_carry_their_group(client):
    body = (
        await client.get("/api/v1/taxonomy/service-types", headers=auth_header(90107))
    ).json()
    groups = {s["code"]: s["group"] for s in body}
    assert groups["tutoring"] == "study"
    assert groups["nostrification"] == "entrance"
    assert groups["insurance"] == "life"

    # What the price is per, so the form does not have to guess. A thesis
    # priced by the hour reads as ten times too little.
    units = {s["code"]: s["default_price_unit"] for s in body}
    assert units["tutoring"] == "hour"
    assert units["writing"] == "work"
    assert units["insurance"] == "item"


async def test_a_category_keeps_its_colour_across_screens(client):
    """The same tile is drawn twice — on the home screen and on `/offer`.

    A category that is green in the catalog and pink where it is offered reads
    as two different things, so the colour comes from the server rather than
    from each screen's own idea of position.
    """
    headers = auth_header(90109)
    home = (await client.get("/api/v1/home", headers=headers)).json()["people"]
    types = (await client.get("/api/v1/taxonomy/service-types", headers=headers)).json()

    on_home = {s["code"]: s["tone"] for s in home}
    on_offer = {s["code"]: s["tone"] for s in types}
    assert on_offer == on_home


async def test_home_lists_every_service_type(client):
    body = (await client.get("/api/v1/home", headers=auth_header(90104))).json()
    codes = [s["code"] for s in body["people"]]
    assert "tutoring" in codes
    assert "nostrification" in codes
    assert "insurance" in codes
    # Tones cycle so the client can colour tiles without deciding anything.
    assert all(0 <= s["tone"] < 6 for s in body["people"])


async def test_home_hands_over_whole_groups(client):
    """The client renders one heading per group and then its tiles.

    So the order has to be grouped: a section that came back after a different
    group had started would be drawn under the wrong heading, or silently
    dropped by a client that groups as it goes.
    """
    body = (await client.get("/api/v1/home", headers=auth_header(90108))).json()
    order = [s["group"] for s in body["people"]]
    assert order, "home returned no service types"

    seen: list[str] = []
    for group in order:
        if not seen or seen[-1] != group:
            assert group not in seen, f"group {group} resumes after {seen[-1]}"
            seen.append(group)
    assert seen == ["study", "entrance", "life"]


async def test_subject_search_accepts_slang(client):
    response = await client.get(
        "/api/v1/taxonomy/subjects", params={"q": "линал"}, headers=auth_header(90105)
    )
    assert response.status_code == 200
    assert response.json()[0]["slug"] == "linearni-algebra"


async def test_subject_browse_walks_the_tree(client):
    headers = auth_header(90106)
    roots = (await client.get("/api/v1/taxonomy/subjects", headers=headers)).json()
    assert roots, "no root subjects seeded"
    assert all(r["parent_id"] is None for r in roots)
    assert any(r["has_children"] for r in roots)

    parent = next(r for r in roots if r["has_children"])
    children = (
        await client.get(
            "/api/v1/taxonomy/subjects",
            params={"parent_id": parent["id"]},
            headers=headers,
        )
    ).json()
    assert children
    assert all(c["parent_id"] == parent["id"] for c in children)


async def test_parse_returns_chips_and_logs_the_query(client, session):
    from sqlalchemy import func, select

    from students_cz.db.models import SearchQuery

    before = await session.scalar(select(func.count(SearchQuery.id)))
    response = await client.post(
        "/api/v1/search/parse",
        json={"text": "нужен матан на ČVUT, экзамен 14 февраля"},
        headers=auth_header(90107),
    )
    assert response.status_code == 200
    body = response.json()
    kinds = {c["kind"] for c in body["chips"]}
    assert "subject" in kinds
    assert "deadline" in kinds

    after = await session.scalar(select(func.count(SearchQuery.id)))
    assert after == before + 1, "the query was not logged"


async def test_parse_says_so_when_it_understood_nothing(client):
    body = (
        await client.post(
            "/api/v1/search/parse",
            json={"text": "zzzz xxxx"},
            headers=auth_header(90108),
        )
    ).json()
    assert body["chips"] == []
    assert body["note"]["code"] == "parse.nothing_recognised"
    assert body["clarify"] is None


async def test_clarify_is_asked_only_when_it_narrows(client):
    """A query that already names the kind of help needs no question."""
    named = (
        await client.post(
            "/api/v1/search/parse",
            json={"text": "помощь на экзамене по матану"},
            headers=auth_header(90109),
        )
    ).json()
    assert named["clarify"] is None

    unnamed = (
        await client.post(
            "/api/v1/search/parse",
            json={"text": "матан"},
            headers=auth_header(90110),
        )
    ).json()
    assert unnamed["clarify"]["code"] == "clarify.when"


async def test_parse_counts_only_what_the_search_will_show(
    client, helper_factory, session
):
    """The number promised is the number delivered.

    The screen shows a budget chip and then a count. Computing that count
    without the budget promises people who will not be in the list, and writes
    the same wrong number into `search_queries.results_count`, which is read as
    the ranked list of what the catalog is missing.
    """
    from sqlalchemy import select

    from students_cz.db.models import Subject

    await helper_factory(tg_id=91021, first_name="Cheap", price=400)
    await helper_factory(tg_id=91022, first_name="Dear", price=900)
    await session.flush()

    body = (
        await client.post(
            "/api/v1/search/parse",
            json={"text": "матан до 500 крон"},
            headers=auth_header(90121),
        )
    ).json()

    budget = [c for c in body["chips"] if c["kind"] == "budget"]
    assert budget and budget[0]["value"] == 500, body["chips"]

    # Against the search itself rather than a literal, because the seed brings
    # its own helpers on this subject and any fixed number would be a statement
    # about the seed. What is being pinned is that the two agree.
    subject = await session.scalar(
        select(Subject).where(Subject.slug == "matematicka-analyza")
    )
    params = {"subject_id": subject.id}
    listed = (
        await client.get(
            "/api/v1/search",
            params={**params, "max_price": 500},
            headers=auth_header(90121),
        )
    ).json()
    assert body["matches"] == listed["total"]

    # And the filter has to be doing something, or the assertion above would
    # hold just as well with the bug in place. `Dear` costs 900.
    everyone = (
        await client.get("/api/v1/search", params=params, headers=auth_header(90121))
    ).json()
    assert listed["total"] < everyone["total"]


async def test_search_finds_a_published_helper(client, helper_factory, session):
    await helper_factory(tg_id=91001, first_name="Marek", deals=8)
    await session.flush()

    from sqlalchemy import select

    from students_cz.db.models import Subject

    subject = await session.scalar(
        select(Subject).where(Subject.slug == "matematicka-analyza")
    )

    body = (
        await client.get(
            "/api/v1/search",
            params={"subject_id": subject.id},
            headers=auth_header(90111),
        )
    ).json()
    assert body["total"] >= 1
    names = [r["name"] for r in body["results"]]
    assert "Marek N." in names, names


async def test_helper_page_404s_for_a_draft(client, session):
    from students_cz.db.models import HelperProfile, User
    from students_cz.db.models.enums import PublishStatus

    user = User(tg_id=91002, first_name="Draft")
    session.add(user)
    await session.flush()
    session.add(HelperProfile(user_id=user.id, status=PublishStatus.DRAFT))
    await session.flush()

    response = await client.get(f"/api/v1/helpers/{user.id}", headers=auth_header(90112))
    assert response.status_code == 404


async def test_a_profile_does_not_show_a_rating(client, helper_factory, session):
    """Hidden until lessons go through the catalog: nobody can leave a review
    yet, so a number here would be one we made up. The field stays for later."""
    from students_cz.db.models import HelperProfile

    helper = await helper_factory(tg_id=91003, deals=8)
    profile = await session.get(HelperProfile, helper.id)
    profile.rating = 4.9
    await session.flush()

    body = (
        await client.get(f"/api/v1/helpers/{helper.id}", headers=auth_header(90113))
    ).json()

    assert [stat["code"] for stat in body["stats"]] == ["stat.deals"]


async def test_a_rating_nobody_sees_does_not_order_the_list(
    client, helper_factory, session
):
    from sqlalchemy import select

    from students_cz.db.models import HelperProfile, Subject

    unrated = await helper_factory(tg_id=91004, first_name="Unrated", deals=5)
    rated = await helper_factory(tg_id=91005, first_name="Rated", deals=5)
    (await session.get(HelperProfile, rated.id)).rating = 5.0
    await session.flush()
    subject = await session.scalar(
        select(Subject).where(Subject.slug == "matematicka-analyza")
    )

    body = (
        await client.get(
            "/api/v1/search",
            params={"subject_id": subject.id},
            headers=auth_header(90114),
        )
    ).json()

    ids = [r["user_id"] for r in body["results"]]
    assert ids.index(unrated.id) < ids.index(rated.id)


async def test_creating_a_request_reads_the_text(client):
    """The form is one field; everything else comes out of the sentence."""
    response = await client.post(
        "/api/v1/requests",
        json={"text": "нужен матан на ČVUT, экзамен 14 февраля, до 700 kč"},
        headers=auth_header(90201),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["subject"] == "Математический анализ"
    assert body["institution"] == "ČVUT"
    assert body["deadline_on"].endswith("-02-14")
    assert body["status"] == "open"
    assert body["responses_count"] == 0


async def test_requests_are_listed_newest_first(client):
    headers = auth_header(90202)
    await client.post("/api/v1/requests", json={"text": "линал на ČVUT"}, headers=headers)
    await client.post("/api/v1/requests", json={"text": "чешский B2"}, headers=headers)

    body = (await client.get("/api/v1/requests", headers=headers)).json()
    assert len(body) == 2
    assert body[0]["text"] == "чешский B2"


async def test_a_request_without_a_deadline_still_expires(client, session):
    from sqlalchemy import select

    from students_cz.db.models import HelpRequest

    created = (
        await client.post(
            "/api/v1/requests",
            json={"text": "помогите с физикой"},
            headers=auth_header(90203),
        )
    ).json()
    row = await session.scalar(select(HelpRequest).where(HelpRequest.id == created["id"]))
    assert row.expires_at is not None, "a request with no end date would hang forever"


async def test_only_the_author_can_close_a_request(client):
    created = (
        await client.post(
            "/api/v1/requests", json={"text": "матан"}, headers=auth_header(90204)
        )
    ).json()
    other = await client.post(
        f"/api/v1/requests/{created['id']}/close", headers=auth_header(90205)
    )
    assert other.status_code == 404

    mine = await client.post(
        f"/api/v1/requests/{created['id']}/close", headers=auth_header(90204)
    )
    assert mine.status_code == 200
    assert mine.json()["status"] == "closed"


async def test_reading_an_introduction_is_gone(client):
    """Onboarding is a grid of tiles now; nothing writes a paragraph any more.

    The endpoint that read one is removed rather than left standing, because a
    parser nobody calls is a parser nobody notices breaking.
    """
    response = await client.post(
        "/api/v1/helper/intro",
        json={"text": "Могу подтянуть матан. Беру 500 в час."},
        headers=auth_header(90301),
    )
    assert response.status_code == 404


async def test_reading_a_query_still_works(client):
    """The other parser stays: the student's search box uses it."""
    body = (
        await client.post(
            "/api/v1/search/parse",
            json={"text": "нужен матан на ČVUT"},
            headers=auth_header(90302),
        )
    ).json()
    assert [c["label"] for c in body["chips"] if c["kind"] == "subject"]


async def test_publishing_makes_the_profile_findable(client, session):
    from sqlalchemy import select

    from students_cz.db.models import ServiceType, Subject

    headers = auth_header(90302, first_name="Nový")
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    subject = await session.scalar(
        select(Subject).where(Subject.slug == "linearni-algebra")
    )

    before = (
        await client.get(
            "/api/v1/search", params={"subject_id": subject.id}, headers=headers
        )
    ).json()["total"]

    saved = await client.put(
        "/api/v1/helper",
        json={
            "headline": "ČVUT FEL · 3. ročník",
            "about": "Podtahuju linearni algebru.",
            "work_format": "both",
            "publish": True,
            "offers": [
                {
                    "service_type_id": service.id,
                    "subject_id": subject.id,
                    "price_amount": 500,
                    "price_unit": "hour",
                    "langs": ["ru", "cs"],
                }
            ],
        },
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["is_helper"] is True
    assert saved.json()["helper_status"] == "published"

    after = (
        await client.get(
            "/api/v1/search", params={"subject_id": subject.id}, headers=headers
        )
    ).json()
    assert after["total"] == before + 1


async def test_an_unpublished_profile_stays_out_of_search(client, session):
    from sqlalchemy import select

    from students_cz.db.models import ServiceType, Subject

    headers = auth_header(90303)
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    subject = await session.scalar(select(Subject).where(Subject.slug == "genetika"))

    await client.put(
        "/api/v1/helper",
        json={
            "publish": False,
            "offers": [{"service_type_id": service.id, "subject_id": subject.id}],
        },
        headers=headers,
    )
    found = (
        await client.get(
            "/api/v1/search", params={"subject_id": subject.id}, headers=headers
        )
    ).json()
    assert found["total"] == 0


async def test_offers_are_replaced_not_appended(client, session):
    """The client sends the whole set; a diff would leave deleted rows behind."""
    from sqlalchemy import select

    from students_cz.db.models import ServiceType, Subject

    headers = auth_header(90304)
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    first = await session.scalar(select(Subject).where(Subject.slug == "fyzika-1"))
    second = await session.scalar(select(Subject).where(Subject.slug == "fyzika-2"))

    async def total(subject_id: int) -> int:
        response = await client.get(
            "/api/v1/search", params={"subject_id": subject_id}, headers=headers
        )
        return response.json()["total"]

    # Deltas, not absolutes: the development database carries demo helpers and
    # one of them already teaches physics.
    before_first, before_second = await total(first.id), await total(second.id)

    for subject in (first, second):
        await client.put(
            "/api/v1/helper",
            json={
                "publish": True,
                "offers": [{"service_type_id": service.id, "subject_id": subject.id}],
            },
            headers=headers,
        )

    assert await total(first.id) == before_first, "the replaced offer survived"
    assert await total(second.id) == before_second + 1


async def test_an_unknown_service_type_is_refused(client):
    response = await client.put(
        "/api/v1/helper",
        json={"offers": [{"service_type_id": 999999}]},
        headers=auth_header(90305),
    )
    assert response.status_code == 422


async def test_hiding_a_published_profile_takes_it_out_of_the_catalog(client, session):
    """ "Hide me" has to actually hide; it used to be a no-op once published."""
    from sqlalchemy import select

    from students_cz.db.models import ServiceType, Subject

    headers = auth_header(90401)
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    subject = await session.scalar(select(Subject).where(Subject.slug == "histologie"))
    offers = [{"service_type_id": service.id, "subject_id": subject.id}]

    await client.put(
        "/api/v1/helper", json={"publish": True, "offers": offers}, headers=headers
    )
    published = (
        await client.get(
            "/api/v1/search", params={"subject_id": subject.id}, headers=headers
        )
    ).json()["total"]
    assert published == 1

    hidden = await client.put(
        "/api/v1/helper", json={"publish": False, "offers": offers}, headers=headers
    )
    assert hidden.json()["helper_status"] == "hidden"
    assert (
        await client.get(
            "/api/v1/search", params={"subject_id": subject.id}, headers=headers
        )
    ).json()["total"] == 0


async def test_a_banned_profile_cannot_publish_itself(client, session):
    from students_cz.db.models import HelperProfile
    from students_cz.db.models.enums import PublishStatus

    headers = auth_header(90402)
    await client.get("/api/v1/me", headers=headers)  # registers the account
    await client.put("/api/v1/helper", json={"publish": False}, headers=headers)

    from sqlalchemy import select

    from students_cz.db.models import User

    user = await session.scalar(select(User).where(User.tg_id == 90402))
    helper = await session.get(HelperProfile, user.id)
    helper.status = PublishStatus.BANNED
    await session.commit()

    # Saved, and not listed: only an operator lifts a ban.
    saved = await client.put("/api/v1/helper", json={"publish": True}, headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["helper_status"] == "banned"


async def test_the_same_axes_twice_is_a_422_not_a_traceback(client, session):
    from sqlalchemy import select

    from students_cz.db.models import ServiceType, Subject

    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    subject = await session.scalar(select(Subject).where(Subject.slug == "genetika"))
    duplicate = {"service_type_id": service.id, "subject_id": subject.id}

    response = await client.put(
        "/api/v1/helper",
        json={"offers": [duplicate, duplicate]},
        headers=auth_header(90403),
    )
    assert response.status_code == 422
    assert "duplicate" in response.json()["detail"]


async def test_unknown_foreign_keys_are_named_not_crashed(client):
    headers = auth_header(90404)
    bad_institution = await client.patch(
        "/api/v1/me", json={"institution_id": 999999}, headers=headers
    )
    assert bad_institution.status_code == 422
    assert "institution_id" in bad_institution.json()["detail"]

    bad_subject = await client.post(
        "/api/v1/requests",
        json={"text": "матан", "subject_id": 999999},
        headers=headers,
    )
    assert bad_subject.status_code == 422


async def test_one_person_appears_once_however_many_offers_match(
    client, session, helper_factory
):
    """Two matching offers is a reason to rank higher, not to show twice."""
    from sqlalchemy import select

    from students_cz.db.models import Offer, ServiceType, Subject

    user = await helper_factory(tg_id=91101, subject_slug="anatomie")
    subject = await session.scalar(select(Subject).where(Subject.slug == "anatomie"))
    second = await session.scalar(
        select(ServiceType).where(ServiceType.code == "exam_prep")
    )
    session.add(
        Offer(
            helper_id=user.id,
            service_type_id=second.id,
            subject_id=subject.id,
            price_amount=800,
        )
    )
    await session.flush()

    body = (
        await client.get(
            "/api/v1/search",
            params={"subject_id": subject.id},
            headers=auth_header(90405),
        )
    ).json()
    assert body["total"] == 1
    assert len(body["results"]) == 1


async def test_clicking_an_unknown_placement_is_a_404(client):
    response = await client.post(
        "/api/v1/placements/999999/click", headers=auth_header(90406)
    )
    assert response.status_code == 404


async def test_an_unknown_placement_slot_is_rejected(client):
    response = await client.get(
        "/api/v1/placements", params={"slot": "nowhere"}, headers=auth_header(90407)
    )
    assert response.status_code == 422


async def test_partner_blocks_are_matched_by_condition(client):
    """Sworn translation belongs on the nostrification screen, not everywhere."""
    on_topic = (
        await client.get(
            "/api/v1/placements",
            params={"slot": "screen_nostrification", "service_type": "nostrification"},
            headers=auth_header(90408),
        )
    ).json()
    assert any("překlad" in p["title"] or "перевод" in p["title"] for p in on_topic)

    off_topic = (
        await client.get(
            "/api/v1/placements",
            params={"slot": "screen_nostrification"},
            headers=auth_header(90409),
        )
    ).json()
    assert off_topic == []


async def test_paging_bounds_are_enforced(client):
    headers = auth_header(90410)
    assert (
        await client.get("/api/v1/search", params={"offset": -1}, headers=headers)
    ).status_code == 422
    assert (
        await client.get("/api/v1/search", params={"limit": 0}, headers=headers)
    ).status_code == 422


async def test_a_matching_institution_ranks_above_one_without(
    client, session, helper_factory
):
    """`institution_id = :x` is NULL when the offer has none.

    Postgres sorts NULLs first under DESC, so the offers that did not match the
    requested school were coming out above the ones that did.
    """
    from sqlalchemy import select

    from students_cz.db.models import Institution, Subject

    subject = await session.scalar(select(Subject).where(Subject.slug == "biochemie"))
    cvut = await session.scalar(select(Institution).where(Institution.code == "cvut"))

    await helper_factory(
        tg_id=91201,
        first_name="Unattached",
        last_name=None,
        subject_slug="biochemie",
        institution_id=None,
        price=100,
    )
    await helper_factory(
        tg_id=91202,
        first_name="Attached",
        last_name=None,
        subject_slug="biochemie",
        institution_id=cvut.id,
        price=900,
    )
    await session.flush()

    body = (
        await client.get(
            "/api/v1/search",
            params={"subject_id": subject.id, "institution_id": cvut.id},
            headers=auth_header(90501),
        )
    ).json()

    names = [r["name"] for r in body["results"]]
    assert names[0] == "Attached", names
    assert body["results"][0]["reason"]["code"].startswith("reason.same")


async def test_search_reports_what_it_is_filtering_on(client, session):
    from sqlalchemy import select

    from students_cz.db.models import Institution, Subject

    subject = await session.scalar(
        select(Subject).where(Subject.slug == "matematicka-analyza")
    )
    cvut = await session.scalar(select(Institution).where(Institution.code == "cvut"))

    body = (
        await client.get(
            "/api/v1/search",
            params={
                "subject_id": subject.id,
                "institution_id": cvut.id,
                "max_price": 700,
            },
            headers=auth_header(90502),
        )
    ).json()

    kinds = {chip["kind"]: chip["label"] for chip in body["chips"]}
    assert kinds["subject"] == "Математический анализ"
    assert kinds["institution"] == "ČVUT"
    assert kinds["budget"] == "700"


async def test_opening_the_app_is_recorded(client, session):
    from sqlalchemy import select

    from students_cz.db.models import UserEvent
    from students_cz.db.models.enums import UserEventKind

    await client.get("/api/v1/home", headers=auth_header(90601))
    kinds = (await session.scalars(select(UserEvent.kind))).all()
    assert UserEventKind.APP_OPEN in kinds


async def test_starting_a_conversation_is_recorded_and_returns_the_link(
    client, session, helper_factory
):
    """The chat happens in Telegram; what we keep is that it started.

    Response times and deal counts on a card are only worth showing if they
    come from something observed rather than claimed.
    """
    from sqlalchemy import select

    from students_cz.db.models import Contact, UserEvent
    from students_cz.db.models.enums import UserEventKind

    helper = await helper_factory(tg_id=91301, first_name="Marek")
    helper.tg_username = "marek_teaches"
    await session.flush()

    response = await client.post(
        f"/api/v1/helpers/{helper.id}/contact", headers=auth_header(90602)
    )
    assert response.status_code == 200
    assert response.json()["telegram_url"] == "https://t.me/marek_teaches"

    assert (
        await session.scalar(select(Contact).where(Contact.helper_id == helper.id))
        is not None
    )
    kinds = (await session.scalars(select(UserEvent.kind))).all()
    assert UserEventKind.CONTACT in kinds


async def test_a_helper_without_a_username_cannot_be_written_to(
    client, session, helper_factory
):
    helper = await helper_factory(tg_id=91302, first_name="Tichý")
    helper.tg_username = None
    await session.flush()

    response = await client.post(
        f"/api/v1/helpers/{helper.id}/contact", headers=auth_header(90603)
    )
    assert response.status_code == 409


async def test_you_cannot_contact_yourself(client, session, helper_factory):
    from sqlalchemy import select

    from students_cz.db.models import User

    await client.get("/api/v1/me", headers=auth_header(90604))
    me = await session.scalar(select(User).where(User.tg_id == 90604))

    response = await client.post(
        f"/api/v1/helpers/{me.id}/contact", headers=auth_header(90604)
    )
    assert response.status_code == 400


async def test_an_errand_says_what_it_covers_and_in_the_helpers_own_words(
    client, session
):
    """The checklist round-trips, and reaches the person reading the profile.

    An errand has no subject and no institution, so without these two the
    catalog shows a row saying "Insurance" and nothing else — the same row for
    everybody offering it.
    """
    from sqlalchemy import select

    from students_cz.db.models import ServiceOption, ServiceType

    insurance = await session.scalar(
        select(ServiceType).where(ServiceType.code == "insurance")
    )
    options = (
        await session.scalars(
            select(ServiceOption)
            .where(ServiceOption.service_type_id == insurance.id)
            .order_by(ServiceOption.sort)
        )
    ).all()
    assert len(options) >= 2, "the seeded checklist is missing"

    headers = auth_header(90501)
    saved = await client.put(
        "/api/v1/helper",
        json={
            "publish": True,
            "offers": [
                {
                    "service_type_id": insurance.id,
                    "option_ids": [options[0].id, options[1].id],
                    "note": "Оформляю за день, отвечаю по-русски и по-чешски.",
                }
            ],
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text

    mine = (await client.get("/api/v1/helper", headers=headers)).json()
    assert mine["offers"][0]["option_ids"] == [options[0].id, options[1].id]
    assert mine["offers"][0]["note"].startswith("Оформляю")

    # And the way a student sees it: labels, not ids.
    me = (await client.get("/api/v1/me", headers=headers)).json()
    page = (await client.get(f"/api/v1/helpers/{me['id']}", headers=headers)).json()
    offer = next(o for o in page["offers"] if o["service_type"] == "insurance")
    assert offer["options"], "the checklist did not reach the person reading it"
    assert all(isinstance(label, str) and label for label in offer["options"])
    assert offer["note"].startswith("Оформляю")


async def test_a_checklist_line_from_another_service_is_dropped(client, session):
    """A stale client must not attach insurance's lines to a bank statement.

    Nothing downstream would notice: the array references nothing, so the
    labels would simply read as somebody else's.
    """
    from sqlalchemy import select

    from students_cz.db.models import ServiceOption, ServiceType

    bank = await session.scalar(
        select(ServiceType).where(ServiceType.code == "bank_letter")
    )
    insurance = await session.scalar(
        select(ServiceType).where(ServiceType.code == "insurance")
    )
    stranger = await session.scalar(
        select(ServiceOption).where(ServiceOption.service_type_id == insurance.id)
    )

    headers = auth_header(90502)
    saved = await client.put(
        "/api/v1/helper",
        json={
            "publish": True,
            "offers": [{"service_type_id": bank.id, "option_ids": [stranger.id]}],
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text

    mine = (await client.get("/api/v1/helper", headers=headers)).json()
    assert mine["offers"][0]["option_ids"] == []


async def test_a_save_that_says_nothing_about_the_checklist_keeps_it(client, session):
    """A save that says nothing about the checklist must not erase one.

    `OfferIn` defaults `option_ids` to `[]`, so a caller that saves an offer
    without mentioning the checklist would wipe what the prices screen wrote,
    silently, on an unrelated save. The shipped client sends both fields; this
    holds the rule for the next one.
    """
    from sqlalchemy import select

    from students_cz.db.models import ServiceOption, ServiceType

    insurance = await session.scalar(
        select(ServiceType).where(ServiceType.code == "insurance")
    )
    option = await session.scalar(
        select(ServiceOption).where(ServiceOption.service_type_id == insurance.id)
    )

    headers = auth_header(90503)
    await client.put(
        "/api/v1/helper",
        json={
            "publish": True,
            "offers": [
                {
                    "service_type_id": insurance.id,
                    "option_ids": [option.id],
                    "note": "Оформляю за день.",
                }
            ],
        },
        headers=headers,
    )

    # The shape the profile screen sends: prices and languages, nothing else.
    again = await client.put(
        "/api/v1/helper",
        json={
            "publish": True,
            "offers": [{"service_type_id": insurance.id, "price_amount": 900}],
        },
        headers=headers,
    )
    assert again.status_code == 200, again.text

    mine = (await client.get("/api/v1/helper", headers=headers)).json()
    assert mine["offers"][0]["option_ids"] == [option.id]
    assert mine["offers"][0]["note"] == "Оформляю за день."
    assert mine["offers"][0]["price_amount"] == 900


async def test_the_checklist_reaches_the_screen_that_ticks_it(client, session):
    """`/taxonomy/service-types` is the only place the boxes come from.

    So the three things the screen depends on are asserted here rather than
    inferred from the database: the labels are translated, they arrive in the
    catalog's order, and a withdrawn line is not offered.
    """
    from sqlalchemy import select

    from students_cz.db.models import ServiceOption, ServiceType

    headers = auth_header(90505)
    ru = (await client.get("/api/v1/taxonomy/service-types", headers=headers)).json()
    insurance_ru = next(s for s in ru if s["code"] == "insurance")
    assert insurance_ru["options"], "the checklist did not reach the screen"
    assert any(o["label"] == "Оформлю VZP или PVZP" for o in insurance_ru["options"])

    # A lesson asks no checklist at all, and says so with an empty list rather
    # than by leaving the key out — the client renders the block conditionally.
    assert next(s for s in ru if s["code"] == "tutoring")["options"] == []

    await client.patch("/api/v1/me", json={"ui_lang": "cs"}, headers=headers)
    cs = (await client.get("/api/v1/taxonomy/service-types", headers=headers)).json()
    insurance_cs = next(s for s in cs if s["code"] == "insurance")
    assert [o["code"] for o in insurance_cs["options"]] == [
        o["code"] for o in insurance_ru["options"]
    ]
    assert any(o["label"] == "Vyřídím VZP nebo PVZP" for o in insurance_cs["options"])

    # The order is the catalog's `sort`, not whatever the database returns.
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "insurance")
    )
    stored = (
        await session.scalars(
            select(ServiceOption)
            .where(
                ServiceOption.service_type_id == service.id,
                ServiceOption.is_active.is_(True),
            )
            .order_by(ServiceOption.sort)
        )
    ).all()
    assert [o["code"] for o in insurance_ru["options"]] == [r.code for r in stored]

    # And a line withdrawn from the catalog stops being offered.
    stored[0].is_active = False
    await session.flush()
    again = (await client.get("/api/v1/taxonomy/service-types", headers=headers)).json()
    offered = next(s for s in again if s["code"] == "insurance")["options"]
    assert [o["code"] for o in offered] == [r.code for r in stored[1:]]


async def test_a_turnaround_reaches_the_person_reading_it(client, session):
    """The one question a written work is asked that a lesson is not."""
    from sqlalchemy import select

    from students_cz.db.models import ServiceType

    writing = await session.scalar(
        select(ServiceType).where(ServiceType.code == "writing")
    )
    headers = auth_header(90702)
    saved = await client.put(
        "/api/v1/helper",
        json={
            "publish": True,
            "offers": [
                {
                    "service_type_id": writing.id,
                    "price_amount": 3000,
                    "price_unit": "work",
                    "turnaround_days": 7,
                }
            ],
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text

    mine = (await client.get("/api/v1/helper", headers=headers)).json()
    assert mine["offers"][0]["turnaround_days"] == 7

    me = (await client.get("/api/v1/me", headers=headers)).json()
    page = (await client.get(f"/api/v1/helpers/{me['id']}", headers=headers)).json()
    offer = next(o for o in page["offers"] if o["service_type"] == "writing")
    assert offer["turnaround_days"] == 7


async def test_a_save_that_says_nothing_about_the_turnaround_keeps_it(client, session):
    """The same rule the checklist follows, and for the same reason.

    `OfferIn` defaults `turnaround_days` to `None`, so a caller that saves an
    offer without mentioning it would quietly move the writer from "a week" to
    "we will agree".
    """
    from sqlalchemy import select

    from students_cz.db.models import ServiceType

    writing = await session.scalar(
        select(ServiceType).where(ServiceType.code == "writing")
    )
    headers = auth_header(90703)
    await client.put(
        "/api/v1/helper",
        json={
            "publish": True,
            "offers": [{"service_type_id": writing.id, "turnaround_days": 14}],
        },
        headers=headers,
    )

    await client.put(
        "/api/v1/helper",
        json={
            "publish": True,
            "offers": [{"service_type_id": writing.id, "price_amount": 2500}],
        },
        headers=headers,
    )

    mine = (await client.get("/api/v1/helper", headers=headers)).json()
    assert mine["offers"][0]["turnaround_days"] == 14, "the turnaround was erased"


async def test_a_turnaround_on_a_lesson_is_dropped(client, session):
    """Only a written work is asked when, so only one can answer.

    The same filter the checklist gets, and for a visible reason: a stale or
    hand-rolled client could otherwise put «Срок: неделя» under a tutoring
    offer, on a form that never asked.
    """
    from sqlalchemy import select

    from students_cz.db.models import ServiceType

    tutoring = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    headers = auth_header(90704)
    saved = await client.put(
        "/api/v1/helper",
        json={
            "publish": True,
            "offers": [{"service_type_id": tutoring.id, "turnaround_days": 7}],
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text

    mine = (await client.get("/api/v1/helper", headers=headers)).json()
    assert mine["offers"][0]["turnaround_days"] is None


async def test_a_turnaround_must_be_a_real_number_of_days(session):
    """`NULL` says "we will agree"; zero and minus three say nothing at all.

    The form only ever sends one of five presets, so this is about everything
    that is not the form — an import, a fixture, a later endpoint.
    """
    import sqlalchemy.exc
    from sqlalchemy import select

    from students_cz.db.models import HelperProfile, Offer, ServiceType, User

    writing = await session.scalar(
        select(ServiceType).where(ServiceType.code == "writing")
    )
    user = User(tg_id=90701, first_name="Zero")
    session.add(user)
    await session.flush()
    session.add(HelperProfile(user_id=user.id))
    await session.flush()

    session.add(Offer(helper_id=user.id, service_type_id=writing.id, turnaround_days=0))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await session.flush()


async def test_a_withdrawn_checklist_line_survives_an_unrelated_save(client, session):
    """Deactivated is not deleted — that is the whole point of deactivating.

    An option withdrawn from the catalog stops being shown, and the offers
    pointing at it keep pointing at it, so putting it back puts the ticks back.
    """
    from sqlalchemy import select

    from students_cz.db.models import ServiceOption, ServiceType

    insurance = await session.scalar(
        select(ServiceType).where(ServiceType.code == "insurance")
    )
    options = (
        await session.scalars(
            select(ServiceOption)
            .where(ServiceOption.service_type_id == insurance.id)
            .order_by(ServiceOption.sort)
        )
    ).all()
    chosen = [options[0].id, options[1].id]

    headers = auth_header(90504)
    await client.put(
        "/api/v1/helper",
        json={
            "publish": True,
            "offers": [{"service_type_id": insurance.id, "option_ids": chosen}],
        },
        headers=headers,
    )

    options[0].is_active = False
    await session.flush()

    # The person edits their price and sends the checklist back untouched.
    await client.put(
        "/api/v1/helper",
        json={
            "publish": True,
            "offers": [
                {
                    "service_type_id": insurance.id,
                    "option_ids": chosen,
                    "price_amount": 800,
                }
            ],
        },
        headers=headers,
    )

    mine = (await client.get("/api/v1/helper", headers=headers)).json()
    assert mine["offers"][0]["option_ids"] == chosen, "a withdrawn line was erased"

    # And the page a student reads shows the surviving line only: hiding is the
    # read path's job, which is what lets the write path keep the id.
    me = (await client.get("/api/v1/me", headers=headers)).json()
    page = (await client.get(f"/api/v1/helpers/{me['id']}", headers=headers)).json()
    offer = next(o for o in page["offers"] if o["service_type"] == "insurance")
    assert len(offer["options"]) == 1, "a withdrawn line is still on the profile"


async def test_the_same_checklist_line_twice_is_stored_once(client, session):
    """Twice in the array is twice on the screen, and two React keys alike."""
    from sqlalchemy import select

    from students_cz.db.models import ServiceOption, ServiceType

    bank = await session.scalar(
        select(ServiceType).where(ServiceType.code == "bank_letter")
    )
    option = await session.scalar(
        select(ServiceOption).where(ServiceOption.service_type_id == bank.id)
    )

    headers = auth_header(90505)
    await client.put(
        "/api/v1/helper",
        json={
            "publish": True,
            "offers": [
                {"service_type_id": bank.id, "option_ids": [option.id, option.id]}
            ],
        },
        headers=headers,
    )
    mine = (await client.get("/api/v1/helper", headers=headers)).json()
    assert mine["offers"][0]["option_ids"] == [option.id]


async def test_an_unsure_guess_comes_back_as_also(client, session):
    """A guess that cannot filter can still be worth reading.

    Below the bar the embedder's proposal used to be dropped. It comes back
    named instead, so the screen can show it as its own section rather than
    narrowing the search by something it is not sure of.
    """
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import RiggedEmbedder

    # Above the demotion floor, below the bar that would let it filter.
    rigged = RiggedEmbedder("Теория вероятностей и статистика", 0.40)
    await rebuild(session, embedder=rigged)
    embedding.set_embedder(rigged)
    try:
        body = (
            await client.post(
                "/api/v1/search/parse",
                json={"text": "не понимаю как считать вероятности"},
                headers=auth_header(90901),
            )
        ).json()
    finally:
        embedding.set_embedder(None)

    assert body["also"] is not None, "the guess was dropped"
    assert "вероятност" in body["also"]["label"].lower()
    assert all(chip["kind"] != "subject" for chip in body["chips"]), (
        "an unsure guess must not become a filter"
    )


async def test_noise_is_not_demoted_either(client, session):
    """Below the floor the nearest subject is whatever happened to be closest."""
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import RiggedEmbedder

    rigged = RiggedEmbedder("Теория вероятностей и статистика", 0.20)
    await rebuild(session, embedder=rigged)
    embedding.set_embedder(rigged)
    try:
        body = (
            await client.post(
                "/api/v1/search/parse",
                json={"text": "не понимаю как считать вероятности"},
                headers=auth_header(90902),
            )
        ).json()
    finally:
        embedding.set_embedder(None)

    assert body["also"] is None


async def test_a_guess_the_rules_removed_is_not_shown_either(client, session):
    """Refused for want of confidence is worth showing. Refused for conflicting
    with the kind of help is not.

    A subject cannot go beside a kind of help that carries none — the search
    ANDs them and the pair matches nobody — so a section of those people answers
    a question the person did not ask.
    """
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import RiggedEmbedder

    # Confident enough to be believed, and then removed by the rule.
    rigged = RiggedEmbedder("Чешский язык B2 (для вуза и нострификации)", 0.60)
    await rebuild(session, embedder=rigged)
    embedding.set_embedder(rigged)
    try:
        body = (
            await client.post(
                "/api/v1/search/parse",
                json={"text": "нужна страховка зззз"},
                headers=auth_header(90903),
            )
        ).json()
    finally:
        embedding.set_embedder(None)

    assert body["also"] is None, "a conflicting guess came back as a section"


async def test_a_guess_beside_a_subjectless_kind_is_never_shown(client, session):
    """Whether it was believed and dropped, or never believed at all.

    A second list filtered by that subject is guaranteed to be empty: the search
    ANDs the subject with the kind of help, and no offer in the non-study group
    has one.
    """
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import RiggedEmbedder

    # Worth demoting on confidence — and still not worth showing here.
    rigged = RiggedEmbedder("Чешский язык B2 (для вуза и нострификации)", 0.40)
    await rebuild(session, embedder=rigged)
    embedding.set_embedder(rigged)
    try:
        body = (
            await client.post(
                "/api/v1/search/parse",
                json={"text": "нужна страховка зззз"},
                headers=auth_header(90904),
            )
        ).json()
    finally:
        embedding.set_embedder(None)

    assert body["also"] is None
