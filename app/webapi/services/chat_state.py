"""What the bot recorded about its own place in a chat and the chat's administrators, for the console.

Read from `chat_bot_rights`, its history and `chat_members`, which the bot
keeps from Telegram's updates and its daily check (app/chats/bot_rights.py,
app/chats/members.py). Nothing here asks Telegram.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import case, select

from app.db.models import ChatBotRights, ChatBotRightsChange, ChatMember, User
from app.webapi.schemas import BotChange, ChatAdmin, ChatBot, ChatPerson

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Changes of the bot's rights shown on the chat page; a chat's whole history is a few a year.
HISTORY_LIMIT = 20
ADMINISTRATORS = ("creator", "administrator")


async def bot(session: AsyncSession, chat_id: int) -> ChatBot | None:
    """The bot in the chat as Telegram last said; None until it was asked."""
    row = await session.get(ChatBotRights, chat_id)
    if row is None:
        return None
    return ChatBot(status=row.status, rights=row.rights, changed_at=row.changed_at, known_at=row.known_at)


async def history(session: AsyncSession, chat_id: int) -> list[BotChange]:
    """The bot's changes of status or rights, newest first, with who made each when Telegram said."""
    rows = (
        await session.execute(
            select(ChatBotRightsChange, User)
            .outerjoin(User, User.id == ChatBotRightsChange.changed_by)
            .where(ChatBotRightsChange.chat_id == chat_id)
            .order_by(ChatBotRightsChange.changed_at.desc(), ChatBotRightsChange.id.desc())
            .limit(HISTORY_LIMIT)
        )
    ).all()
    return [
        BotChange(
            id=change.id,
            status=change.status,
            rights=change.rights,
            changed_at=change.changed_at,
            changed_by=_person(change.changed_by, user) if change.changed_by is not None else None,
        )
        for change, user in rows
    ]


async def admins(session: AsyncSession, chat_id: int) -> list[ChatAdmin]:
    """The chat's owner and administrators, the owner first, then by name, the nameless last."""
    rows = (
        await session.execute(
            select(ChatMember, User)
            .outerjoin(User, User.id == ChatMember.user_id)
            .where(ChatMember.chat_id == chat_id, ChatMember.status.in_(ADMINISTRATORS))
            .order_by(
                case((ChatMember.status == "creator", 0), else_=1),
                User.first_name.asc().nulls_last(),
                ChatMember.user_id,
            )
        )
    ).all()
    return [
        ChatAdmin(
            **_person(member.user_id, user).model_dump(),
            status="creator" if member.status == "creator" else "administrator",
            known_at=member.known_at,
        )
        for member, user in rows
    ]


def _person(user_id: int, user: User | None) -> ChatPerson:
    return ChatPerson(
        user_id=user_id,
        username=user.username if user else None,
        first_name=user.first_name if user else None,
        last_name=user.last_name if user else None,
    )
