"""Every kind of help belongs to a group, and production hears about it.

Two different silent failures live here.

The first is a service type with no group. Both screens that show these tiles —
the catalog's front door and the screen where someone offers a service — render
by group, so an ungrouped type appears on neither. Nothing errors; the type is
simply invisible.

The second is the seed and the migration drifting apart. The deployment runs
`alembic upgrade head` and never runs `seed.py`, so a row that exists only in
the seed reaches every developer's database and no production one. The two
therefore hold the same reference data on purpose, and the last test here is
what keeps them saying the same thing.
"""

import importlib.util
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from students_cz.db.models import ServiceType
from students_cz.db.models.enums import ServiceGroup
from students_cz.db.seed import SERVICE_TYPES
from students_cz.services.parser import SUBJECTLESS

VERSIONS = Path(__file__).resolve().parents[1] / "src/students_cz/db/migrations/versions"


def _seeded_groups() -> dict[str, str]:
    return {spec["code"]: spec["group"] for spec in SERVICE_TYPES}


def _seeded_rows() -> dict[str, dict[str, Any]]:
    """Everything about a service type that a deployed database has to match."""
    return {
        spec["code"]: {
            "group": spec["group"],
            "unit": spec.get("default_price_unit"),
            "names": {lang: tuple(value) for lang, value in spec["names"].items()},
        }
        for spec in SERVICE_TYPES
    }


def _migrated_rows() -> dict[str, dict[str, Any]]:
    """The same, for the rows the migrations actually create or rename.

    A rename is declared under `SERVICE_TYPE_RENAMES`, code to the languages it
    rewrites, and says nothing about the shelf or the unit. A type no migration
    created comes out of here with its names alone — the only part of it a
    migration has ever written.
    """
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        for code, names in _constant(path, "SERVICE_TYPE_RENAMES", {}).items():
            row = rows.setdefault(code, {})
            row["names"] = {
                **row.get("names", {}),
                **{lang: tuple(value) for lang, value in names.items()},
            }
        for row in _load(path):
            # A row that creates a service type says everything about it. One
            # with names and no group would be a migration inserting a type onto
            # no shelf, which is worth a named failure rather than a KeyError.
            if "names" not in row:
                continue
            assert "group" in row, (
                f"{path.name}: {row['code']} creates a service type with no group"
            )
            rows[row["code"]] = {
                "group": row["group"],
                "unit": row["default_price_unit"],
                "names": {lang: tuple(value) for lang, value in row["names"].items()},
            }
    return rows


def _constant(path: Path, name: str, default: Any = None) -> Any:
    """One constant out of one migration file, or `default` if it has none.

    Loaded by path rather than imported: `versions` is not a package.
    """
    spec = importlib.util.spec_from_file_location(f"_migration_{path.stem}", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, name, default)


def _load(path: Path) -> list[dict[str, Any]]:
    """The service types one migration writes, or nothing if it writes none.

    Every row is checked for the keys these comparisons index, and named if it
    lacks them: a future migration that spells its table differently should say
    so here rather than fail with a bare `KeyError` in a helper.

    A migration carries the columns it sets and no others, so `code` is the only
    key every row must have. Beyond that a row is required to say *something* —
    a row naming a service type and changing nothing about it is a mistake worth
    a failure rather than a silent skip.
    """
    rows = list(_constant(path, "SERVICE_TYPES", []))
    for row in rows:
        assert "code" in row, f"{path.name}: a SERVICE_TYPES row is missing ['code']"
        assert set(row) - {"code"}, (
            f"{path.name}: {row['code']} names a service type and sets nothing"
        )
    return rows


def _migrated_groups() -> dict[str, str]:
    """What the migrations, taken together, leave a deployed database holding.

    Every migration, not one named file. A migration describes the database at
    a moment in time and must never be edited afterwards, so pinning this to a
    single revision would mean the thirteenth service type could only be added
    by rewriting history.

    Later revisions win, ordered by filename rather than by walking the revision
    chain. That is only correct because every file here is date prefixed, which
    is this repository's convention and not alembic's rule — two revisions
    landing on the same day and disagreeing about the same code would be
    resolved arbitrarily. They would also be a mistake worth catching by hand.

    """
    groups: dict[str, str] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        for row in _load(path):
            # A migration that sets some other column names the same service
            # types and says nothing about their shelf. Skipping those is what
            # keeps "which types exist" answerable from every migration
            # together, rather than only from the ones about groups.
            if "group" in row:
                groups[row["code"]] = row["group"]
    return groups


