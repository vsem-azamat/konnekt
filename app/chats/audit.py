"""What the bot recorded about each chat, against what the project expects.

Read-only unless asked to `--apply`. Project chats drifted apart because nothing compared them: the bot
held different rights in different groups, and whether a group had a link was
known only by opening it. This pass lists what is off in every chat in the
`chats` table, so the comparison can be repeated whenever drift is suspected:

    docker compose exec bot python -m app.chats.audit          # table
    docker compose exec bot python -m app.chats.audit --json   # everything

Telegram is not asked: the chat's profile is what `getChat` last answered
(app/chats/profile.py, daily), the bot's rights are what its own updates and
daily check recorded (app/chats/bot_rights.py), and `synced_at` says how old
the profile is. The expected rights are the ones the bot asks for when it is
added (`DEFAULT_ADMIN_RIGHTS`); an approved chat's description is held to
`app/chats/template.py`. Titles are reported, not judged (#202).

`--apply` asks Telegram about each chat whose description is off, records the
answer, and writes the template's description wherever the bot may change the
chat's info; `--chat ID` (repeatable) narrows the run:

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

from app.chats import profile
from app.chats.bot_rights import GONE
from app.chats.members import ADMINISTRATORS
from app.chats.metadata import ask, fetch_metadata
from app.chats.rights import DEFAULT_ADMIN_RIGHTS
from app.chats.snapshots import PAUSE_BETWEEN_CHATS_SECONDS
from app.chats.template import OWN_WORDS, expected_description, main_chats, own_words_fit
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import Chat, ChatBotRights

if TYPE_CHECKING:
    import datetime

    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger("chats.audit")

# Topics exist only in forums; elsewhere Telegram reports the right as off and it means nothing.
_FORUM_ONLY_RIGHTS = frozenset({"can_manage_topics"})
# Asked for by the bot's rule of every right, used by nothing: the bot sends no
# welcomes. Bot API added it after the bot was in every chat, so holding chats to
# it would report all of them for a right nobody needs.
_UNUSED_RIGHTS = frozenset({"can_send_welcome_messages"})
_EXPECTED_RIGHTS = tuple(
    name
    for name, value in DEFAULT_ADMIN_RIGHTS.model_dump().items()
    if isinstance(value, bool) and value and name not in _UNUSED_RIGHTS
)
# The settings a per-kind chat profile will be agreed on, copied as Telegram gives them.
_SETTINGS = (
    "is_forum",
    "slow_mode_delay",
    "join_by_request",
    "has_protected_content",
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
    synced_at: datetime.datetime | None = None
    bot_status: str | None = None
    missing_rights: tuple[str, ...] = ()
    link: str | None = None
    description: str | None = None
    settings: dict[str, Any] = dataclasses.field(default_factory=dict)
    expected_description: str | None = None
    findings: tuple[str, ...] = ()
    applied: tuple[str, ...] = ()


def _missing_rights(status: str, rights: dict[str, bool], *, is_forum: bool) -> tuple[str, ...]:
    if status == "creator":
        return ()

    def held(name: str) -> bool:
        value = rights.get(name)
        if value is None and name in _DEFAULTS_TO:
            value = rights.get(_DEFAULTS_TO[name])
        return bool(value)

    return tuple(name for name in _EXPECTED_RIGHTS if not held(name) and (is_forum or name not in _FORUM_ONLY_RIGHTS))


def _not_checked(err: TelegramAPIError, *, refused: str, skipped: str = "not checked") -> str:
    if isinstance(err, TelegramRetryAfter):
        return f"{skipped}: flood control"
    if isinstance(err, TelegramNetworkError):
        return f"{skipped}: network"
    return f"{refused}: {err.message}"


def _is_username_link(link: str) -> bool:
    tail = link.rstrip("/").rsplit("/", 1)[-1]
    return not tail.startswith("+") and "joinchat" not in link


def inspect_chat(
    chat: Chat,
    rights: ChatBotRights | None,
    *,
    bot_username: str | None = None,
    parent: Chat | None = None,
    university: bool = False,
) -> ChatState:
    """One chat as the bot last recorded it.

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
        synced_at=chat.last_synced_at,
        bot_status=rights.status if rights else None,
    )
    if chat.bot_absent_at is not None or state.bot_status in GONE:
        return dataclasses.replace(state, findings=("bot is not in the chat",))
    if chat.last_synced_at is None:
        return dataclasses.replace(state, findings=("not synced yet",))

    status = state.bot_status
    missing = (
        _missing_rights(status, rights.rights, is_forum=chat.is_forum) if rights and status in ADMINISTRATORS else ()
    )
    link = f"https://t.me/{chat.username}" if chat.username else chat.public_link

    findings: list[str] = []
    if status is None:
        findings.append("bot's membership unknown: not checked yet")
    elif status not in ADMINISTRATORS:
        findings.append("bot is not an administrator")
    if missing:
        findings.append("missing rights: " + ", ".join(missing))
    if link is None:
        findings.append("no link")
    if chat.public_link and _is_username_link(chat.public_link):
        if not chat.username:
            findings.append("catalogue links a username the chat no longer has")
        elif not chat.public_link.rstrip("/").casefold().endswith(f"/{chat.username.casefold()}"):
            findings.append("catalogue link differs from the chat's username")

    expected = None
    if bot_username and chat.is_approved:
        expected = expected_description(
            title=chat.title or "",
            current=chat.description or "",
            bot=bot_username,
            university=university,
            parent=parent,
            own_words=chat.id in OWN_WORDS,
        )
        if chat.id in OWN_WORDS and not own_words_fit(chat.description or "", bot_username):
            findings.append("own words do not fit with the bot line")
        elif (chat.description or "") != expected:
            findings.append("description differs from the template")

    return dataclasses.replace(
        state,
        reachable=True,
        missing_rights=missing,
        link=link,
        description=chat.description,
        settings={name: getattr(chat, name) for name in _SETTINGS},
        expected_description=expected,
        findings=tuple(findings),
    )


