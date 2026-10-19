"""A word that names a whole shelf searches the whole shelf.

«математика» is what people type, and it names no single subject: the catalog
files maths under calculus, linear algebra, maths for economists and a dozen
more. Answered with whichever leaf the trigram scorer liked best — «Математика
для экономистов» at 0.66 — the search was narrowed to one corner of the shelf,
and "maths" in English found nothing at all.

So the parser may answer with the group itself, and everything that filters by
a subject reads a group as what it holds: its subtree, and the maths filed on
other shelves that its synonyms name.
"""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import HelpRequest, Subject, User
from students_cz.db.models.enums import RequestStatus, UiLang
from students_cz.services import requests as requests_service
from students_cz.services.parser import parse
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 1, 20)


async def _id(session: AsyncSession, slug: str) -> int:
    subject_id = await session.scalar(select(Subject.id).where(Subject.slug == slug))
    assert subject_id is not None, f"seed missing subject {slug}"
    return subject_id


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("математика", "ru"),
        ("репетитор по математике", "ru"),
        ("помощь на экзамене по математике", "ru"),
        ("matematika", "cs"),
        ("doučování matematiky", "cs"),
        ("maths", "en"),
        ("math tutor", "en"),
        ("mathematics", "en"),
        ("математика", "uk"),
        ("репетитор з математики", "uk"),
        # What is already a field is not a word about the subject.
        ("математика на ČVUT", "ru"),
        ("matematika ČVUT do 14. února, do 600 Kč", "cs"),
    ],
)
async def test_a_word_for_the_shelf_names_the_shelf(session, text, lang) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None, "no subject at all"
    assert parsed.subject.id == await _id(session, "math"), parsed.subject


@pytest.mark.parametrize(
    ("text", "lang", "slug"),
    [
        # A leaf named in full, by a synonym or by its exact name, is more
        # than the shelf it sits on.
        ("матан", "ru", "matematicka-analyza"),
        ("математика для экономистов", "ru", "matematika-pro-ekonomy"),
        ("школьная математика", "ru", "matematika-stredni-skola"),
        ("дискретная математика", "ru", "diskretni-matematika"),
        ("вступительный экзамен по математике", "ru", "prijimacky-matematika"),
        ("matematická analýza", "cs", "matematicka-analyza"),
        ("calculus", "en", "matematicka-analyza"),
        # Inflected, so no leaf scores 1.00 — and still not the shelf, because
        # something beside the maths word says which corner of it.
        ("doučování matematiky pro ekonomy", "cs", "matematika-pro-ekonomy"),
        ("репетитор по математике для экономистов", "ru", "matematika-pro-ekonomy"),
        ("finanční matematiky", "cs", "financni-matematika"),
        ("diskrétní matematiky", "cs", "diskretni-matematika"),
        # A kind of help whose offers live on another shelf: the maths group
        # beside it would match nobody.
        ("přijímací zkoušky z matematiky", "cs", "prijimacky-matematika"),
        ("вступительные экзамены по математике", "ru", "prijimacky-matematika"),
        ("nostrifikační zkouška z matematiky", "cs", "nostrifikacni-zkousky"),
    ],
)
async def test_a_named_leaf_beats_its_shelf(session, text, lang, slug) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.id == await _id(session, slug), parsed.subject


@pytest.mark.parametrize(("text", "lang"), [("физика", "ru"), ("fyzika", "cs")])
async def test_a_shelf_is_reached_by_its_synonyms_never_its_name(
    session, text, lang
) -> None:
    """Physics has no synonyms, so its name alone does not make a shelf of it.

    A shelf's name can be a whole phrase people type for something else:
    «příprava na přijímací zkoušky» names the admissions group and is the kind
    of help in full.
    """
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.id != await _id(session, "physics"), parsed.subject


async def test_searching_a_shelf_finds_every_leaf_on_it(
    client, session, helper_factory
) -> None:
    calculus = await helper_factory(tg_id=94001, subject_slug="matematicka-analyza")
    algebra = await helper_factory(tg_id=94002, subject_slug="linearni-algebra")
    physics = await helper_factory(tg_id=94003, subject_slug="fyzika-1")
    # Maths filed on other shelves, which the maths shelf's synonyms name.
    economists = await helper_factory(tg_id=94005, subject_slug="matematika-pro-ekonomy")
    maturita = await helper_factory(
        tg_id=94006, subject_slug="maturita", service_code="exam_prep"
    )

    async def found(slug: str) -> set[int]:
        body = (
            await client.get(
                "/api/v1/search",
                params={"subject_id": await _id(session, slug), "limit": 50},
                headers=auth_header(94004),
            )
        ).json()
        return {item["user_id"] for item in body["results"]}

    on_the_shelf = await found("math")
    assert {calculus.id, algebra.id, economists.id, maturita.id} <= on_the_shelf
    assert physics.id not in on_the_shelf
    # A leaf still means that leaf alone.
    assert algebra.id not in await found("matematicka-analyza")


async def test_a_request_for_the_shelf_reaches_a_helper_on_any_leaf(
    session: AsyncSession, helper_factory
) -> None:
    helper = await helper_factory(tg_id=94011, subject_slug="linearni-algebra")
    student = User(tg_id=94012, first_name="Eva", ui_lang=UiLang.RU)
    session.add(student)
    await session.flush()
    asked = HelpRequest(
        author_id=student.id,
        raw_text="нужна математика",
        status=RequestStatus.OPEN,
        langs=["ru"],
        subject_id=await _id(session, "math"),
    )
    session.add(asked)
    await session.flush()

    rows = await requests_service.feed_for(session, user=helper, limit=50)
    [row] = [item for item in rows if item.request.id == asked.id]
    assert row.on_subject is True


async def test_a_request_for_the_shelf_reaches_maths_filed_elsewhere(
    session: AsyncSession, helper_factory
) -> None:
    helper = await helper_factory(tg_id=94031, subject_slug="matematika-pro-ekonomy")
    student = User(tg_id=94032, first_name="Eva", ui_lang=UiLang.RU)
    session.add(student)
    await session.flush()
    asked = HelpRequest(
        author_id=student.id,
        raw_text="нужна математика",
        status=RequestStatus.OPEN,
        langs=["ru"],
        subject_id=await _id(session, "math"),
    )
    session.add(asked)
    await session.flush()

    rows = await requests_service.feed_for(session, user=helper, limit=50)
    [row] = [item for item in rows if item.request.id == asked.id]
    assert row.on_subject is True


async def test_a_request_for_a_leaf_does_not_reach_a_sibling_leaf(
    session: AsyncSession, helper_factory
) -> None:
    """Upwards only: calculus is maths, maths is not calculus."""
    helper = await helper_factory(tg_id=94021, subject_slug="linearni-algebra")
    student = User(tg_id=94022, first_name="Eva", ui_lang=UiLang.RU)
    session.add(student)
    await session.flush()
    asked = HelpRequest(
        author_id=student.id,
        raw_text="нужен матан",
        status=RequestStatus.OPEN,
        langs=["ru"],
        subject_id=await _id(session, "matematicka-analyza"),
    )
    session.add(asked)
    await session.flush()

    rows = await requests_service.feed_for(session, user=helper, limit=50)
    [row] = [item for item in rows if item.request.id == asked.id]
    assert row.on_subject is False
