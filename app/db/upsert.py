"""INSERT ... ON CONFLICT, in whichever dialect the session speaks.

Read-then-insert loses races that Telegram makes routine: a new member's album
arrives as several updates at once, each saw no row, and every one after the
first failed on the primary key. Production is PostgreSQL; the tests run on
SQLite, and both spell the statement the same way through their own insert.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects import postgresql, sqlite

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def insert_for(db: AsyncSession, table: Any) -> Any:
    """The dialect's INSERT for `table`, which has on_conflict_do_update."""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        return postgresql.insert(table)
    if dialect == "sqlite":
        return sqlite.insert(table)
    raise NotImplementedError(f"no upsert for {dialect}")
