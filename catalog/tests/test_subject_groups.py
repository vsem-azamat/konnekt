"""A word that names a whole shelf searches the whole shelf.

«математика» is what people type, and it names no single subject: the catalog
files maths under calculus, linear algebra, maths for economists and a dozen
more. Answered with whichever leaf the trigram scorer liked best — «Математика
для экономистов» at 0.66 — the search was narrowed to one corner of the shelf,
and "maths" in English found nothing at all.

So the parser may answer with the group itself, and everything that filters by
a subject reads a group as what it holds: its subtree, and the leaves on other
shelves it lists in `holds`.
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
        # The Czech locative turns k into c.
        ("matematice", "cs"),
        # A number where no maths course is numbered says nothing about which.
        ("математика 1", "ru"),
        ("maths 101", "en"),
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


@pytest.mark.parametrize(("text", "lang"), [("биология", "ru"), ("biologie", "cs")])
async def test_a_shelf_is_reached_by_its_synonyms_never_its_name(
    session, text, lang
) -> None:
    """Biology has no synonyms, so its name alone does not make a shelf of it.

    A shelf's name can be a whole phrase people type for something else:
    «příprava na přijímací zkoušky» names the admissions group and is the kind
    of help in full.
    """
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.id != await _id(session, "biology-medicine"), parsed.subject


async def test_searching_a_shelf_finds_every_leaf_on_it(
    client, session, helper_factory
) -> None:
    calculus = await helper_factory(tg_id=94001, subject_slug="matematicka-analyza")
    algebra = await helper_factory(tg_id=94002, subject_slug="linearni-algebra")
    physics = await helper_factory(tg_id=94003, subject_slug="fyzika-1")
    # Maths filed on other shelves, which the maths shelf lists.
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


def _shelf_migrations() -> list:
    """Every migration that writes a shelf's words or what it holds, in
    revision order — which the file names do not promise — from the one that
    introduced them (65e02593516e, which also adds the column) on."""
    import importlib.util
    from pathlib import Path

    versions = (
        Path(__file__).resolve().parents[1] / "src/students_cz/db/migrations/versions"
    )
    migrations = []
    for path in versions.glob("*.py"):
        spec = importlib.util.spec_from_file_location(f"_m_{path.stem}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "HOLDS"):
            migrations.append(module)
    by_parent = {migration.down_revision: migration for migration in migrations}
    revisions = {migration.revision for migration in migrations}
    [first] = [m for m in migrations if m.down_revision not in revisions]
    assert first.revision == "65e02593516e"
    ordered = [first]
    while ordered[-1].revision in by_parent:
        ordered.append(by_parent[ordered[-1].revision])
    assert len(ordered) == len(migrations)
    return ordered


# Leaf synonyms production held before the shelf migrations, which they take
# away. Written out here rather than read from the downgrades: a migration that
# forgot to remove a word would restore nothing on the way down and remove
# nothing on the way up, and the seed would look matched.
PRODUCTION_HAD: dict[str, set[str]] = {
    "obecna-chemie": {"хімія"},
    "automatizace-a-rizeni": {"rizeni"},
}


async def test_seed_and_migrations_agree_about_what_a_shelf_holds() -> None:
    """`holds` reaches production by migration only, like synonyms."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    seeded = {
        group["slug"]: set(group.get("holds", []))
        for group in json.loads((root / "seeds/subjects.json").read_text())["groups"]
    }
    migrated: dict[str, set[str]] = {}
    for module in _shelf_migrations():
        for slug, slugs in module.HOLDS.items():
            migrated[slug] = set(slugs)
    assert migrated, "no migration declares what a shelf holds"
    assert {slug: holds for slug, holds in seeded.items() if holds} == migrated