def _migrated_forms() -> dict[str, str]:
    """The same walk as `_migrated_groups`, for the other column."""
    forms: dict[str, str] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        for row in _load(path):
            if "form" in row:
                forms[row["code"]] = row["form"]
    return forms


def test_every_seeded_service_type_declares_a_group() -> None:
    """A twelfth type appended without a group would default to `study`.

    Checking the column against `ServiceGroup` instead would prove nothing:
    the column is typed, so a member test can never fail. The mistake worth
    catching happens in the seed, in Python, before any of that.
    """
    missing = [spec["code"] for spec in SERVICE_TYPES if not spec.get("group")]
    assert missing == [], f"service types with no group: {missing}"

    unknown = sorted(
        {spec["group"] for spec in SERVICE_TYPES}
        - {member.value for member in ServiceGroup}
    )
    assert unknown == [], f"groups that are not in ServiceGroup: {unknown}"


def test_the_three_groups_are_all_used() -> None:
    """A group nobody is in renders an empty heading on both screens."""
    used = {spec["group"] for spec in SERVICE_TYPES}
    assert used == {member.value for member in ServiceGroup}


@pytest.mark.asyncio
async def test_seeded_groups_reach_the_database(session: Any) -> None:
    rows = (await session.scalars(select(ServiceType))).all()
    assert rows, "reference data is not loaded — run `make seed`"

    stored = {row.code: row.group_code.value for row in rows}
    expected = _seeded_groups()
    assert {code: stored.get(code) for code in expected} == expected


def test_seed_and_migrations_agree_on_which_types_exist() -> None:
    """The one that stops production drifting from the seed.

    `seed.py` builds a fresh database; the migrations are the only thing that
    runs on the deployed one. A type added to one and not the other is a
    category that exists locally and nowhere else — or, the other way round, a
    category live in production that no fresh checkout has.
    """
    assert _migrated_groups() == _seeded_groups()


def test_seed_and_migrations_agree_on_what_those_types_say() -> None:
    """Names too, not only codes — that is where most of the data is.

    Forty translated strings and a price unit are written out twice, and only
    the seed's copy is ever re-read. Renaming a service type there and stopping
    would leave production showing the old name for ever, because the seed does
    not run on the deployed database: a rename needs a migration, and this is
    what says so.

    Only what a migration writes is compared: the rows it creates, and the
    languages a `SERVICE_TYPE_RENAMES` rewrites. No migration creates seven of
    the twelve — the initial schema builds the table and inserts nothing, and
    they reached production because somebody ran the seed against it by hand.
    Renaming one of those in the seed alone still passes here; the rename has to
    be declared in a migration before this can hold the two together, and
    docs/data-model.md is where that is written down.
    """
    migrated = _migrated_rows()
    seeded = _seeded_rows()
    assert migrated == {
        code: {
            key: (
                {lang: seeded[code]["names"][lang] for lang in row["names"]}
                if key == "names"
                else seeded[code][key]
            )
            for key in row
        }
        for code, row in migrated.items()
    }


def test_subjectless_is_exactly_the_life_group():
    """The parser's own list of subjectless kinds, against the seed.

    `SUBJECTLESS` is written out in the parser because it reads no tables, and a
    sixth kind of help in the `life` group would otherwise be added without the
    rule that protects it — a query naming a subject would come back with that
    kind beside it, and the two filters together match nobody.

    Not `requires_subject`: exam help and nostrification have that false too and
    must stay out of this set.
    """
    life = {spec["code"] for spec in SERVICE_TYPES if spec["group"] == "life"}
    assert life == SUBJECTLESS


def test_every_seeded_service_type_declares_a_form():
    """The shape of the form that offers it, not the shelf it sits on.

    Without this a new kind of help takes the column's default and gets the
    lesson form — which is how a bank statement came to ask how you teach.
    """
    missing = [spec["code"] for spec in SERVICE_TYPES if not spec.get("form")]
    assert not missing, f"no form shape: {missing}"


