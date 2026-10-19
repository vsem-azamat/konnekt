from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import and_

from app.db.models import Message
from app.db.upsert import insert_for


class MessageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def save(self, message: Message) -> Message:
        """Save message."""
        # Check if message exists
        existing_query = select(Message).where(
            and_(
                Message.chat_id == message.chat_id,
                Message.user_id == message.user_id,
                Message.message_id == message.message_id,
            )
        )
        result = await self.db.execute(existing_query)
        existing = result.scalars().first()

        if existing:
            # Update existing
            existing.message = message.message
            existing.message_info = message.message_info or {}
            existing.spam = message.spam
        else:
            # Create new
            new_message = Message(
                chat_id=message.chat_id,
                user_id=message.user_id,
                message_id=message.message_id,
                message=message.message,
                message_info=message.message_info or {},
                spam=message.spam,
            )
            self.db.add(new_message)

        await self.db.commit()

        # Return updated message
        return message

    async def add_message(
        self,
        chat_id: int,
        user_id: int,
        message_id: int,
        message: str | None,
        message_info: dict[str, Any],
        *,
        replace: bool = False,
    ) -> None:
        """One row per message: a redelivery changes nothing, an edit (`replace`) its text."""
        statement = insert_for(self.db, Message).values(
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            message=message,
            message_info=message_info,
        )
        key = [Message.chat_id, Message.message_id]
        if replace:
            statement = statement.on_conflict_do_update(
                index_elements=key, set_={"message": message, "message_info": message_info}
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=key)
        await self.db.execute(statement)
        await self.db.commit()

    async def label_spam(self, chat_id: int, message_id: int, *, unless_edited_after: int | None = None) -> bool:
        """Mark a message's stored text as spam; returns whether it was marked.

        ``unless_edited_after`` is when the moderator saw the message: a text
        edited after that is not what they judged, and marking it would teach
        the filter whatever the author changed it to.
        """
        row = await self.db.scalar(
            select(Message).where(and_(Message.chat_id == chat_id, Message.message_id == message_id))
        )
        if row is None:
            return False
        edited_at = (row.message_info or {}).get("edit_date")
        if unless_edited_after is not None and isinstance(edited_at, int) and edited_at > unless_edited_after:
            return False
        row.spam = True
        await self.db.commit()
        return True

    async def get_user_messages(self, user_id: int, chat_id: int | None = None) -> list[Message]:
        """Get messages by user, optionally filtered by chat."""
        query = select(Message).where(Message.user_id == user_id)
        if chat_id is not None:
            query = query.where(Message.chat_id == chat_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_user_chats(self, user_id: int) -> int:
        query = select(func.count(func.distinct(Message.chat_id))).where(Message.user_id == user_id)
        result = await self.db.execute(query)
        count = result.scalar()
        return count or 0

    async def count_user_messages(self, user_id: int) -> int:
        query = select(func.count()).where(Message.user_id == user_id)
        result = await self.db.execute(query)
        count = result.scalar()
        return count or 0

    async def has_previous_messages(self, chat_id: int, user_id: int, *, before_message_id: int | None = None) -> bool:
        """Check if user has any previous messages in this chat.

        ``before_message_id`` leaves out the message being asked about and any
        after it: history is saved before the spam check runs, so counting
        everything counted the message itself, and no message was ever a first.
        """
        query = select(func.count()).where(Message.user_id == user_id, Message.chat_id == chat_id)
        if before_message_id is not None:
            query = query.where(Message.message_id < before_message_id)
        result = await self.db.execute(query)
        count = result.scalar()
        return count is not None and count > 0

    async def is_similar_spam_message(self, message: str) -> bool:
        query = select(func.count()).where(Message.message == message, Message.spam)
        result = await self.db.execute(query)
        count = result.scalar()
        return count is not None and count > 0


def get_message_repository(db: AsyncSession) -> MessageRepository:
    return MessageRepository(db)
