from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_now
from app.db.models import Chat
from app.db.upsert import insert_for


class ChatRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, chat_id: int) -> Chat | None:
        """Get chat by ID."""
        result = await self.db.execute(select(Chat).filter(Chat.id == chat_id))
        return result.scalars().first()

    async def exists(self, chat_id: int) -> bool:
        """Check if chat exists."""
        result = await self.db.execute(select(Chat.id).filter(Chat.id == chat_id))
        return result.scalars().first() is not None

    async def save(self, chat: Chat) -> Chat:
        """Save chat."""
        chat_model = await self.get_by_id(chat.id)
        if chat_model:
            chat_model.title = chat.title
            chat_model.resource_status = chat.resource_status
            chat_model.is_forum = chat.is_forum
            chat_model.welcome_message = chat.welcome_message
            chat_model.time_delete = chat.time_delete
            chat_model.is_welcome_enabled = chat.is_welcome_enabled
            chat_model.join_mode = chat.join_mode
        else:
            chat_model = Chat(
                id=chat.id,
                title=chat.title,
                resource_status=chat.resource_status,
                is_forum=chat.is_forum,
                welcome_message=chat.welcome_message,
                time_delete=chat.time_delete,
                is_welcome_enabled=chat.is_welcome_enabled,
                join_mode=chat.join_mode,
            )
            self.db.add(chat_model)

        await self.db.commit()
        await self.db.refresh(chat_model)
        return chat_model

    async def get_chats(self) -> list[Chat]:
        """Get all chats as models."""
        result = await self.db.execute(select(Chat))
        return list(result.scalars().all())

    async def merge_chat(
        self,
        id_tg_chat: int,
        title: str | None = None,
        is_forum: bool | None = None,
        *,
        is_public: bool = False,
    ) -> None:
        """Record a chat's title and forum flag, creating it if new.

        One statement, for the same reason as users: two updates from a chat
        the bot has just joined arrive together.

        A new chat starts in the join mode the bot acted in before there were
        modes: a public one's requests are Telegram's and go to the admins, a
        private one's come through the bot's link, which asked for none.
        """
        changed = {name: value for name, value in (("title", title), ("is_forum", is_forum)) if value is not None}
        statement = insert_for(self.db, Chat).values(
            id=id_tg_chat,
            title=title,
            is_forum=is_forum or False,
            join_mode=Chat.JOIN_ADMINS if is_public else Chat.JOIN_OPEN,
        )
        if changed:
            # Only when something changed, or every message rewrites the row.
            differs = or_(*(getattr(Chat, name).is_distinct_from(statement.excluded[name]) for name in changed))
            statement = statement.on_conflict_do_update(
                index_elements=[Chat.id], set_={**changed, "modified_at": utc_now()}, where=differs
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=[Chat.id])
        await self.db.execute(statement)
        await self.db.commit()

    async def update_welcome_message(self, id_tg_chat: int, message: str) -> None:
        """Set the greeting and switch it on: a moderator who wrote one means it to be sent."""
        await self.db.execute(
            update(Chat).filter(Chat.id == id_tg_chat).values(welcome_message=message, is_welcome_enabled=True)
        )
        await self.db.commit()


def get_chat_repository(db: AsyncSession) -> ChatRepository:
    return ChatRepository(db)
