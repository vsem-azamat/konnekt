"""What the catalog no longer holds: rentals, study materials, moderation
verdicts, and the columns nothing ever filled.

The tables went with the migration that removed them; the columns left the
models a release before the database, so the release before could still run
while the deploy migrated (docs/invariants.md).
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import Base

DROPPED_TABLES = {"items", "materials", "moderation_reviews"}
DROPPED_TYPES = {
    "item_kind",
    "item_condition",
    "item_status",
    "material_kind",
    "material_access",
    "moderated_entity",
    "moderation_verdict",
}
DROPPED_COLUMNS = {
    ("helper_profiles", "reviews_count"),
    ("institutions", "logo_url"),
    ("item_categories", "allows_rent"),
    ("item_categories", "allows_sale"),
    ("weekly_availability", "valid_until"),
    ("contacts", "replied_at"),
    ("user_education", "is_current"),
    ("user_education", "started_year"),
    ("user_education", "finished_year"),
}

MIGRATION = next(
    Path(__file__)
    .parents[1]
    .glob("src/students_cz/db/migrations/versions/*_drop_rentals_materials_reviews.py")
)


def _migration():
    spec = importlib.util.spec_from_file_location("drop_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_models_no_longer_map_them() -> None:
    assert DROPPED_TABLES.isdisjoint(Base.metadata.tables)
    mapped = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
    }
    assert DROPPED_COLUMNS.isdisjoint(mapped)


async def test_the_database_no_longer_has_the_tables(session: AsyncSession) -> None:
    tables = set(
        await session.scalars(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
    )
    types = set(await session.scalars(text("SELECT typname FROM pg_type")))
    assert DROPPED_TABLES.isdisjoint(tables)
    assert DROPPED_TYPES.isdisjoint(types)


async def test_the_database_no_longer_has_the_columns(session: AsyncSession) -> None:
    columns = set(
        (
            await session.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns"
                    " WHERE table_schema = 'public'"
                )
            )
        ).tuples()
    )
    assert DROPPED_COLUMNS.isdisjoint(columns)


def test_autogenerate_hides_no_columns() -> None:
    """The filter that kept the columns out of `alembic check` while they
    waited for their release went with them."""
    env = (MIGRATION.parents[1] / "env.py").read_text()
    assert "RETIRED_COLUMNS" not in env


async def test_the_migration_stops_on_a_table_with_rows(session: AsyncSession) -> None:
    """The drop was agreed on empty tables; one that has filled since is a new
    question, not something to lose quietly."""
    await session.execute(text("CREATE TEMPORARY TABLE materials (id int)"))
    await session.execute(text("INSERT INTO materials VALUES (1)"))
    connection = await session.connection()

    with pytest.raises(RuntimeError, match="materials"):
        await connection.run_sync(_migration().refuse_unless_empty)


async def test_the_migration_passes_empty_or_missing_tables(
    session: AsyncSession,
) -> None:
    await session.execute(text("CREATE TEMPORARY TABLE items (id int)"))
    connection = await session.connection()

    await connection.run_sync(_migration().refuse_unless_empty)


def _column_migration():
    path = next(MIGRATION.parent.glob("*_drop_empty_columns.py"))
    spec = importlib.util.spec_from_file_location("drop_columns", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_column_migration_stops_on_a_filled_column(
    session: AsyncSession,
) -> None:
    await session.execute(text("ALTER TABLE institutions ADD COLUMN logo_url text"))
    await session.execute(
        text(
            "UPDATE institutions SET logo_url = 'x'"
            " WHERE id = (SELECT min(id) FROM institutions)"
        )
    )
    connection = await session.connection()

    with pytest.raises(RuntimeError, match=r"institutions\.logo_url"):
        await connection.run_sync(_column_migration().refuse_unless_empty)


async def test_the_column_migration_passes_columns_at_their_default(
    session: AsyncSession,
) -> None:
    await session.execute(text("ALTER TABLE institutions ADD COLUMN logo_url text"))
    await session.execute(
        text(
            "ALTER TABLE helper_profiles ADD COLUMN reviews_count int NOT NULL DEFAULT 0"
        )
    )
    connection = await session.connection()

    await connection.run_sync(_column_migration().refuse_unless_empty)


async def test_the_column_migration_stops_on_a_flag_set_off(
    session: AsyncSession,
) -> None:
    """For the booleans, `false` is the information: `true` is the default."""
    await session.execute(
        text(
            "ALTER TABLE item_categories"
            " ADD COLUMN allows_rent boolean NOT NULL DEFAULT true"
        )
    )
    await session.execute(
        text("INSERT INTO item_categories (code, allows_rent) VALUES ('probe', false)")
    )
    connection = await session.connection()

    with pytest.raises(RuntimeError, match=r"item_categories\.allows_rent"):
        await connection.run_sync(_column_migration().refuse_unless_empty)
