"""One captcha decision about a chat at a time."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_chat(db: AsyncSession, chat_id: int) -> None:
    """Serialise work on one chat's captchas until the transaction ends.

    PostgreSQL only; the test database runs one request at a time anyway.
    """
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": chat_id})
