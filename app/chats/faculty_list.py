"""A university chat's list of its faculties' chats, pinned and kept by the bot.

Each university chat pinned a list typed by hand, and it went stale the moment
a chat was added or a link changed. Built here from the rows the catalog lists,
so it says what the catalog says. The bot pins it once, silently, and from then
on edits that message in place: an edit notifies nobody, a new pin notifies
everybody.

Only in the chats named in `faculty_list_chats`: thousands read a pinned
message, so a chat gets one once its text was approved for it. A message that
somebody removed stays removed; the bot does not post it again.
"""

from __future__ import annotations

import asyncio
import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.chats.metrics import FACULTY_LIST_EVENTS
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import Chat, ChatBotRights, FacultyList

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger("chats.faculty_list")

TITLE = "📌 <b>Чаты факультетов {university}</b>"
# The same list as an answer to /chats: in a faculty's chat it is the whole university's.
FACULTIES_HEADING = "<b>Чаты факультетов {university}</b>"
UNIVERSITY_HEADING = "<b>Чаты {university}</b>"
FOOTER = "Чаты других вузов и факультетов — тоже в Konnekt 👇"
# Past the budget the rest is counted, not listed; the button leads to all of them.
MORE = "…и ещё {count} — в Konnekt"
# Telegram refuses a message over 4096 characters of visible text; room is left for the rest.
TEXT_BUDGET = 3500
APP_BUTTON = "Все чаты в Konnekt 📱"
# What a university chat's title holds besides the university's own name: «ČVUT | ЧВУТ».
TITLE_SEPARATOR = " | "
SYNC_INTERVAL_SECONDS = 900
PAUSE_BETWEEN_CHATS_SECONDS = 1.0
# How Telegram says an edit changed nothing, and that the message is not there.
NOT_MODIFIED = "message is not modified"
NOT_FOUND = "message to edit not found"
PIN_NOT_FOUND = "message to pin not found"


@dataclass(frozen=True)
class Faculty:
    title: str
    link: str


def university_name(title: str) -> str:
    return title.split(TITLE_SEPARATOR, 1)[0].strip()


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def text(university: str, faculties: list[Faculty], *, heading: str = TITLE) -> str:
    """The message: a heading, one linked line per chat, and the way to the rest."""
    lines = [heading.format(university=html.escape(university)), ""]
    # Counted as Telegram counts, in UTF-16 units of the text a reader sees.
    used = sum(_units(line) for line in (university, FOOTER, MORE))
    for index, f in enumerate(faculties):
        used += _units(f"• {f.title}\n")
        if used > TEXT_BUDGET:
            lines.append(MORE.format(count=len(faculties) - index))
            break
        lines.append(f'• <a href="{html.escape(f.link)}">{html.escape(f.title)}</a>')
    lines += ["", FOOTER]
    return "\n".join(lines)


def app_url(bot_username: str, code: str) -> str:
    """The same university in the app, where each chat shows its size and activity."""
    return f"https://t.me/{bot_username}?startapp=uni-{code}"


def markup(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=APP_BUTTON, url=url)]])


async def faculties(session: AsyncSession, chat_id: int) -> list[Faculty]:
    """The chats under `chat_id` that the catalog lists, by name.

    By name and not by size, as the catalog orders them: sizes move every day,
    and each move would be an edit of a message thousands have pinned.
    """
    rows = await session.execute(
        select(Chat.title, Chat.public_link)
        .where(Chat.parent_chat_id == chat_id)
        .where(Chat.resource_status.in_(Chat.LISTABLE_STATUSES))
        .where(Chat.public_link.is_not(None))
        .where(Chat.title.is_not(None))
        # The id breaks ties: two chats of one name must not swap places, each swap an edit.
        .order_by(Chat.title, Chat.id)
    )
    return [Faculty(title, link) for title, link in rows.all()]


async def university_of(session: AsyncSession, chat: Chat) -> str | None:
    """The university code of `chat` when it is a university's own chat with listed chats under it.

    By the same rule as the list: a button to faculties the catalog does not
    list would open an empty section.
    """
    if chat.parent_chat_id is not None or not chat.institution_code:
        return None
    return chat.institution_code if await faculties(session, chat.id) else None


@dataclass(frozen=True)
class Listing:
    """What /chats answers in a university's chat."""

    heading: str
    university: str
    code: str
    chats: list[Faculty]


async def listing_for(session: AsyncSession, chat_id: int) -> Listing | None:
    """In a university's own chat its faculties; in a faculty's, the whole university; elsewhere None."""
    chat = await session.get(Chat, chat_id)
    if chat is None or not chat.title:
        return None
    if code := await university_of(session, chat):
        return Listing(FACULTIES_HEADING, university_name(chat.title), code, await faculties(session, chat.id))
    parent = await session.get(Chat, chat.parent_chat_id) if chat.parent_chat_id else None
    # An undecided university's Telegram title is not for an answer, whatever sits under it.
    if parent is None or not parent.title or parent.resource_status not in Chat.LISTABLE_STATUSES:
        return None
    if not (code := await university_of(session, parent)):
        return None
    own = [Faculty(parent.title, parent.public_link)] if parent.public_link else []
    return Listing(UNIVERSITY_HEADING, university_name(parent.title), code, own + await faculties(session, parent.id))


