"""Who may moderate, and where.

Two questions, and only the second one is ever the right one to ask before
acting: not "is this person an administrator" but "is this person an
administrator *here*". The first is still useful for deciding what to print in
the help text, and nothing else.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Admin, AdminChat


class AdminRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, admin_id: int) -> Admin | None:
        """Get admin by ID."""
        result = await self.db.execute(select(Admin).filter(Admin.id == admin_id))
        return result.scalars().first()

    async def save(self, admin: Admin) -> Admin:
        """Save admin."""
        admin_model = await self._get_admin_model(admin.id)
        if admin_model:
            admin_model.state = admin.state
        else:
            admin_model = Admin(id=admin.id, state=admin.state)
            self.db.add(admin_model)

        await self.db.commit()
        await self.db.refresh(admin_model)
        return admin_model

    async def delete(self, admin_id: int) -> None:
        """Remove an administrator entirely, in every chat they were trusted in."""
        await self.db.execute(delete(Admin).where(Admin.id == admin_id))
        await self.db.commit()

    async def is_admin(self, user_id: int) -> bool:
        """Whether this person moderates anywhere at all.

        Good enough to decide which half of the help text to show. Never good
        enough to authorise an action — use :meth:`is_admin_in` for that.
        """
        result = await self.db.execute(select(Admin).where(Admin.id == user_id).where(Admin.state))
        return result.scalars().first() is not None

    async def is_admin_in(self, user_id: int, chat_id: int) -> bool:
        """Whether this person may act in this chat.

        One indexed lookup on a two-column primary key, once per command. The
        previous version cached the whole administrator list for five minutes,
        which is a sensible trade when the answer is the same everywhere and a
        bad one now that it differs per chat — a stale cache would hand somebody
        a chat they were removed from.
        """
        result = await self.db.execute(
            select(AdminChat.chat_id)
            .join(Admin, Admin.id == AdminChat.admin_id)
            .where(AdminChat.admin_id == user_id)
            .where(AdminChat.chat_id == chat_id)
            .where(Admin.state)
        )
        return result.first() is not None

    async def chats_for(self, user_id: int) -> list[int]:
        """Every chat this person moderates, oldest grant first."""
        result = await self.db.execute(
            select(AdminChat.chat_id).where(AdminChat.admin_id == user_id).order_by(AdminChat.granted_at)
        )
        return list(result.scalars().all())

    async def grant(self, user_id: int, chat_id: int, *, granted_by: int | None = None) -> bool:
        """Trust somebody with one chat. False when they already had it."""
        if await self.is_admin_in(user_id, chat_id):
            return False

        admin = await self._get_admin_model(user_id)
        if admin is None:
            self.db.add(Admin(id=user_id))
        elif not admin.state:
            admin.state = True

        self.db.add(AdminChat(admin_id=user_id, chat_id=chat_id, granted_by=granted_by))
        await self.db.commit()
        return True

    async def revoke(self, user_id: int, chat_id: int) -> bool:
        """Take one chat back. False when they did not have it.

        Losing the last chat means losing the job: an administrator row with no
        chats can do nothing, and leaving it behind would make the list of
        administrators longer than the list of people who moderate anything.
        """
        found = await self.db.execute(
            select(AdminChat).where(AdminChat.admin_id == user_id).where(AdminChat.chat_id == chat_id)
        )
        scope = found.scalars().first()
        if scope is None:
            return False

        await self.db.delete(scope)
        await self.db.flush()

        remaining = await self.db.execute(select(AdminChat.chat_id).where(AdminChat.admin_id == user_id).limit(1))
        if remaining.first() is None:
            await self.db.execute(delete(Admin).where(Admin.id == user_id))

        await self.db.commit()
        return True

    async def _get_admin_model(self, admin_id: int) -> Admin | None:
        """Get admin model by ID."""
        result = await self.db.execute(select(Admin).filter(Admin.id == admin_id))
        return result.scalars().first()


def get_admin_repository(db: AsyncSession) -> AdminRepository:
    return AdminRepository(db)
