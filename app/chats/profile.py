"""What Telegram says a chat is, written into its row in one place.

Every answer `getChat` gives is taken here, whoever asked: the daily pass of
the hourly loop, the photo notice, the console's refresh button. They used to
copy the title, the join setting and the photo each in their own way, and the
rest of what Telegram said (username, description, slow mode, permissions)
was thrown away.

The title alone is also taken from every update (`ChatRepository.merge_chat`):
each one carries it, and a rename shows up with the next message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.chats.avatars import sync_photo

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.chats.avatars import Outcome
    from app.chats.metadata import ChatMetadata
    from app.db.models import Chat


async def apply(*, session: AsyncSession, bot: Bot, chat: Chat, metadata: ChatMetadata) -> Outcome:
    """Take one `getChat` answer, photo included. Caller commits. Returns what became of the photo.

    The title only when Telegram gave one: an empty one is not a rename.
    Settings the admins choose here (welcome, join mode, parent) are not
    Telegram's and are never touched.
    """
    if metadata.title and metadata.title != chat.title:
        chat.title = metadata.title
    chat.join_by_request = metadata.join_by_request
    chat.username = metadata.username
    chat.description = metadata.description
    chat.chat_type = metadata.chat_type
    chat.is_forum = metadata.is_forum
    chat.slow_mode_delay = metadata.slow_mode_delay
    chat.permissions = metadata.permissions
    chat.has_protected_content = metadata.has_protected_content
    chat.has_hidden_members = metadata.has_hidden_members
    chat.has_aggressive_anti_spam_enabled = metadata.has_aggressive_anti_spam_enabled
    chat.message_auto_delete_time = metadata.message_auto_delete_time
    chat.linked_chat_id = metadata.linked_chat_id
    return await sync_photo(session=session, bot=bot, chat=chat, metadata=metadata)
