"""The agreed description of a project chat.

Approved by the owner on 2026-10-19 (#155). A university chat gets the shared
description below: a university's main chat or a chat under one. A dormitory
chat carries its university's institution too, so when several top chats share
one, the main chat is the one with chats under it (see `main_chats`). Any other project
chat keeps its own words and only loses the links that no longer lead anywhere
useful: the network channel is not run, and contacts go through the bot.

Titles and the bot's rules pin come later (#202). Until the rules are pinned,
the description does not promise them.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models import Chat

DESCRIPTION_LIMIT = 255  # Telegram's limit for a group description
DEFAULT_EMOJI = "🎓"
RETIRED_HANDLES = ("@konnekt_cz", "@konnekt_net", "@czech_media", "@czechopen", "@work_azamat")
_LEADING_SYMBOLS = re.compile(r"^[^\w@]+")


def _short_name(title: str) -> str:
    return title.split(" | ")[0].strip()


def _leading_emoji(text: str) -> str:
    match = _LEADING_SYMBOLS.match(text.strip())
    return match.group(0).strip() if match else ""


def _username(link: str | None) -> str | None:
    if not link:
        return None
    tail = link.rstrip("/").rsplit("/", 1)[-1]
    return None if tail.startswith("+") or "joinchat" in link else f"@{tail}"


def main_chats(chats: list[Chat]) -> set[int]:
    """The ids of the chats that are a university's main chat."""
    parents = {chat.parent_chat_id for chat in chats if chat.parent_chat_id is not None}
    holders: dict[str, list[Chat]] = {}
    for chat in chats:
        if chat.parent_chat_id is None and chat.institution_code:
            holders.setdefault(chat.institution_code, []).append(chat)
    return {chat.id for roots in holders.values() for chat in roots if len(roots) == 1 or chat.id in parents}


def _is_university(parent: Chat | None, *, is_main: bool) -> bool:
    return bool(parent.institution_code) if parent is not None else is_main


def _without_retired_links(text: str) -> str:
    lines = [line for line in text.splitlines() if not any(h in line.casefold() for h in RETIRED_HANDLES)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def expected_description(
    chat: Chat, *, current: str, bot: str, parent: Chat | None = None, is_main: bool = False
) -> str:
    """What the chat's description should read, given what it reads now.

    The parent is passed in rather than read from the chat: the relationship
    would load lazily, which an async session refuses.
    """
    if not _is_university(parent, is_main=is_main):
        return _without_retired_links(current)

    emoji = _leading_emoji(current) or DEFAULT_EMOJI
    lines = []
    main = _username(parent.public_link) if parent is not None else None
    if parent is not None and main:
        lines.append(f"Главный чат {_short_name(parent.title or '')}: {main}")
    lines.append(f"Все чаты и помощь с учёбой: @{bot}")

    tail = "\n" + "\n".join(lines)
    head = f"{emoji} Чат студентов и абитуриентов "
    room = DESCRIPTION_LIMIT - len(head) - len(tail)
    # The main chat goes by its short name ("ČVUT", not "ČVUT | ЧВУТ"); a chat
    # under it by its whole title, which is what tells it apart.
    name = (chat.title or "") if parent is not None else _short_name(chat.title or "")
    return head + name[:room] + tail