@pytest.mark.asyncio
async def test_the_form_shape_reaches_the_database(session) -> None:
    """Against rows, not against the constant this module already imports.

    The seed writing `form` into a dict proves nothing about what a database
    holds; the column it lands in is what the API reads.
    """
    rows = {
        row.code: row.form_shape.value
        for row in (await session.scalars(select(ServiceType))).all()
    }
    assert rows["tutoring"] == "lesson"
    assert rows["writing"] == "work"
    # Standby for one event on one day. It sits on the entrance shelf, where a
    # student compares it with exam preparation, and its form has nothing to do
    # with teaching.
    assert rows["exam_live_help"] == "errand"
    assert rows["insurance"] == "errand"
    assert rows == {spec["code"]: spec["form"] for spec in SERVICE_TYPES}


def test_seed_and_migration_agree_about_forms():
    """The deploy runs migrations and never the seed.

    A form shape that exists only in the seed reaches every developer's
    database and no production one, and the production form then asks a
    bank-statement helper how they teach — silently, because nothing errors.
    """
    migrated = _migrated_forms()
    assert migrated, "no migration sets a form shape"
    assert migrated == {spec["code"]: spec["form"] for spec in SERVICE_TYPES}


def _migrated_options() -> dict[str, list[tuple]]:
    """Each service type's checklist as the migrations write it — labels too.

    Codes alone would leave a hundred translated strings duplicated between the
    seed and the migration with nothing comparing them, which is the exact
    failure this module exists to prevent: a label corrected in the seed alone
    never reaches production.
    """
    options: dict[str, list[tuple]] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        for code, rows in _constant(path, "SERVICE_OPTIONS", {}).items():
            options[code] = [tuple(row) for row in rows]
    return options


def test_every_errand_says_what_it_covers() -> None:
    """A tile is the whole query for an errand, so the checklist is the offer.

    Without one the person offering insurance can say nothing beyond the word
    "insurance", and the student reads a list of identical rows.
    """
    from students_cz.db.seed import SERVICE_OPTIONS

    errands = {spec["code"] for spec in SERVICE_TYPES if spec["form"] == "errand"}
    missing = sorted(errands - set(SERVICE_OPTIONS))
    assert missing == [], f"errands with no checklist: {missing}"


def test_written_work_says_what_it_takes_on() -> None:
    """The same argument as the errand above, for the one `work` shape.

    A written work asks for no subject and no school — `requires_subject` is
    false — no hourly rate and no question about meeting, so two people who
    write theses are one row read twice unless they can say which works they
    take on.
    """
    from students_cz.db.seed import SERVICE_OPTIONS

    works = {spec["code"] for spec in SERVICE_TYPES if spec["form"] == "work"}
    missing = sorted(works - set(SERVICE_OPTIONS))
    assert missing == [], f"written work with no checklist: {missing}"


def test_seed_and_migration_agree_about_options() -> None:
    """The deploy runs migrations and never the seed.

    A checklist that exists only in the seed is one every developer sees and no
    student does.
    """
    from students_cz.db.seed import SERVICE_OPTIONS

    seeded = {
        code: [tuple(row) for row in rows] for code, rows in SERVICE_OPTIONS.items()
    }
    migrated = _migrated_options()
    assert migrated, "no migration creates a checklist"
    assert migrated == seeded


@pytest.mark.asyncio
async def test_the_checklist_reaches_the_database(session) -> None:
    from students_cz.db.models import ServiceOption, ServiceType
    from students_cz.db.seed import SERVICE_OPTIONS

    # Active only: a line dropped from the constant is retired rather than
    # deleted, so its row outlives the constant on purpose.
    rows = (
        await session.scalars(
            select(ServiceOption).where(ServiceOption.is_active.is_(True))
        )
    ).all()
    assert rows, "reference data is not loaded — run `make seed`"

    codes = {
        service.id: service.code
        for service in (await session.scalars(select(ServiceType))).all()
    }
    stored: dict[str, set[str]] = {}
    for row in rows:
        stored.setdefault(codes[row.service_type_id], set()).add(row.code)

    # Per service type, not a total: a count alone passes with all twenty-five
    # attached to the wrong kind of help, which is the mis-association the rest
    # of this change goes to some trouble to prevent.
    assert stored == {
        code: {row[0] for row in rows} for code, rows in SERVICE_OPTIONS.items()
    }


