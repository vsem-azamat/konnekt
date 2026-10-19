"""The agreed description of a project chat.

Approved by the owner on 2026-10-19 (#155). A university chat gets the shared
description below: a university's main chat or a chat under one. A dormitory
chat carries its university's institution too, so when several top chats share
one, the main chat is the one with chats under it (see `main_chats`). Any other project
chat keeps its own words and only loses the links that no longer lead anywhere
useful: the network channel is not run, contacts go through the bot, and the
bots Konnekt moved away from only point onwards (#245).

Titles and the bot's rules pin come later (#202). Until the rules are pinned,
the description does not promise them.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models import Chat

DESCRIPTION_LIMIT = 255  # Telegram's limit for a group description
DEFAULT_EMOJI = "🎓"
# An emoji kept from the old text: at most this many code points (a ZWJ family
# or a flag is several), and never the old network channel's megaphone.
_EMOJI_MAX_CODEPOINTS = 8
_NOT_KEPT = frozenset({"📢", "📩"})
_RETIRED = re.compile(
    r"(?:@|t\.me/)(?:konnekt_cz|konnekt_net|czech_media|czechopen|work_azamat|konnekt_moder_bot|student_cz_bot)\b",
    re.IGNORECASE,
)
_LEADING_SYMBOLS = re.compile(r"^[^\w@\s]+")


def _utf16_len(text: str) -> int:
    """Length as Telegram counts it: UTF-16 code units, the stricter of the two readings."""
    return len(text.encode("utf-16-le")) // 2


def _fit(text: str, room: int) -> str:
    """The longest prefix of whole code points that fits in `room` UTF-16 units."""
    out = ""
    for char in text:
        if _utf16_len(out + char) > room:
            break
        out += char
    return out


def _short_name(title: str) -> str:
    return title.split(" | ")[0].strip()


def _leading_emoji(text: str) -> str:
    first_line = text.strip().split("\n", 1)[0]
    match = _LEADING_SYMBOLS.match(first_line)
    if not match:
        return ""
    emoji = match.group(0)
    if len(emoji) > _EMOJI_MAX_CODEPOINTS or emoji in _NOT_KEPT:
        return ""
    if any(unicodedata.category(char).startswith("P") for char in emoji):
        return ""
    return emoji


def _username(link: str | None) -> str | None:
    if not link:
        return None
    tail = link.rstrip("/").rsplit("/", 1)[-1]
    return None if tail.startswith("+") or "joinchat" in link else f"@{tail}"


def main_chats(chats: list[Chat]) -> set[int]:
    """The ids of the approved chats that are a university's main chat.

    The only approved top chat holding an institution, or, when several hold
    the same one, those with chats under them.
    """
    parents = {chat.parent_chat_id for chat in chats if chat.parent_chat_id is not None}
    holders: dict[str, list[Chat]] = {}
    for chat in chats:
        if chat.parent_chat_id is None and chat.institution_code and chat.is_approved:
            holders.setdefault(chat.institution_code, []).append(chat)
    return {chat.id for roots in holders.values() for chat in roots if len(roots) == 1 or chat.id in parents}


def _without_retired_links(text: str) -> str:
    lines = text.splitlines()
    kept = [line for line in lines if not _RETIRED.search(line)]
    if len(kept) == len(lines):
        return text
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def expected_description(*, title: str, current: str, bot: str, university: bool, parent: Chat | None = None) -> str:
    """What a chat's description should read, given its title and what it reads now.

    `university` is whether the chat is a university's main chat or under one
    (`main_chats`); the caller knows the whole table, this function does not.
    """
    if not university:
        return _without_retired_links(current)

    emoji = _leading_emoji(current) or DEFAULT_EMOJI
    lines = []
    main = _username(parent.public_link) if parent is not None else None
    if parent is not None and main:
        lines.append(f"Главный чат {_short_name(parent.title or '')}: {main}")
    lines.append(f"Все чаты и помощь с учёбой: @{bot}")

    tail = "\n" + "\n".join(lines)
    head = f"{emoji} Чат студентов и абитуриентов "
    # The main chat goes by its short name ("ČVUT", not "ČVUT | ЧВУТ"); a chat
    # under it by its whole title, which is what tells it apart.
    name = title if parent is not None else _short_name(title)
    room = max(0, DESCRIPTION_LIMIT - _utf16_len(head) - _utf16_len(tail))
    return _fit(head + _fit(name, room) + tail, DESCRIPTION_LIMIT)