async def test_the_migration_writes_what_the_seed_says(session: AsyncSession) -> None:
    """The deploy runs the migrations and never the seed, so their UPDATEs are
    what production gets. Take the seeded database back to what production held
    before the first of them, run them up in order inside the test's
    transaction, and compare with the seed file.
    """
    import json
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    root = Path(__file__).resolve().parents[1]
    migrations = _shelf_migrations()

    def run(connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            for migration in reversed(migrations):
                migration.downgrade()
            # What production held before: no group had synonyms. A downgrade
            # only removes the words it names, so a word missing from a
            # migration would otherwise survive here from the seed.
            connection.execute(
                text("UPDATE subjects SET synonyms = '{}' WHERE kind = 'group'")
            )
            for slug, words in PRODUCTION_HAD.items():
                connection.execute(
                    text(
                        "UPDATE subjects SET synonyms = ARRAY(SELECT DISTINCT unnest("
                        "synonyms || CAST(:words AS text[]))) WHERE slug = :slug"
                    ),
                    {"words": sorted(words), "slug": slug},
                )
            for migration in migrations:
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

    # And the leaves a migration took a word from.
    leaves = {
        leaf["slug"]: leaf
        for group in seeded.values()
        for leaf in group.get("children", [])
    }
    for slug in PRODUCTION_HAD:
        synonyms = await session.scalar(
            text("SELECT synonyms FROM subjects WHERE slug = :slug"), {"slug": slug}
        )
        assert set(synonyms) == set(leaves[slug].get("synonyms", [])), slug


# The other shelves people name by one word, written the same way as maths:
# synonyms for the word, and `holds` for what sits elsewhere.
@pytest.mark.parametrize(
    ("text", "lang", "shelf"),
    [
        ("физика", "ru", "physics"),
        ("репетитор по физике", "ru", "physics"),
        ("fyzika", "cs", "physics"),
        # The genitive answered «Fyziologie» by trigram.
        ("fyziky", "cs", "physics"),
        ("fyzice", "cs", "physics"),
        ("doučování ve fyzice", "cs", "physics"),
        ("фізиці", "uk", "physics"),
        ("pomoc u zkoušky z fyziky", "cs", "physics"),
        ("physics", "en", "physics"),
        ("фізика", "uk", "physics"),
        ("химия", "ru", "chemistry"),
        ("помощь по химии", "ru", "chemistry"),
        ("chemie", "cs", "chemistry"),
        ("chemistry tutor", "en", "chemistry"),
        ("хімія", "uk", "chemistry"),
        ("программирование", "ru", "it-programming"),
        ("информатика", "ru", "it-programming"),
        ("programování", "cs", "it-programming"),
        ("programming", "en", "it-programming"),
        ("informatika", "cs", "it-programming"),
        ("інформатика", "uk", "it-programming"),
        ("інформатиці", "uk", "it-programming"),
        ("informatice", "cs", "it-programming"),
        ("програмування", "uk", "it-programming"),
        ("экономика", "ru", "economics-finance"),
        ("репетитор по экономике", "ru", "economics-finance"),
        ("ekonomie", "cs", "economics-finance"),
        ("economics", "en", "economics-finance"),
        ("економіка", "uk", "economics-finance"),
        ("економіці", "uk", "economics-finance"),
    ],
)
async def test_other_words_for_a_shelf_name_their_shelf(
    session, text, lang, shelf
) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None, "no subject at all"
    assert parsed.subject.id == await _id(session, shelf), parsed.subject


@pytest.mark.parametrize(
    ("text", "lang", "slug"),
    [
        ("физика 1", "ru", "fyzika-1"),
        # Inflected, so no leaf scores 1.00; a number in the name of a course
        # on the shelf names that course.
        ("fyziky 2", "cs", "fyzika-2"),
        ("по физике 1", "ru", "fyzika-1"),
        ("репетитор по физике 2", "ru", "fyzika-2"),
        ("фізичної хімії", "uk", "fyzikalni-chemie"),
        ("organické chemie", "cs", "organicka-chemie"),
        ("fyzikální chemie", "cs", "fyzikalni-chemie"),
        ("физическая химия", "ru", "fyzikalni-chemie"),
        ("organická chemie", "cs", "organicka-chemie"),
        ("programování v C", "cs", "programovani-v-c"),
        ("теоретическая информатика", "ru", "teoreticka-informatika"),
        ("mikroekonomie", "cs", "mikroekonomie"),
        ("математика для экономистов", "ru", "matematika-pro-ekonomy"),
    ],
)
async def test_a_named_leaf_beats_the_other_shelves(session, text, lang, slug) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.id == await _id(session, slug), parsed.subject


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        # "physic" would begin "physician".
        ("physician", "en"),
        # «fyzic» would begin «fyzická příprava», which is fitness.
        ("fyzická příprava", "cs"),
    ],
)
async def test_a_stem_does_not_reach_another_word(session, text, lang) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is None or parsed.subject.id != await _id(session, "physics")


