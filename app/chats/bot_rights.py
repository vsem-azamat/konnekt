"""The bot's own status and rights in each chat, kept as Telegram reports them.

The one writer of `chat_bot_rights` and its history. Telegram sends the bot an
update about itself whenever somebody adds it, removes it or changes what it
may do, and that update is the source. A daily check asks `getChatMember` for
the bot in every chat it has not heard about lately: a downtime loses updates,
and chats from before this table never sent one.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import or_, select

from app.chats.metadata import ask
from app.chats.metrics import BOT_RIGHTS_MISSING
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import Chat, ChatBotRights, ChatBotRightsChange
from app.db.upsert import insert_for

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import ChatMemberUnion
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger("chats.bot_rights")

# The rights moderation cannot do without, by the problem their absence is reported as.
NEEDED_RIGHTS = {
    "no_delete": "can_delete_messages",
    "no_restrict": "can_restrict_members",
    "no_invite": "can_invite_users",
}
PROBLEMS = ("left", "not_admin", *NEEDED_RIGHTS, "unknown")
# The bot is not in the chat; only an update adding it back changes that.
GONE = ("left", "kicked")


def rights_of(member: ChatMemberUnion) -> dict[str, bool]:
    """Every true-or-false field Telegram gave, under its own names.

    A right Telegram left out is left out here too: it omits `can_manage_tags`
    when it equals `can_pin_messages`, and guessing would record a change
    Telegram never made.
    """
    return {name: value for name, value in member.model_dump().items() if isinstance(value, bool)}


async def record(
    db: AsyncSession, chat_id: int, member: ChatMemberUnion, *, at: datetime.datetime, by: int | None = None
) -> None:
    """Take what Telegram said the bot is in `chat_id` at `at`, and commit."""
    # aiogram hands the status over as its enum, whose str() is the enum's name.
    await _record(db, chat_id, str(getattr(member.status, "value", member.status)), rights_of(member), at=at, by=by)


async def _record(
    db: AsyncSession, chat_id: int, status: str, rights: dict[str, bool], *, at: datetime.datetime, by: int | None
) -> None:
    """Updates arrive late and are replayed: one older than what is stored
    changes nothing. A change of status or of any right is added to the
    history; the same state again only moves `known_at`.

    The first state is inserted in one statement: the bot added and promoted
    in the same second arrives as two updates handled at once, and a locked
    read finds nothing to lock while there is no row.
    """
    created = await db.execute(
        insert_for(db, ChatBotRights)
        .values(chat_id=chat_id, status=status, rights=rights, changed_at=at, known_at=at)
        .on_conflict_do_nothing(index_elements=[ChatBotRights.chat_id])
        .returning(ChatBotRights.chat_id)
    )
    if created.first() is None:
        row = await db.get(ChatBotRights, chat_id, with_for_update=True, populate_existing=True)
        if row is None or row.known_at > at:
            await db.rollback()
            return
        if row.status == status and row.rights == rights:
            row.known_at = at
            await db.commit()
            return
        row.status, row.rights, row.changed_at, row.known_at = status, rights, at, at
    db.add(ChatBotRightsChange(chat_id=chat_id, status=status, rights=rights, changed_by=by, changed_at=at))
    await db.commit()
    logger.info("bot_rights_changed", chat_id=chat_id, status=status, changed_by=by)


def problems_of(status: str, rights: dict[str, bool]) -> list[str]:
    """What keeps the bot from moderating, by the names the gauge reports them under."""
    if status in GONE:
        return ["left"]
    if status == "creator":
        return []
    if status != "administrator":
        return ["not_admin"]
    return [problem for problem, right in NEEDED_RIGHTS.items() if not rights.get(right)]


async def refresh_gauge(session: AsyncSession) -> None:
    """Count the approved chats by what the bot lacks there, from what is stored."""
    rows = (
        await session.execute(
            select(ChatBotRights.status, ChatBotRights.rights)
            .select_from(Chat)
            .outerjoin(ChatBotRights, ChatBotRights.chat_id == Chat.id)
            .where(Chat.resource_status == Chat.STATUS_APPROVED)
        )
    ).all()
    counts = dict.fromkeys(PROBLEMS, 0)
    for status, rights in rows:
        for problem in ["unknown"] if status is None else problems_of(status, rights):
            counts[problem] += 1
    for problem, count in counts.items():
        BOT_RIGHTS_MISSING.labels(problem=problem).set(count)


async def check_once(*, session_maker: async_sessionmaker[AsyncSession], bot: Bot) -> int:
    """Ask Telegram about the bot in every chat not confirmed lately. Returns how many were asked.

    Only chats Telegram can answer about: not one known by its invite link
    alone, nor a group that became a supergroup, nor one the bot is known not
    to be in, whether the hourly loop found Telegram does not know the chat
    or the bot was recorded as gone. The update adding the bot back is what
    brings such a chat back. A chat that refuses otherwise is skipped until
    the next tick.
    """
    config = settings.chat_state
    due = utc_now() - datetime.timedelta(hours=config.recheck_after_hours)
    async with session_maker() as session:
        chat_ids = (
            await session.scalars(
                select(Chat.id)
                .outerjoin(ChatBotRights, ChatBotRights.chat_id == Chat.id)
                .where(
                    Chat.id > Chat.PREVIEW_ID_CEILING,
                    Chat.migrated_to_chat_id.is_(None),
                    Chat.bot_absent_at.is_(None),
                    or_(
                        ChatBotRights.known_at.is_(None),
                        (ChatBotRights.known_at < due) & ChatBotRights.status.not_in(GONE),
                    ),
                )
                .order_by(Chat.id)
            )
        ).all()

    asked = 0
    for chat_id in chat_ids:
        if asked:
            await asyncio.sleep(config.pause_between_chats_seconds)
        asked += 1
        # Telegram dates its updates in whole seconds; a change it makes in
        # the second after this question must still count as newer.
        at = utc_now().replace(microsecond=0)
        try:
            member = await ask(lambda chat_id=chat_id: bot.get_chat_member(chat_id, bot.id))
        except TelegramForbiddenError as err:
            # The one answer a bot no longer in the chat gets: a kick says so, leaving does not.
            gone = "kicked" if "kicked" in err.message.lower() else "left"
            async with session_maker() as session:
                await _record(session, chat_id, gone, {}, at=at, by=None)
            continue
        except TelegramRetryAfter:
            # Over the limit: the rest wait for the next tick rather than add to it.
            logger.warning("bot_rights_check_flooded", asked=asked, due=len(chat_ids))
            break
        except TelegramAPIError as err:
            logger.warning("bot_rights_check_failed", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
            continue
        async with session_maker() as session:
            await record(session, chat_id, member, at=at)
    return asked


async def run_check_loop(*, session_maker: async_sessionmaker[AsyncSession], bot: Bot) -> None:
    """Forever-loop. Cancelled on shutdown via task.cancel().

    Wakes every tick and asks only what is due, so a restart does not ask
    every chat again.
    """
    while True:
        try:
            await check_once(session_maker=session_maker, bot=bot)
        except Exception:
            logger.exception("bot_rights_check iteration failed")
        await asyncio.sleep(settings.chat_state.tick_minutes * 60)
