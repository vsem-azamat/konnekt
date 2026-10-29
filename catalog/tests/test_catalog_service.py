"""The catalog's writes, reached without an HTTP client.

Three of them: starting a contact, and the two events that say the app was
opened and a person was read. They were route bodies until this file existed —
which is why none of them had a test that did not need a signed request.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import Contact, HelperProfile, User, UserEvent
from students_cz.db.models.enums import PublishStatus, UiLang, UserEventKind
from students_cz.services import catalog, errors

pytestmark = pytest.mark.asyncio


async def _person(session: AsyncSession, tg_id: int) -> User:
    user = User(tg_id=tg_id, first_name="Nikol", ui_lang=UiLang.RU)
    session.add(user)
    await session.flush()
    return user


async def _events(session: AsyncSession, user_id: int, kind: UserEventKind) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(UserEvent)
            .where(UserEvent.user_id == user_id, UserEvent.kind == kind)
        )
    ) or 0


async def test_starting_a_contact_records_it_and_hands_back_the_link(
    session: AsyncSession, helper_factory
) -> None:
    helper = await helper_factory(tg_id=92101, first_name="Dana")
    helper.tg_username = "dana_teaches"
    await session.flush()
    student = await _person(session, 92102)

    out = await catalog.start_contact(session, viewer=student, helper_id=helper.id)

    assert out.telegram_url.endswith(helper.tg_username)
    contacts = await session.scalar(
        select(func.count())
        .select_from(Contact)
        .where(Contact.student_id == student.id, Contact.helper_id == helper.id)
    )
    assert contacts == 1
    assert await _events(session, student.id, UserEventKind.CONTACT) == 1


async def test_you_cannot_start_a_contact_with_yourself(
    session: AsyncSession, helper_factory
) -> None:
    helper = await helper_factory(tg_id=92103)

    with pytest.raises(errors.BadRequest):
        await catalog.start_contact(session, viewer=helper, helper_id=helper.id)


async def test_somebody_who_is_not_a_helper_cannot_be_written_to(
    session: AsyncSession,
) -> None:
    student = await _person(session, 92104)
    nobody = await _person(session, 92105)

    with pytest.raises(errors.NotFound):
        await catalog.start_contact(session, viewer=student, helper_id=nobody.id)


async def test_a_profile_that_is_not_published_cannot_be_written_to(
    session: AsyncSession, helper_factory
) -> None:
    """A draft is not a listing. It exists, and to anyone outside it does not:
    the same 404, so which of the two it is cannot be read off the answer."""
    helper = await helper_factory(tg_id=92113)
    profile = await session.get(HelperProfile, helper.id)
    assert profile is not None
    profile.status = PublishStatus.DRAFT
    await session.flush()
    student = await _person(session, 92114)

    with pytest.raises(errors.NotFound):
        await catalog.start_contact(session, viewer=student, helper_id=helper.id)


async def test_a_helper_without_a_username_cannot_be_written_to(
    session: AsyncSession, helper_factory
) -> None:
    helper = await helper_factory(tg_id=92106)
    helper.tg_username = None
    await session.flush()
    student = await _person(session, 92107)

    with pytest.raises(errors.Conflict):
        await catalog.start_contact(session, viewer=student, helper_id=helper.id)


async def test_opening_the_home_screen_is_recorded_once(
    session: AsyncSession,
) -> None:
    viewer = await _person(session, 92108)

    people, things = await catalog.open_home(session, UiLang.RU, viewer=viewer)

    assert people or things
    assert await _events(session, viewer.id, UserEventKind.APP_OPEN) == 1


async def test_reading_a_person_is_recorded_once(
    session: AsyncSession, helper_factory
) -> None:
    helper = await helper_factory(tg_id=92109)
    viewer = await _person(session, 92110)

    detail = await catalog.view_helper(session, helper.id, UiLang.RU, viewer=viewer)

    assert detail is not None
    assert await _events(session, viewer.id, UserEventKind.HELPER_VIEW) == 1


async def test_a_person_who_is_not_there_is_not_recorded_as_read(
    session: AsyncSession,
) -> None:
    # Nothing was read, so nothing happened. An event here would count views of
    # profiles that do not exist as views of profiles.
    viewer = await _person(session, 92111)
    missing = await _person(session, 92112)

    detail = await catalog.view_helper(session, missing.id, UiLang.RU, viewer=viewer)

    assert detail is None
    assert await _events(session, viewer.id, UserEventKind.HELPER_VIEW) == 0


async def test_a_card_names_the_service_it_was_found_for(
    session: AsyncSession, helper_factory
) -> None:
    """Somebody who published without a line under their name is a name and
    nothing else on the card, which reads as a broken one. The service says
    what they are there for."""
    helper = await helper_factory(tg_id=92111, price=None)
    viewer = await _person(session, 92112)

    _, cards = await catalog.search(session, UiLang.RU, viewer=viewer)

    [card] = [c for c in cards if c.user_id == helper.id]
    assert card.service == "Репетитор по предмету"
    assert card.subject == "Математический анализ"


async def test_a_card_in_one_service_does_not_repeat_its_name(
    session: AsyncSession, helper_factory
) -> None:
    """The screen is already headed with the service; the card would say it twice."""
    from students_cz.db.models import ServiceType

    helper = await helper_factory(tg_id=92113, price=None)
    viewer = await _person(session, 92114)
    tutoring = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    assert tutoring is not None

    _, cards = await catalog.search(
        session, UiLang.RU, viewer=viewer, service_type_id=tutoring.id
    )

    [card] = [c for c in cards if c.user_id == helper.id]
    assert card.service is None


async def test_a_card_in_a_search_for_one_subject_does_not_repeat_it(
    session: AsyncSession, helper_factory
) -> None:
    from students_cz.db.models import Subject

    helper = await helper_factory(tg_id=92115, price=None)
    viewer = await _person(session, 92116)
    subject = await session.scalar(
        select(Subject).where(Subject.slug == "matematicka-analyza")
    )
    assert subject is not None

    _, cards = await catalog.search(
        session, UiLang.RU, viewer=viewer, subject_id=subject.id
    )

    [card] = [c for c in cards if c.user_id == helper.id]
    assert card.subject is None