# Beyond its subtree, exactly what each shelf lists — maths what it held when
# membership was read from leaf names, physics its entrance exams. And not
# what a name or a synonym only mentions: «Fyzikální chemie» is chemistry, the
# medicine admissions are not chemistry, the VŠE admissions are not economics,
# and nostrification is not maths.
ACROSS: dict[str, set[str]] = {
    "math": {
        "maturita",
        "matematika-pro-ekonomy",
        "financni-matematika",
        "prijimacky-technicke-vs",
        "prijimacky-matematika",
    },
    "physics": {"prijimacky-fyzika", "prijimacky-technicke-vs"},
    "chemistry": set(),
    "it-programming": {"prijimacky-technicke-vs"},
    "economics-finance": {"prijimacky-ekonomicke-vs"},
}


@pytest.mark.parametrize("shelf", sorted(ACROSS))
async def test_a_shelf_holds_what_it_lists_and_nothing_it_only_mentions(
    session, shelf
) -> None:
    from students_cz.services.lookup import held_by

    shelf_id = await _id(session, shelf)
    path = await session.scalar(select(Subject.path).where(Subject.id == shelf_id))
    held = await session.scalars(
        select(Subject.slug).where(
            Subject.id.in_(await held_by(session, shelf_id)),
            ~Subject.path.startswith(path),
        )
    )
    assert set(held) == ACROSS[shelf]


async def test_every_listed_leaf_is_a_live_leaf_elsewhere(session) -> None:
    """`holds` is the only way across the tree, so a typo there holds nothing
    and fails nothing — except this."""
    from students_cz.db.models.enums import NodeKind

    shelves = (
        await session.scalars(select(Subject).where(Subject.kind == NodeKind.GROUP))
    ).all()
    for shelf in shelves:
        for slug in shelf.holds:
            leaf = await session.scalar(select(Subject).where(Subject.slug == slug))
            assert leaf is not None, f"{shelf.slug} holds a missing {slug}"
            assert leaf.kind == NodeKind.LEAF and leaf.is_active, slug
            assert not leaf.path.startswith(shelf.path), f"{slug} is under {shelf.slug}"


# What #252 still had open once the shelves were in.
@pytest.mark.parametrize(
    ("text", "lang", "shelf"),
    [
        # Asking politely or in a hurry says nothing about which corner.
        ("математика срочно", "ru", "math"),
        ("математика пожалуйста", "ru", "math"),
        ("matematika prosím", "cs", "math"),
        # Nor does a school year, or asking for a teacher rather than a tutor.
        ("физика 9 класс", "ru", "physics"),
        ("учитель математики", "ru", "math"),
        ("učitel matematiky", "cs", "math"),
        ("maths teacher", "en", "math"),
        # A school named in full, or a faculty beside its university.
        ("matematika Univerzita Karlova", "cs", "math"),
        ("математика в Карловом университете", "ru", "math"),
        ("informatika FIT ČVUT", "cs", "it-programming"),
        ("matematika MFF UK", "cs", "math"),
    ],
)
async def test_what_surrounds_a_shelf_word_can_be_said_aside(
    session, text, lang, shelf
) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None, "no subject at all"
    assert parsed.subject.id == await _id(session, shelf), parsed.subject


async def test_a_shelf_word_is_not_also_a_school(session) -> None:
    """«informatiky» is the programming shelf, and by trigram also «Fakulta
    informatiky» — the same word read twice, narrowing to one faculty."""
    parsed = await parse(session, "doučování informatiky", "cs", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.id == await _id(session, "it-programming")
    assert parsed.institution is None, parsed.institution


async def test_a_guess_from_another_shelf_is_dropped(session) -> None:
    """«вступительные по химии» answered the physics entrance exam: the query
    names chemistry, and the guess sits on physics."""
    parsed = await parse(session, "вступительные по химии", "ru", today=TODAY)
    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is None, parsed.subject


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("přijímací řízení", "cs"),
        ("příprava na přijímací řízení", "cs"),
        ("приемные экзамены", "ru"),
        ("подготовка к приемным экзаменам", "ru"),
        ("помощь с приемными экзаменами", "ru"),
        ("о приемном экзамене", "ru"),
        ("приемный экзамен", "ru"),
        ("приемная комиссия", "ru"),
    ],
)
async def test_other_names_for_admissions_name_the_kind_of_help(
    session, text, lang
) -> None:
    """«řízení» is the admission procedure here, not control theory; «приемные»
    is the other Russian word for entrance exams."""
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is None, parsed.subject


