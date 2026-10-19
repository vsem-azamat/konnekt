"""A group upgraded to a supergroup, followed to its new id.

Telegram gives the upgraded chat a new `-100…` id: making a group public or
turning topics on is enough. Everything this project keeps about the chat was
on the old id, so the new one arrived as a stranger, `discovered`, and the
approval gate silenced it, its moderators lost their rights there, and its
listing pointed at a chat that no longer exists. Nothing was logged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update

from app.core.logging import get_logger
from app.db.models import AdminChat, Chat
from app.db.upsert import insert_for

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("chats.migration")

# What belongs to the chat rather than to the Telegram object: decided here,
# by people, and kept across the upgrade.
_CARRIED = (
    "resource_status",
    "welcome_message",
    "time_delete",
    "is_welcome_enabled",
    "is_captcha_enabled",
    "is_service_cleanup_enabled",
    "parent_chat_id",
    "relation_notes",
    "public_link",
    "institution_code",
)


async def follow_upgrade(db: AsyncSession, *, old_id: int, new_id: int) -> bool:
    """Move a chat's settings, moderators and children to its new id.

    Returns whether anything moved. Telegram announces an upgrade in both
    chats; a second announcement finds the old row already retired.
    """
    old = await db.get(Chat, old_id)
    if old is None or old.resource_status == Chat.STATUS_DISABLED:
        return False
    new = await db.get(Chat, new_id)
    if new is None:
        new = Chat(id=new_id, title=old.title)
        db.add(new)

    carried = {name: getattr(old, name) for name in _CARRIED}
    old_status = old.resource_status
    old.public_link = None
    old.resource_status = Chat.STATUS_DISABLED
    old.relation_notes = f"Стал супергруппой {new_id}"
    if new.resource_status == Chat.STATUS_APPROVED:
        # Somebody already decided about the new chat; the old one's settings
        # must not undo that, its approval and its link least of all.
        carried = {name: value for name, value in carried.items() if getattr(new, name) in (None, False)}
        carried.pop("resource_status", None)
        # Restoring approval must not silently republish a link: only an
        # approved old chat's link may follow it.
        if old_status != Chat.STATUS_APPROVED:
            carried.pop("public_link", None)
    for name, value in carried.items():
        setattr(new, name, value)
    await db.flush()

    moderators = (await db.scalars(select(AdminChat).where(AdminChat.chat_id == old_id))).all()
    if moderators:
        await db.execute(
            insert_for(db, AdminChat)
            .values([{"admin_id": m.admin_id, "chat_id": new_id, "granted_by": m.granted_by} for m in moderators])
            .on_conflict_do_nothing(index_elements=[AdminChat.admin_id, AdminChat.chat_id])
        )
    await db.execute(delete(AdminChat).where(AdminChat.chat_id == old_id))
    await db.execute(update(Chat).where(Chat.parent_chat_id == old_id).values(parent_chat_id=new_id))
    await db.commit()

    logger.warning("chat_upgraded", old_id=old_id, new_id=new_id, moderators=len(moderators))
    return True