async def may_pin(session: AsyncSession, chat_id: int) -> bool:
    rights = await session.get(ChatBotRights, chat_id)
    return rights is not None and rights.status == "administrator" and bool(rights.rights.get("can_pin_messages"))


async def sync_chat(session: AsyncSession, bot: Bot, chat: Chat) -> str:
    """Pin the list in `chat`, or bring the pinned one up to date; returns what happened."""
    kept = await session.get(FacultyList, chat.id)
    if kept is not None and kept.gone_at is not None:
        return "gone"
    if not chat.institution_code or not chat.title:
        logger.warning("faculty_list_no_university", chat_id=chat.id)
        return "no_university"
    listed = await faculties(session, chat.id)
    if not listed:
        return "empty"
    body = text(university_name(chat.title), listed)
    me = await bot.me()
    url = app_url(me.username or "", chat.institution_code)
    buttons = markup(url)

    if kept is None:
        if not await may_pin(session, chat.id):
            logger.warning("faculty_list_cannot_pin", chat_id=chat.id)
            return "no_pin_right"
        sent = await bot.send_message(
            chat.id, body, reply_markup=buttons, disable_notification=True, disable_web_page_preview=True
        )
        # Recorded before the pin: a pin that fails leaves a message to pin next time, not a second one.
        kept = FacultyList(chat.id, sent.message_id, body, url)
        session.add(kept)
        try:
            await session.commit()
        # Cancelled at shutdown as well: unrecorded either way.
        except BaseException:
            # Unrecorded, it would be posted again next time: taken back instead.
            await bot.delete_message(chat.id, sent.message_id)
            raise
        logger.info("faculty_list_posted", chat_id=chat.id, message_id=sent.message_id, chats=len(listed))
        await _pin(session, bot, kept)
        return "posted"

    if kept.pinned_at is None:
        try:
            await _pin(session, bot, kept)
        except TelegramBadRequest as err:
            if PIN_NOT_FOUND not in str(err):
                raise
            return await _gone(session, kept)
    # The button too: a university whose code changed would open an empty section.
    if kept.text == body and kept.button_url == url:
        return "unchanged"
    try:
        await bot.edit_message_text(
            body, chat_id=chat.id, message_id=kept.message_id, reply_markup=buttons, disable_web_page_preview=True
        )
    except TelegramBadRequest as err:
        if NOT_FOUND in str(err):
            return await _gone(session, kept)
        if NOT_MODIFIED not in str(err):
            raise
        kept.text, kept.button_url = body, url
        await session.commit()
        return "unchanged"
    kept.text, kept.button_url = body, url
    await session.commit()
    logger.info("faculty_list_edited", chat_id=chat.id, message_id=kept.message_id, chats=len(listed))
    return "edited"


async def _gone(session: AsyncSession, kept: FacultyList) -> str:
    """Somebody removed the message; it stays removed."""
    kept.gone_at = utc_now()
    await session.commit()
    logger.warning("faculty_list_gone", chat_id=kept.chat_id, message_id=kept.message_id)
    return "gone"


async def _pin(session: AsyncSession, bot: Bot, kept: FacultyList) -> None:
    """Pin it without a sound, once; a pin that failed is tried again on the next round."""
    await bot.pin_chat_message(kept.chat_id, kept.message_id, disable_notification=True)
    kept.pinned_at = utc_now()
    await session.commit()


async def sync_once(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    bot: Bot,
    pause_seconds: float = PAUSE_BETWEEN_CHATS_SECONDS,
) -> dict[str, int]:
    """Every chat named in the settings; returns the outcomes counted."""
    counts: dict[str, int] = {}
    for index, chat_id in enumerate(settings.telegram.faculty_list_chats):
        if index:
            await asyncio.sleep(pause_seconds)
        async with session_maker() as session:
            try:
                chat = await session.get(Chat, chat_id)
                if chat is None or chat.resource_status != Chat.STATUS_APPROVED:
                    # Named by mistake, or taken down since: the bot speaks only in its own chats.
                    logger.warning("faculty_list_chat_not_approved", chat_id=chat_id)
                    outcome = "not_approved"
                else:
                    outcome = await sync_chat(session, bot, chat)
            except Exception:
                await session.rollback()
                logger.exception("faculty_list_sync_failed", chat_id=chat_id)
                outcome = "failed"
        FACULTY_LIST_EVENTS.labels(event=outcome).inc()
        counts[outcome] = counts.get(outcome, 0) + 1
    if counts:
        logger.info("faculty_lists_checked", **counts)
    return counts


async def run_sync_loop(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    bot: Bot,
    interval_seconds: int = SYNC_INTERVAL_SECONDS,
) -> None:
    """Forever-loop, cancelled on shutdown. Does nothing while no chat is named."""
    while True:
        try:
            await sync_once(session_maker=session_maker, bot=bot)
        except Exception:
            logger.exception("faculty_list_loop_iteration_failed")
        await asyncio.sleep(interval_seconds)