@pytest.mark.parametrize(
    ("text", "lang", "slug"),
    [
        # A plain query naming two shelves keeps what it found: the guess-drop
        # is for a kind of help the shelf cannot go with, nothing else.
        ("fyzikální chemii", "cs", "fyzikalni-chemie"),
        ("maturitu z chemie", "cs", "maturita"),
        # A number beside a school is still the course's number.
        ("fyziky 2 UK", "cs", "fyzika-2"),
        ("репетитор по физике 2 МФФ", "ru", "fyzika-2"),
        # A school's name carries subject words; they stay the subject's.
        ("maths for economics VŠE", "en", "matematika-pro-ekonomy"),
        # Control theory by its other names, now that «řízení» alone is not.
        ("automatické řízení", "cs", "automatizace-a-rizeni"),
        ("řízení procesů", "cs", "automatizace-a-rizeni"),
    ],
)
async def test_what_the_leftovers_must_not_take_away(session, text, lang, slug) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None, "no subject at all"
    assert parsed.subject.id == await _id(session, slug), parsed.subject


async def test_two_shelves_named_together_still_find_somebody(session) -> None:
    """«математика и физика» answered Физика 1 on main; dropping it for not
    being maths left a guess that matched nobody."""
    parsed = await parse(session, "математика и физика", "ru", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.id == await _id(session, "fyzika-1"), parsed.subject


@pytest.mark.parametrize(
    ("text", "lang", "school"),
    [
        ("matematika MFF UK", "cs", True),
        # An exact school is kept even when the shelf word alone explains the
        # rest: FI is named here, not guessed from «informatika».
        ("informatika FI", "cs", True),
    ],
)
async def test_a_school_named_beside_a_shelf_stays(session, text, lang, school) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert (parsed.institution is not None) is school, parsed.institution


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("математика терміново", "uk"),
        ("математика будь ласка", "uk"),
        ("вчитель математики", "uk"),
        ("викладач математики", "uk"),
        ("matematika rychle", "cs"),
    ],
)
async def test_ukrainian_and_czech_asides_too(session, text, lang) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.id == await _id(session, "math"), parsed.subject


@pytest.mark.parametrize(
    ("text", "lang"),
    [("приемник и передатчик", "ru"), ("приемная семья", "ru")],
)
async def test_a_receiver_is_not_an_entrance_exam(session, text, lang) -> None:
    parsed = await parse(session, text, lang, today=TODAY)
    assert parsed.service_type != "entrance_prep"


async def test_a_dropped_guess_is_not_replaced_by_the_embedder(session) -> None:
    """Dropping the wrong shelf's guess left the list empty, and the embedder
    was then asked and answered «Chemie – střední škola» at 0.69 — beside
    entrance exams, which matches nobody. The shelf has spoken; nothing is left
    for the embedder to explain."""
    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .test_embedding import PointedEmbedder

    query = "вступительные по химии"
    pointed = PointedEmbedder({query: "Chemie – střední škola"})
    await rebuild(session, embedder=pointed)
    embedding.set_embedder(pointed)
    try:
        parsed = await parse(session, query, "ru", today=TODAY)
    finally:
        embedding.set_embedder(None)

    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is None, parsed.subject
    assert parsed.vector is None, "the embedder was asked"


async def test_a_listed_leaf_survives_the_wrong_shelf_drop(session) -> None:
    """Economics lists the economics admissions, so beside entrance exams that
    is the answer to keep, not to throw away with the guess."""
    parsed = await parse(session, "entrance exam economics", "en", today=TODAY)
    assert parsed.service_type == "entrance_prep"
    assert parsed.subject is not None
    assert parsed.subject.id == await _id(session, "prijimacky-ekonomicke-vs"), (
        parsed.subject
    )


async def test_a_year_of_study_is_said_aside(session) -> None:
    parsed = await parse(session, "математика 1 курс", "ru", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.id == await _id(session, "math"), parsed.subject
