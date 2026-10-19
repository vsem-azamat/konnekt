"""What Telegram says about each chat, against what the project expects.

Read-only. Project chats drifted apart because nothing compared them: the bot
held different rights in different groups, and whether a group had a link or a
pinned rules message was known only by opening it. This pass asks Telegram
about every chat in the `chats` table and lists what is off, so the comparison
can be repeated whenever drift is suspected:

    docker compose exec bot python -m app.chats.audit          # table
    docker compose exec bot python -m app.chats.audit --json   # everything

The expected rights are the ones the bot asks for when it is added
(`DEFAULT_ADMIN_RIGHTS`). Titles, descriptions and pins are reported, not
judged: the template for them is the owner's to agree.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from app.chats.metadata import ask
from app.db.models import Chat
from app.presentation.telegram.profile import DEFAULT_ADMIN_RIGHTS

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PINNED_PREVIEW_CHARS = 120
# Topics exist only in forums; elsewhere Telegram reports the right as off and it means nothing.
_FORUM_ONLY_RIGHTS = frozenset({"can_manage_topics"})
_EXPECTED_RIGHTS = tuple(
    name for name, value in DEFAULT_ADMIN_RIGHTS.model_dump().items() if isinstance(value, bool) and value
)
# The settings a per-kind chat profile will be agreed on, copied as Telegram gives them.
_SETTINGS = (
    "is_forum",
    "slow_mode_delay",
    "join_by_request",
    "has_protected_content",
    "has_visible_history",
    "has_hidden_members",
    "has_aggressive_anti_spam_enabled",
    "message_auto_delete_time",
    "linked_chat_id",
)


@dataclass(frozen=True)
class ChatState:
    chat_id: int
    title: str | None
    resource_status: str
    parent_chat_id: int | None
    public_link: str | None
    reachable: bool
    bot_status: str | None = None
    missing_rights: tuple[str, ...] = ()
    link: str | None = None
    description: str | None = None
    pinned: str | None = None
    settings: dict[str, Any] = dataclasses.field(default_factory=dict)
    findings: tuple[str, ...] = ()


def _preview(message: Any) -> str | None:
    if message is None:
        return None
    text = getattr(message, "text", None) or getattr(message, "caption", None) or "(no text)"
    return text if len(text) <= PINNED_PREVIEW_CHARS else text[: PINNED_PREVIEW_CHARS - 1] + "…"


def _missing_rights(member: Any, *, is_forum: bool) -> tuple[str, ...]:
    if getattr(member, "status", None) == "creator":
        return ()
    return tuple(
        name
        for name in _EXPECTED_RIGHTS
        if not getattr(member, name, False) and (is_forum or name not in _FORUM_ONLY_RIGHTS)
    )


async def inspect_chat(bot: Bot, chat: Chat) -> ChatState:
    """One chat as Telegram sees it. Never raises for a chat Telegram refuses."""
    base = {
        "chat_id": chat.id,
        "title": chat.title,
        "resource_status": chat.resource_status,
        "parent_chat_id": chat.parent_chat_id,
        "public_link": chat.public_link,
    }
    try:
        info = await ask(lambda: bot.get_chat(chat.id))
        member = await ask(lambda: bot.get_chat_member(chat.id, bot.id))
    except TelegramAPIError:
        return ChatState(**base, reachable=False, findings=("bot cannot see the chat",))

    status = getattr(member, "status", None)
    is_forum = bool(info.is_forum)
    missing = _missing_rights(member, is_forum=is_forum) if status in {"administrator", "creator"} else ()
    link = f"https://t.me/{info.username}" if info.username else info.invite_link

    findings: list[str] = []
    if status not in {"administrator", "creator"}:
        findings.append("bot is not an administrator")
    if missing:
        findings.append("missing rights: " + ", ".join(missing))
    if link is None:
        findings.append("no link")
    if chat.public_link and info.username and not chat.public_link.rstrip("/").endswith(f"/{info.username}"):
        findings.append("catalogue link differs from the chat's username")

    return ChatState(
        **{**base, "title": info.title or chat.title},
        reachable=True,
        bot_status=status,
        missing_rights=missing,
        link=link,
        description=info.description,
        pinned=_preview(info.pinned_message),
        settings={name: getattr(info, name, None) for name in _SETTINGS},
        findings=tuple(findings),
    )


async def audit_chats(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    bot: Bot,
    pause_seconds: float = 1.0,
) -> list[ChatState]:
    """Every chat in the table, one after another, paced like the snapshot loop."""
    async with session_maker() as session:
        chats = (await session.execute(select(Chat).order_by(Chat.id))).scalars().all()

    states: list[ChatState] = []
    for index, chat in enumerate(chats):
        if index and pause_seconds:
            await asyncio.sleep(pause_seconds)
        states.append(await inspect_chat(bot, chat))
    return states


def _table(states: list[ChatState]) -> str:
    lines = ["chat_id\tstatus\tbot\tlink\tpinned\ttitle\tfindings"]
    for s in states:
        lines.append(
            "\t".join(
                [
                    str(s.chat_id),
                    s.resource_status,
                    s.bot_status or "-",
                    s.link or "-",
                    "yes" if s.pinned else "-",
                    s.title or "-",
                    "; ".join(s.findings) or "ok",
                ]
            )
        )
    return "\n".join(lines)


async def _main(as_json: bool) -> None:
    from aiogram import Bot

    from app.core.config import settings
    from app.db import session as db

    bot = Bot(token=settings.telegram.token)
    try:
        states = await audit_chats(session_maker=db.get_session_maker(), bot=bot)
    finally:
        await bot.session.close()
        # Disposed directly: close_db() logs to stdout, which is where the report goes.
        if db.engine is not None:
            await db.engine.dispose()

    if as_json:
        json.dump([dataclasses.asdict(s) for s in states], sys.stdout, ensure_ascii=False, indent=2, default=str)
    else:
        print(_table(states))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="every field, as JSON")
    asyncio.run(_main(parser.parse_args().json))
