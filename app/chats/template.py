"""The agreed description of a project chat.

Approved by the owner on 2026-10-19 (#155). A university chat gets the shared
description below: a university's main chat or a chat under one. A dormitory
chat carries its university's institution too, so when several top chats share
one, the main chat is the one with chats under it (see `main_chats`). Any other project
chat keeps its own words and only loses the links that no longer lead anywhere
useful: the network channel is not run, contacts go through the bot, and the
bots Konnekt moved away from only point onwards (#245).

A few chats keep their owner's words even where the shared text would apply
(`OWN_WORDS`): their description was written by whoever runs the chat, with
links of their own. Only the retired links go, and the bot line is added at
the end. The owner's words are never cut to make room: a text that cannot take
the bot line stays as it is, and the audit says so.

Titles and the bot's rules pin come later (#202). Until the rules are pinned,
the description does not promise them.
"""

from __future__ import annotations

import re
import unicodedata

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
_RETIRED_IN_A_LIST = re.compile(r"(?:https?://)?" + _RETIRED.pattern + r"(?:\s*,\s*)?", re.IGNORECASE)
_ANY_LINK = re.compile(r"@\w|t\.me/|https?://", re.IGNORECASE)
BOT_LINE = "Все чаты и помощь с учёбой: @{bot}"

# Chats whose description stays in their owner's words, chosen by the owner on
# 2026-10-20: IT Чехия, Matfyz, VUT. A one-off decision, so a constant and not
# a column.
OWN_WORDS = frozenset({-1001541760895, -1001283110780, -1001198485843})


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


def _without_retired_handles(line: str) -> str | None:
    """The line with only its retired links cut, or None when nothing of the owner's is left."""
    kept = _RETIRED_IN_A_LIST.sub("", line).rstrip(" ,")
    return kept if _ANY_LINK.search(kept) else None


def _in_own_words(current: str, bot: str) -> str:
    """The owner's text without retired links, with the bot line at the end.

    When the owner's text and the bot line do not fit together, the text is left
    exactly as it was (`own_words_fit` tells the audit).
    """
    bot_line = BOT_LINE.format(bot=bot)
    lines = []
    for line in current.splitlines():
        if not _RETIRED.search(line):
            lines.append(line)
        elif (kept := _without_retired_handles(line)) is not None:
            lines.append(kept)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if bot_line in text:
        return text
    full = f"{text}\n\n{bot_line}" if text else bot_line
    return full if _utf16_len(full) <= DESCRIPTION_LIMIT else current


def own_words_fit(current: str, bot: str) -> bool:
    """Whether a chat in its owner's words can take the bot line."""
    return BOT_LINE.format(bot=bot) in _in_own_words(current, bot)


def expected_description(
    *, title: str, current: str, bot: str, university: bool, parent: Chat | None = None, own_words: bool = False
) -> str:
    """What a chat's description should read, given its title and what it reads now.

    `university` is whether the chat is a university's main chat or under one
    (`main_chats`); the caller knows the whole table, this function does not.
    `own_words` is whether the chat is one of `OWN_WORDS`.
    """
    if own_words:
        return _in_own_words(current, bot)
    if not university:
        return _without_retired_links(current)

    emoji = _leading_emoji(current) or DEFAULT_EMOJI
    lines = []
    # Somebody else's main chat is listed, never recommended: our own
    # description sending people there would vouch for a room we do not run.
    ours = parent is not None and parent.resource_status != Chat.STATUS_EXTERNAL
    main = _username(parent.public_link) if parent is not None and ours else None
    if parent is not None and main:
        lines.append(f"Главный чат {_short_name(parent.title or '')}: {main}")
    lines.append(BOT_LINE.format(bot=bot))

    tail = "\n" + "\n".join(lines)
    head = f"{emoji} Чат студентов и абитуриентов "
    # The main chat goes by its short name ("ČVUT", not "ČVUT | ЧВУТ"); a chat
    # under it by its whole title, which is what tells it apart.
    name = title if parent is not None else _short_name(title)
    room = max(0, DESCRIPTION_LIMIT - _utf16_len(head) - _utf16_len(tail))
    return _fit(head + _fit(name, room) + tail, DESCRIPTION_LIMIT)