@pytest.mark.asyncio
async def test_a_line_dropped_from_the_checklist_is_retired_not_deleted(
    session,
) -> None:
    """`offers.option_ids` holds plain integers and references nothing.

    A deleted row would leave an offer pointing at a label that is gone, which
    is why `seed_languages` retires a code rather than removing it and why this
    does the same.
    """
    from students_cz.db.models import ServiceOption, ServiceType
    from students_cz.db.seed import _seed_options

    insurance = await session.scalar(
        select(ServiceType).where(ServiceType.code == "insurance")
    )
    before = (
        await session.scalars(
            select(ServiceOption).where(ServiceOption.service_type_id == insurance.id)
        )
    ).all()
    assert len(before) >= 2

    # Seed a shorter list: everything but the first line.
    keep = [
        (row.code, "x", "x", "x", "x") for row in sorted(before, key=lambda r: r.sort)[1:]
    ]
    await _seed_options(session, insurance, keep)
    await session.flush()

    dropped = await session.scalar(
        select(ServiceOption).where(ServiceOption.id == before[0].id)
    )
    assert dropped is not None, "the row was deleted, not retired"
    assert dropped.is_active is False


def _seeded_synonyms() -> dict[str, set[str]]:
    """Every subject's synonyms, out of the file the seed reads."""
    import json

    data = json.loads(
        (Path(__file__).resolve().parents[1] / "seeds/subjects.json").read_text()
    )

    out: dict[str, set[str]] = {}

    def walk(nodes: Any) -> None:
        for node in nodes:
            out[node["slug"]] = set(node.get("synonyms") or [])
            walk(node.get("children", []))

    walk(data["groups"])
    return out


def test_seed_and_migrations_agree_about_synonyms() -> None:
    """The same rule the service types follow, for the words that find them.

    Subjects are seeded from a file and never by a migration, so a migration
    that edits `synonyms` is the only way a change reaches production — and the
    two drifting apart is invisible until a production query answers differently
    from every developer's. A migration declares what it touches under
    `SYNONYM_ADDS` and `SYNONYM_REMOVES`; this holds the seed to it.
    """
    seeded = _seeded_synonyms()
    checked = 0
    for path in sorted(VERSIONS.glob("*.py")):
        for slug, words in _constant(path, "SYNONYM_ADDS", {}).items():
            assert slug in seeded, f"{path.name} names a subject the seed has not: {slug}"
            missing = sorted(set(words) - seeded[slug])
            assert missing == [], f"{path.name} adds synonyms the seed lacks: {missing}"
            checked += 1
        for slug, words in _constant(path, "SYNONYM_REMOVES", {}).items():
            assert slug in seeded, f"{path.name} names a subject the seed has not: {slug}"
            left = sorted(set(words) & seeded[slug])
            assert left == [], f"{path.name} removes synonyms the seed still has: {left}"
            checked += 1
    assert checked, "no migration declares a synonym change"


def _seeded_subject_names() -> dict[str, dict[str, str]]:
    """Every subject's names, out of the file the seed reads."""
    import json

    data = json.loads(
        (Path(__file__).resolve().parents[1] / "seeds/subjects.json").read_text()
    )

    out: dict[str, dict[str, str]] = {}

    def walk(nodes: Any) -> None:
        for node in nodes:
            out[node["slug"]] = dict(node["names"])
            walk(node.get("children", []))

    walk(data["groups"])
    return out


def test_seed_and_migrations_agree_about_subject_names() -> None:
    """The same rule again, for what a subject is called.

    Subject names reach production from a migration only, like their synonyms,
    so a migration that renames one declares it under `SUBJECT_RENAMES` — slug
    to the languages it rewrites — and the seed file has to say the same. The
    later migration wins where two rename the same name.
    """
    seeded = _seeded_subject_names()
    renamed: dict[str, dict[str, str]] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        for slug, names in _constant(path, "SUBJECT_RENAMES", {}).items():
            assert slug in seeded, f"{path.name} names a subject the seed has not: {slug}"
            renamed.setdefault(slug, {}).update(names)
    assert renamed, "no migration declares a subject rename"
    assert renamed == {
        slug: {lang: seeded[slug].get(lang) for lang in names}
        for slug, names in renamed.items()
    }
