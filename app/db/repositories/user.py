from sqlalchemy import insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UserNotFoundException
from app.core.time import utc_now
from app.db.models import User
from app.db.upsert import insert_for


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, user_id: int) -> User | None:
        result = await self.db.execute(select(User).filter(User.id == user_id))
        return result.scalars().first()

    async def exists(self, user_id: int) -> bool:
        result = await self.db.execute(select(User.id).filter(User.id == user_id))
        return result.scalars().first() is not None

    async def upsert_profile(
        self, user_id: int, *, username: str | None, first_name: str | None, last_name: str | None
    ) -> None:
        """Record what Telegram says about a person, creating them if new.

        Never touches `blocked` or `verify`. One statement, so two updates
        from a new user at once cannot both try to create them.
        """
        profile = {"username": username, "first_name": first_name, "last_name": last_name}
        statement = insert_for(self.db, User).values(id=user_id, **profile, created_at=utc_now(), modified_at=utc_now())
        # Only when something changed: every message from a person would
        # otherwise rewrite their row and bump modified_at.
        changed = or_(*(getattr(User, name).is_distinct_from(statement.excluded[name]) for name in profile))
        await self.db.execute(
            statement.on_conflict_do_update(
                index_elements=[User.id], set_={**profile, "modified_at": utc_now()}, where=changed
            )
        )
        await self.db.commit()

    async def save(self, user: User) -> User:
        user_model = await self.get_by_id(user.id)
        if user_model:
            user_model.username = user.username
            user_model.first_name = user.first_name
            user_model.last_name = user.last_name
            user_model.verify = user.verify
            user_model.blocked = user.blocked
        else:
            user_model = User(
                id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                verify=user.verify,
                blocked=user.blocked,
            )
            self.db.add(user_model)

        await self.db.commit()
        await self.db.refresh(user_model)
        return user_model

    async def get_blocked_users(self) -> list[User]:
        result = await self.db.execute(select(User).filter(User.blocked))
        return list(result.scalars().all())

    async def find_blocked_user(self, identifier: str) -> User | None:
        """Find blocked user by username (without @) or user_id."""
        # Remove @ prefix if present
        if identifier.startswith("@"):
            identifier = identifier[1:]

        # Try to find by user_id if identifier is numeric
        if identifier.isdigit():
            user_id = int(identifier)
            result = await self.db.execute(select(User).filter(User.id == user_id, User.blocked))
        else:
            # Search by username
            result = await self.db.execute(select(User).filter(User.username == identifier, User.blocked))

        return result.scalars().first()

    async def add_to_blacklist(self, id_tg: int) -> None:
        user = await self.get_by_id(id_tg)
        if user:
            await self.db.execute(update(User).where(User.id == id_tg).values(blocked=True))
        else:
            await self.db.execute(insert(User).values(id=id_tg, blocked=True))
        await self.db.commit()

    async def remove_from_blacklist(self, id_tg: int) -> None:
        user = await self.get_by_id(id_tg)
        if user:
            await self.db.execute(update(User).where(User.id == id_tg).values(blocked=False))
            await self.db.commit()
        else:
            raise UserNotFoundException(id_tg)


def get_user_repository(db: AsyncSession) -> "UserRepository":
    return UserRepository(db)
