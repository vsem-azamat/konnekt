"""What the catalog no longer holds: rentals, study materials, moderation
verdicts, and the columns nothing ever filled.

The tables go with the migration that removes them; the columns leave the
models first and the database a release later, so the release before can still
run while the deploy migrates (docs/invariants.md).
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
UNMAPPED_COLUMNS = {
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
    assert UNMAPPED_COLUMNS.isdisjoint(mapped)


async def test_the_database_no_longer_has_the_tables(session: AsyncSession) -> None:
    tables = set(
        await session.scalars(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
    )
    types = set(await session.scalars(text("SELECT typname FROM pg_type")))
    assert DROPPED_TABLES.isdisjoint(tables)
    assert DROPPED_TYPES.isdisjoint(types)


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
