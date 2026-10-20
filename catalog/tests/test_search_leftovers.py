"""What #252 left open, each found on the deployed parser (#257).

Small things, each a query people type that came back as something else.
"""

from datetime import date

import pytest
from sqlalchemy import select

from students_cz.db.models import Subject
from students_cz.services.parser import parse

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 1, 20)


async def _id(session, slug: str) -> int:
    subject_id = await session.scalar(select(Subject.id).where(Subject.slug == slug))
    assert subject_id is not None, f"seed missing subject {slug}"
    return subject_id


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        # "exam prep" was checked before "entrance", and took the query.
        ("entrance exam preparation", "en"),
        ("entrance exam prep", "en"),
        # «тесты» only restate the kind of help, like «экзамены».
        ("вступительные тесты", "ru"),
        ("přijímací testy", "cs"),
    ],
)
async def test_entrance_exams_named_in_other_words(session, text, lang) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is None, parsed.subject


async def test_a_number_in_a_synonym_ends_there(session) -> None:
    """«физика 11 класс» matched the synonym «физика 1» by its first digit."""
    parsed = await parse(session, "физика 11 класс", "ru", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.id != await _id(session, "fyzika-1"), parsed.subject


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("matematika na Univerzitě Karlově", "cs"),
        ("matematika na Masarykově univerzitě", "cs"),
    ],
)
async def test_a_czech_locative_school_is_the_school(session, text, lang) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.institution is not None, "no school"
    assert parsed.subject is not None
    assert parsed.subject.id == await _id(session, "math"), parsed.subject


@pytest.mark.parametrize(
    ("text", "lang", "shelf"),
    [
        # A person, a treatment and a classic are not the shelf.
        ("химиотерапия", "ru", "chemistry"),
        ("chemist", "en", "chemistry"),
        ("chemik", "cs", "chemistry"),
        ("информатик", "ru", "it-programming"),
        ("классическая физика", "ru", "physics"),
        ("třídění matematika", "cs", "math"),
        ("učitelství matematiky", "cs", "math"),
    ],
)
async def test_a_stem_stops_at_the_word_it_means(session, text, lang, shelf) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is None or parsed.subject.id != await _id(session, shelf), (
        parsed.subject
    )


@pytest.mark.parametrize(
    ("text", "lang", "shelf"),
    [
        # The forms the narrower words must still reach.
        ("химия", "ru", "chemistry"),
        ("помощь по химии", "ru", "chemistry"),
        ("репетитор по химии", "ru", "chemistry"),
        ("хімія", "uk", "chemistry"),
        ("з хімії", "uk", "chemistry"),
        ("chemie", "cs", "chemistry"),
        ("doučování chemii", "cs", "chemistry"),
        ("chemistry", "en", "chemistry"),
        ("информатика", "ru", "it-programming"),
        ("по информатике", "ru", "it-programming"),
        ("физика 9 класс", "ru", "physics"),
        ("fyzika 9. třída", "cs", "physics"),
        ("učitel matematiky", "cs", "math"),
    ],
)
async def test_the_narrower_words_still_name_the_shelf(
    session, text, lang, shelf
) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None, "no subject at all"
    assert parsed.subject.id == await _id(session, shelf), parsed.subject


async def test_rizeni_restates_only_entrance_exams(session) -> None:
    """«přijímací řízení» is the admission procedure; beside tutoring the word
    is control, so the query is not bare and the embedder may answer it."""
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import PointedEmbedder

    query = "doučování řízení"
    pointed = PointedEmbedder({query: "Automatizace a teorie řízení"})
    await rebuild(session, embedder=pointed)
    embedding.set_embedder(pointed)
    try:
        parsed = await parse(session, query, "cs", today=TODAY)
    finally:
        embedding.set_embedder(None)

    assert parsed.service_type == "tutoring"
    assert parsed.vector is not None, "the embedder was not asked"
