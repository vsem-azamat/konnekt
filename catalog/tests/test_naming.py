"""The rule that turns a reference row into a name.

Five modules read names off the taxonomy, and four of them used to reach across
the package boundary into `catalog` for a private helper to do it. Now that the
rule has a home it gets a test of its own — the fallbacks in it are the
difference between a Ukrainian speaker seeing the Czech name of their faculty
and seeing a blank row, and nothing above this level would notice which.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import Institution, InstitutionI18n, Subject, SubjectI18n
from students_cz.db.models.enums import UiLang
from students_cz.services.naming import names_by_id, rows_by_id, short_form, translated

pytestmark = pytest.mark.asyncio


@contextmanager
def statements(session: AsyncSession) -> Generator[list[tuple[str, Any]]]:
    """Every statement the session sends while the block runs, with its values.

    Two of `rows_by_id`'s promises are about the query it does *not* send —
    that `None` is dropped rather than asked about, and that an empty set of
    ids costs nothing. Both are invisible in the return value: `IN (NULL)`
    still matches the real ids, and a predicate that is always false still
    answers `{}`. A test that only reads the result passes with either
    promise deleted, which is what happened to the first two written here.

    The values come along because the alternative was counting `$` in the SQL,
    which asks the test to know the driver's paramstyle — true of asyncpg,
    false of psycopg, and a failure that would say nothing about the rule.
    """
    sent: list[tuple[str, Any]] = []
    # The session is bound to a connection, not to the engine — see the
    # `session` fixture, which nests every test in a transaction it rolls back.
    # Listening on the engine still catches it: a connection joins the engine's
    # dispatch when it is created, and every execute re-reads the engine's flag.
    engine = session.get_bind().engine

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        sent.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield sent
    finally:
        event.remove(engine, "before_cursor_execute", record)


def values_of(sent: list[tuple[str, Any]], table: str) -> list[Any]:
    """The parameters of every statement that touched a table.

    By what the statement says rather than by its position in the list: a
    savepoint or an autoflush ahead of the one under test would otherwise shift
    the index, and the failure would name the wrong thing.
    """
    return [parameters for statement, parameters in sent if f"FROM {table}" in statement]


def subject_named(**by_lang: str) -> Subject:
    # `path` is the materialised tree path and is not nullable; the seeder
    # fills it after the flush that assigns an id. Nothing here reads it.
    row = Subject(slug="x", kind="leaf", path="")
    row.names = [
        SubjectI18n(lang=UiLang(lang), name=name) for lang, name in by_lang.items()
    ]
    return row


def institution_named(name: str, short: str | None) -> Institution:
    row = Institution(code="x")
    row.names = [InstitutionI18n(lang=UiLang.CS, name=name, short_name=short)]
    return row


async def test_the_asked_language_wins() -> None:
    row = subject_named(cs="Matematická analýza", ru="Матанализ")

    assert translated(row, UiLang.RU) == "Матанализ"


async def test_a_missing_translation_falls_back_to_any_other() -> None:
    """Not to nothing. A Czech name is a worse answer than a Ukrainian one and
    a far better answer than an empty row."""
    row = subject_named(cs="Matematická analýza")

    assert translated(row, UiLang.UK) == "Matematická analýza"


async def test_a_row_with_no_names_at_all_says_so() -> None:
    assert translated(subject_named(), UiLang.CS) is None


async def test_an_empty_string_is_not_a_translation() -> None:
    """The fallback has to keep looking past it, or a blank row in the asked
    language hides a real name in another one."""
    row = subject_named(uk="", cs="Matematická analýza")

    assert translated(row, UiLang.UK) == "Matematická analýza"


async def test_another_attribute_follows_the_same_rule() -> None:
    row = institution_named("České vysoké učení technické", "ČVUT")

    assert translated(row, UiLang.RU, "short_name") == "ČVUT"


async def test_the_short_form_is_the_short_name_when_there_is_one() -> None:
    row = institution_named("České vysoké učení technické", "ČVUT")

    assert short_form(row, UiLang.CS) == "ČVUT"


async def test_the_short_form_falls_back_to_the_full_name() -> None:
    """A chip with nothing in it is worse than a chip that is too long."""
    row = institution_named("Slezská univerzita v Opavě", None)

    assert short_form(row, UiLang.CS) == "Slezská univerzita v Opavě"


async def test_rows_by_id_never_asks_about_none(session: AsyncSession) -> None:
    """An offer without a subject is ordinary, not an error.

    Asserted on the statement rather than the answer: `id IN (1, NULL)` returns
    the same row as `id IN (1)`, so a version that passed the `None` straight
    through would look correct here and send a parameter that means nothing.
    """
    subject = subject_named(cs="Fyzika")
    session.add(subject)
    await session.flush()

    with statements(session) as sent:
        found = await rows_by_id(session, Subject, [subject.id, None, None])

    assert list(found) == [subject.id]
    # One value asked about, not three. Only the lookup is examined — the names
    # arrive in a second statement because the relationship loads `selectin`,
    # and how many queries that costs is not this function's promise.
    assert values_of(sent, "subjects") == [(subject.id,)]


async def test_rows_by_id_asks_nothing_when_there_is_nothing_to_ask(
    session: AsyncSession,
) -> None:
    """Also on the statement: `IN ()` compiles to a predicate that is always
    false and answers `{}` too, so the empty answer proves nothing."""
    with statements(session) as sent:
        assert await rows_by_id(session, Subject, [None]) == {}

    assert sent == []


async def test_names_by_id_renders_what_rows_by_id_finds(
    session: AsyncSession,
) -> None:
    subject = subject_named(cs="Fyzika", ru="Физика")
    session.add(subject)
    await session.flush()

    assert await names_by_id(session, Subject, [subject.id], UiLang.RU) == {
        subject.id: "Физика"
    }


async def test_names_by_id_answers_with_a_string_for_an_untranslated_row(
    session: AsyncSession,
) -> None:
    """Its callers put the value straight into a field that cannot be null."""
    subject = subject_named()
    session.add(subject)
    await session.flush()

    assert await names_by_id(session, Subject, [subject.id], UiLang.CS) == {
        subject.id: ""
    }