def _off_template(state: ChatState) -> bool:
    expected = state.expected_description
    return expected is not None and state.reachable and (state.description or "") != expected


async def apply_template(bot: Bot, state: ChatState) -> list[str]:
    """Bring one inspected chat to the template, as far as the bot may. Returns what was done."""
    expected = state.expected_description
    if expected is None or not _off_template(state):
        return []
    if state.bot_status is None:
        return ["description: rights unknown"]
    if state.bot_status not in ADMINISTRATORS or "can_change_info" in state.missing_rights:
        return ["description: no right to change it"]
    try:
        await ask(lambda: bot.set_chat_description(chat_id=state.chat_id, description=expected))
    except TelegramNetworkError:
        # The request may have landed; the next audit will tell.
        return ["description outcome unknown: network"]
    except TelegramAPIError as err:
        return [_not_checked(err, refused="description refused", skipped="description not set")]
    return ["description set"]


async def _resync(*, session_maker: async_sessionmaker[AsyncSession], bot: Bot, chat_id: int) -> Chat | None:
    """Ask Telegram about the chat now and record the answer, so the description written is judged against
    what is there rather than what was there at the last daily pass. None when Telegram would not say."""
    metadata = await fetch_metadata(bot=bot, chat_id=chat_id)
    if metadata is None:
        return None
    async with session_maker() as session:
        chat = await session.get(Chat, chat_id)
        if chat is None:
            return None
        if await profile.apply(session=session, bot=bot, chat=chat, metadata=metadata) != "failed":
            chat.last_synced_at = utc_now()
        await session.commit()
        return chat


async def audit_chats(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    bot: Bot,
    pause_seconds: float = PAUSE_BETWEEN_CHATS_SECONDS,
    apply: bool = False,
    chat_ids: set[int] | None = None,
) -> list[ChatState]:
    """Every chat in the table (or those asked for). With `apply`, the ones off the template are
    asked about again and corrected one after another, paced like the snapshot loop."""
    bot_username = (await ask(bot.me)).username
    async with session_maker() as session:
        chats = (await session.execute(select(Chat).order_by(Chat.id))).scalars().all()
        rights = {row.chat_id: row for row in (await session.execute(select(ChatBotRights))).scalars()}
    by_id = {chat.id: chat for chat in chats}
    # From the whole table, before --chat narrows it: whether a chat is a
    # university's depends on the others.
    mains = main_chats(list(chats))
    if stray := sorted(OWN_WORDS - {chat.id for chat in chats if chat.is_approved}):
        logger.warning("own_words_not_approved", chat_ids=stray)
    if chat_ids is not None:
        chats = [chat for chat in chats if chat.id in chat_ids]
    # Known only by an invite link: there is no id Telegram would answer about.
    chats = [chat for chat in chats if not chat.is_preview_only]

    def inspect(chat: Chat) -> ChatState:
        return inspect_chat(
            chat,
            rights.get(chat.id),
            bot_username=bot_username,
            parent=by_id.get(chat.parent_chat_id) if chat.parent_chat_id else None,
            university=chat.id in mains or chat.parent_chat_id in mains,
        )

    states: list[ChatState] = []
    asked = 0
    for chat in chats:
        state = inspect(chat)
        if apply and _off_template(state):
            if asked and pause_seconds:
                await asyncio.sleep(pause_seconds)
            asked += 1
            fresh = await _resync(session_maker=session_maker, bot=bot, chat_id=chat.id)
            if fresh is None:
                state = dataclasses.replace(state, applied=("description not set: Telegram did not answer",))
            else:
                state = inspect(fresh)
                state = dataclasses.replace(state, applied=tuple(await apply_template(bot, state)))
        states.append(state)
    return states


def _table(states: list[ChatState]) -> str:
    lines = ["chat_id\tstatus\tbot\tlink\tsynced\ttitle\tfindings\tapplied"]
    for s in states:
        lines.append(
            "\t".join(
                [
                    str(s.chat_id),
                    s.resource_status,
                    s.bot_status or "-",
                    s.link or "-",
                    f"{s.synced_at:%Y-%m-%d %H:%M}" if s.synced_at else "-",
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
