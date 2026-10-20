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
from sqlalchemy import select, text
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
        # Words that restate an exam, and a number, say nothing about which
        # corner of maths.
        ("подготовка к экзамену по математике", "ru"),
        ("экзамен по математике", "ru"),
        ("maths exam", "en"),
        ("математика 1", "ru"),
        # «Higher» says which school level, not which corner of maths.
        ("высшая математика", "ru"),
        ("вища математика", "uk"),
        ("vyšší matematika", "cs"),
        ("higher maths", "en"),
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
        # A synonym naming the leaf, with nothing else in the query.
        ("matematika VŠE", "cs", "matematika-pro-ekonomy"),
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


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        # A level says which language exam, not which maths.
        ("математика B2", "ru"),
        # Kinds of help whose offers carry no maths leaf.
        ("math essay", "en"),
        ("математика общежитие", "ru"),
    ],
)
async def test_the_shelf_is_not_chosen_beside_what_it_cannot_go_with(
    session, text, lang
) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is None or parsed.subject.id != await _id(session, "math"), (
        parsed.subject
    )


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

    # Nostrification mentions maths in one synonym of a dozen; it is not maths.
    nostrification = await helper_factory(
        tg_id=94007, subject_slug="nostrifikacni-zkousky", service_code="nostrification"
    )

    on_the_shelf = await found("math")
    assert {calculus.id, algebra.id, economists.id, maturita.id} <= on_the_shelf
    assert nostrification.id not in on_the_shelf
    assert physics.id not in on_the_shelf
    # A leaf still means that leaf alone, however its synonyms read: only a
    # shelf reaches across the tree.
    on_calculus = await found("matematicka-analyza")
    assert algebra.id not in on_calculus
    assert economists.id not in on_calculus


async def test_a_leaf_reaches_nothing_beyond_itself(
    client, session, helper_factory
) -> None:
    """Only a shelf reaches across the tree. A leaf's synonyms read the same way
    would make probability cover statistics for economists by the word
    «statistik», and operating systems cover law."""
    economists = await helper_factory(tg_id=94051, subject_slug="statistika-pro-ekonomy")
    body = (
        await client.get(
            "/api/v1/search",
            params={
                "subject_id": await _id(session, "pravdepodobnost-a-statistika"),
                "limit": 50,
            },
            headers=auth_header(94052),
        )
    ).json()
    assert economists.id not in {item["user_id"] for item in body["results"]}


async def test_a_retired_leaf_elsewhere_is_not_on_the_shelf(
    client, session, helper_factory
) -> None:
    """Retiring financial maths takes it out of a maths search and off the
    shelf in the request feed, the same in both directions."""
    helper = await helper_factory(tg_id=94061, subject_slug="financni-matematika")
    leaf = await session.get(Subject, await _id(session, "financni-matematika"))
    assert leaf is not None
    leaf.is_active = False
    await session.flush()

    body = (
        await client.get(
            "/api/v1/search",
            params={"subject_id": await _id(session, "math"), "limit": 50},
            headers=auth_header(94062),
        )
    ).json()
    assert helper.id not in {item["user_id"] for item in body["results"]}

    student = User(tg_id=94063, first_name="Eva", ui_lang=UiLang.RU)
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
    assert row.on_subject is False


async def test_a_retired_leaf_still_finds_its_own_offers(
    client, session, helper_factory
) -> None:
    """As a plain filter by its id always did; only what a shelf reaches
    beyond itself has to be live."""
    helper = await helper_factory(tg_id=94041, subject_slug="teorie-grafu")
    leaf = await session.get(Subject, await _id(session, "teorie-grafu"))
    assert leaf is not None
    leaf.is_active = False
    await session.flush()

    body = (
        await client.get(
            "/api/v1/search",
            params={"subject_id": leaf.id, "limit": 50},
            headers=auth_header(94042),
        )
    ).json()
    assert helper.id in {item["user_id"] for item in body["results"]}


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


async def test_seed_and_migrations_agree_about_what_a_shelf_holds() -> None:
    """`holds` reaches production by migration only, like synonyms."""
    import importlib.util
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    seeded = {
        group["slug"]: set(group.get("holds", []))
        for group in json.loads((root / "seeds/subjects.json").read_text())["groups"]
    }
    migrated: dict[str, set[str]] = {}
    for path in sorted((root / "src/students_cz/db/migrations/versions").glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"_m_{path.stem}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for slug, slugs in getattr(module, "HOLDS", {}).items():
            migrated[slug] = set(slugs)
    assert migrated, "no migration declares what a shelf holds"
    assert {slug: holds for slug, holds in seeded.items() if holds} == migrated


async def test_the_migration_writes_what_the_seed_says(session: AsyncSession) -> None:
    """The deploy runs the migration and never the seed, so its UPDATEs are
    what production gets. Take the seeded database back to what production
    held, run the migration up inside the test's transaction, and compare with
    the seed file.
    """
    import importlib.util
    import json
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    root = Path(__file__).resolve().parents[1]
    [path] = (root / "src/students_cz/db/migrations/versions").glob("*_65e02593516e_*.py")
    spec = importlib.util.spec_from_file_location("_m_shelf", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def run(connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            # What production held before: no group had synonyms. The downgrade
            # only removes the words it names, so a word missing from the
            # migration would otherwise survive here from the seed.
            connection.execute(
                text("UPDATE subjects SET synonyms = '{}' WHERE kind = 'group'")
            )
            migration.upgrade()

    await session.run_sync(lambda sync: run(sync.connection()))

    seeded = {
        group["slug"]: group
        for group in json.loads((root / "seeds/subjects.json").read_text())["groups"]
    }
    rows = (
        await session.execute(
            text("SELECT slug, synonyms, holds FROM subjects WHERE kind = 'group'")
        )
    ).all()
    assert rows
    for slug, synonyms, holds in rows:
        assert set(synonyms) == set(seeded[slug].get("synonyms", [])), slug
        assert set(holds) == set(seeded[slug].get("holds", [])), slug
