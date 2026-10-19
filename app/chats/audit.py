"""What Telegram says about each chat, against what the project expects.

Read-only unless asked to `--apply`. Project chats drifted apart because nothing compared them: the bot
held different rights in different groups, and whether a group had a link or a
pinned rules message was known only by opening it. This pass asks Telegram
about every chat in the `chats` table and lists what is off, so the comparison
can be repeated whenever drift is suspected:

    docker compose exec bot python -m app.chats.audit          # table
    docker compose exec bot python -m app.chats.audit --json   # everything

The expected rights are the ones the bot asks for when it is added
(`DEFAULT_ADMIN_RIGHTS`); an approved chat's description is held to
`app/chats/template.py`. Titles and pins are reported, not judged (#202).

`--apply` writes the template's description wherever the bot may change the
chat's info, and `--chat ID` (repeatable) narrows the run:

    docker compose exec bot python -m app.chats.audit --apply --chat -1001370017010

For a private group the link shown is the bot's own invite link, which lets
anyone in: keep the output out of public issues.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import logging
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TextIO, cast

from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramRetryAfter
from sqlalchemy import select

from app.chats.metadata import ask
from app.chats.snapshots import PAUSE_BETWEEN_CHATS_SECONDS
from app.chats.template import expected_description, main_chats
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
    "permissions",
)
# Telegram omits this right when it equals can_pin_messages.
_DEFAULTS_TO = {"can_manage_tags": "can_pin_messages"}


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
    expected_description: str | None = None
    findings: tuple[str, ...] = ()
    applied: tuple[str, ...] = ()


def _preview(message: Any) -> str | None:
    if message is None:
        return None
    text = getattr(message, "text", None) or getattr(message, "caption", None) or "(no text)"
    return text if len(text) <= PINNED_PREVIEW_CHARS else text[: PINNED_PREVIEW_CHARS - 1] + "…"


def _missing_rights(member: Any, *, is_forum: bool) -> tuple[str, ...]:
    if getattr(member, "status", None) == "creator":
        return ()

    def held(name: str) -> bool:
        value = getattr(member, name, None)
        if value is None and name in _DEFAULTS_TO:
            value = getattr(member, _DEFAULTS_TO[name], None)
        return bool(value)

    return tuple(name for name in _EXPECTED_RIGHTS if not held(name) and (is_forum or name not in _FORUM_ONLY_RIGHTS))


def _not_checked(err: TelegramAPIError, *, refused: str, skipped: str = "not checked") -> str:
    if isinstance(err, TelegramRetryAfter):
        return f"{skipped}: flood control"
    if isinstance(err, TelegramNetworkError):
        return f"{skipped}: network"
    return f"{refused}: {err.message}"


def _setting(info: Any, name: str) -> Any:
    value = getattr(info, name, None)
    return value.model_dump(exclude_none=True) if hasattr(value, "model_dump") else value


def _is_username_link(link: str) -> bool:
    tail = link.rstrip("/").rsplit("/", 1)[-1]
    return not tail.startswith("+") and "joinchat" not in link


async def inspect_chat(
    bot: Bot,
    chat: Chat,
    *,
    bot_username: str | None = None,
    parent: Chat | None = None,
    university: bool = False,
) -> ChatState:
    """One chat as Telegram sees it. Never raises for a chat Telegram refuses.

    With the bot's username, an approved chat's description is also compared
    with the template.
    """
    state = ChatState(
        chat_id=chat.id,
        title=chat.title,
        resource_status=chat.resource_status,
        parent_chat_id=chat.parent_chat_id,
        public_link=chat.public_link,
        reachable=False,
    )
    try:
        info = await ask(lambda: bot.get_chat(chat.id))
    except TelegramAPIError as err:
        return dataclasses.replace(state, findings=(_not_checked(err, refused="bot cannot see the chat"),))
    try:
        member = await ask(lambda: bot.get_chat_member(chat.id, bot.id))
    except TelegramAPIError as err:
        member, member_error = None, _not_checked(err, refused="bot's membership unknown")
    else:
        member_error = None

    status = getattr(member, "status", None)
    is_forum = bool(info.is_forum)
    missing = _missing_rights(member, is_forum=is_forum) if status in {"administrator", "creator"} else ()
    link = f"https://t.me/{info.username}" if info.username else info.invite_link

    findings: list[str] = []
    if member_error:
        findings.append(member_error)
    elif status not in {"administrator", "creator"}:
        findings.append("bot is not an administrator")
    if missing:
        findings.append("missing rights: " + ", ".join(missing))
    if link is None:
        findings.append("no link")
    if chat.public_link and _is_username_link(chat.public_link):
        if not info.username:
            findings.append("catalogue links a username the chat no longer has")
        elif not chat.public_link.rstrip("/").casefold().endswith(f"/{info.username.casefold()}"):
            findings.append("catalogue link differs from the chat's username")

    expected = None
    if bot_username and chat.is_approved:
        expected = expected_description(
            title=info.title or chat.title or "",
            current=info.description or "",
            bot=bot_username,
            university=university,
            parent=parent,
        )
        if (info.description or "") != expected:
            findings.append("description differs from the template")

    return dataclasses.replace(
        state,
        title=info.title or chat.title,
        reachable=True,
        bot_status=status,
        missing_rights=missing,
        link=link,
        description=info.description,
        pinned=_preview(info.pinned_message),
        settings={name: _setting(info, name) for name in _SETTINGS},
        expected_description=expected,
        findings=tuple(findings),
    )


async def apply_template(bot: Bot, state: ChatState) -> list[str]:
    """Bring one inspected chat to the template, as far as the bot may. Returns what was done."""
    expected = state.expected_description
    if expected is None or not state.reachable or (state.description or "") == expected:
        return []
    if state.bot_status is None:
        return ["description: rights unknown"]
    if state.bot_status not in {"administrator", "creator"} or "can_change_info" in state.missing_rights:
        return ["description: no right to change it"]
    try:
        await ask(lambda: bot.set_chat_description(chat_id=state.chat_id, description=expected))
    except TelegramNetworkError:
        # The request may have landed; the next audit will tell.
        return ["description outcome unknown: network"]
    except TelegramAPIError as err:
        return [_not_checked(err, refused="description refused", skipped="description not set")]
    return ["description set"]


async def audit_chats(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    bot: Bot,
    pause_seconds: float = PAUSE_BETWEEN_CHATS_SECONDS,
    apply: bool = False,
    chat_ids: set[int] | None = None,
) -> list[ChatState]:
    """Every chat in the table (or those asked for), one after another, paced like the snapshot loop."""
    bot_username = (await ask(bot.me)).username
    async with session_maker() as session:
        chats = (await session.execute(select(Chat).order_by(Chat.id))).scalars().all()
    by_id = {chat.id: chat for chat in chats}
    # From the whole table, before --chat narrows it: whether a chat is a
    # university's depends on the others.
    mains = main_chats(list(chats))
    if chat_ids is not None:
        chats = [chat for chat in chats if chat.id in chat_ids]

    states: list[ChatState] = []
    for index, chat in enumerate(chats):
        if index and pause_seconds:
            await asyncio.sleep(pause_seconds)
        state = await inspect_chat(
            bot,
            chat,
            bot_username=bot_username,
            parent=by_id.get(chat.parent_chat_id) if chat.parent_chat_id else None,
            university=chat.id in mains or chat.parent_chat_id in mains,
        )
        if apply:
            state = dataclasses.replace(state, applied=tuple(await apply_template(bot, state)))
        states.append(state)
    return states


def _table(states: list[ChatState]) -> str:
    lines = ["chat_id\tstatus\tbot\tlink\tpinned\ttitle\tfindings\tapplied"]
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
                    "; ".join(s.applied) or "-",
                ]
            )
        )
    return "\n".join(lines)


async def _main(*, as_json: bool, apply: bool, chat_ids: set[int] | None) -> None:
    from aiogram import Bot

    from app.core.config import settings
    from app.db import session as db

    # The report owns stdout. Logging was pointed at stdout when the app was
    # imported, so its handlers are moved; anything printed directly follows.
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
            cast("logging.StreamHandler[TextIO]", handler).setStream(sys.stderr)
    with contextlib.redirect_stdout(sys.stderr):
        bot = Bot(token=settings.telegram.token)
        try:
            states = await audit_chats(session_maker=db.get_session_maker(), bot=bot, apply=apply, chat_ids=chat_ids)
        finally:
            await bot.session.close()
            await db.close_db()

    if chat_ids:
        unknown = sorted(chat_ids - {s.chat_id for s in states})
        if unknown:
            print("not in the chats table: " + ", ".join(map(str, unknown)), file=sys.stderr)
    if as_json:
        json.dump([dataclasses.asdict(s) for s in states], sys.stdout, ensure_ascii=False, indent=2, default=str)
    else:
        print(_table(states))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="every field, as JSON")
    parser.add_argument("--apply", action="store_true", help="write the template's description where the bot may")
    parser.add_argument("--chat", type=int, action="append", help="only this chat id; repeatable")
    args = parser.parse_args()
    asyncio.run(_main(as_json=args.json, apply=args.apply, chat_ids=set(args.chat) if args.chat else None))
