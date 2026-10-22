"""What t.me shows a stranger about a chat, for a chat the bot cannot ask.

A private group the bot is not in is closed to the Bot API: `getChat` wants a
member, and an invite link resolves only for whoever joins through it. Its
public page at t.me still shows the title, the photo and how many are in it,
which is all the catalogue lists. So an external chat known only by its invite
link is kept current from that page instead of from Telegram's API.

Nothing here raises for a network or page problem: a page that cannot be read
is a chat that keeps what it had.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp

from app.chats import avatars
from app.chats.avatars import JPEG_MAGIC, MAX_AVATAR_BYTES
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import ChatAvatar, ChatMemberSnapshot

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models import Chat

logger = get_logger("chats.previews")

TIMEOUT = aiohttp.ClientTimeout(total=15)

# An invite link as people paste it: "t.me/+hash", "https://t.me/+hash" or the
# older "t.me/joinchat/hash". The hash is Telegram's, letters, digits, - and _.
_INVITE = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)(?P<hash>[\w-]{8,64})/?$")
_TITLE = re.compile(r'<div class="tgme_page_title"[^>]*>\s*<span[^>]*>(.*?)</span>', re.S)
_EXTRA = re.compile(r'<div class="tgme_page_extra">(.*?)</div>', re.S)
_PHOTO = re.compile(r'<img class="tgme_page_photo_image" src="(https://[^"]+)"')


def invite_hash_of(link: str) -> str | None:
    """The hash of a pasted invite link, or None when it is not one."""
    match = _INVITE.match(link.strip())
    return match["hash"] if match else None


def invite_link(invite_hash: str) -> str:
    return f"https://t.me/+{invite_hash}"


@dataclass(frozen=True)
class Preview:
    title: str
    # A group's "members", a channel's "subscribers"; None when the page gave no count.
    member_count: int | None
    is_channel: bool
    photo_url: str | None


def parse(page: str) -> Preview | None:
    """Read the page; None when it names no chat (a dead or wrong link)."""
    title = _TITLE.search(page)
    if title is None:
        return None
    extra_match = _EXTRA.search(page)
    extra = html.unescape(extra_match[1]).strip() if extra_match else ""
    # "1 648 members, 578 online" or "717 subscribers": the first figure, its spaces dropped.
    count = re.match(r"([\d\s]+)\s+(members|subscribers)", extra)
    photo = _PHOTO.search(page)
    return Preview(
        title=html.unescape(title[1]).strip(),
        member_count=int(re.sub(r"\D", "", count[1])) if count else None,
        is_channel=count is not None and count[2] == "subscribers",
        photo_url=html.unescape(photo[1]) if photo else None,
    )


async def fetch(http: aiohttp.ClientSession, link: str) -> Preview | None:
    """The page behind a link, read; None when it cannot be had or names no chat."""
    try:
        async with http.get(link, timeout=TIMEOUT) as response:
            if response.status != 200:
                logger.warning("preview_fetch_failed", status=response.status)
                return None
            page = await response.text()
    except (aiohttp.ClientError, TimeoutError) as err:
        logger.warning("preview_fetch_failed", error_type=type(err).__name__)
        return None
    return parse(page)


@dataclass(frozen=True)
class Photo:
    # Made from the picture itself, so it changes exactly when the picture does,
    # as Telegram's own file_unique_id does for the chats the bot can ask.
    unique_id: str
    content: bytes


async def fetch_photo(http: aiohttp.ClientSession, url: str) -> Photo | None:
    """The preview's picture, or None when it is not a small JPEG."""
    try:
        async with http.get(url, timeout=TIMEOUT) as response:
            if response.status != 200:
                logger.warning("preview_photo_failed", status=response.status)
                return None
            data = await response.content.read(MAX_AVATAR_BYTES)
    except (aiohttp.ClientError, TimeoutError) as err:
        logger.warning("preview_photo_failed", error_type=type(err).__name__)
        return None
    # Served to strangers under our own address, so the same check as the bot's download.
    if not data.startswith(JPEG_MAGIC) or len(data) >= MAX_AVATAR_BYTES:
        logger.warning("preview_photo_rejected", size=len(data))
        return None
    return Photo(unique_id="tme-" + hashlib.sha256(data).hexdigest()[:40], content=data)


async def sync(session: AsyncSession, http: aiohttp.ClientSession, chat: Chat) -> Preview | None:
    """Bring a preview-only chat in line with its page. Caller commits.

    Its title, a member count and its picture, as the snapshot loop does over
    the Bot API for the others. None, with nothing changed, when the page could
    not be read or names no chat any more.
    """
    if chat.public_link is None:
        return None
    preview = await fetch(http, chat.public_link)
    if preview is None:
        return None
    if preview.title != chat.title:
        chat.title = preview.title
    if preview.member_count is not None:
        session.add(ChatMemberSnapshot(chat_id=chat.id, member_count=preview.member_count))
    stored = await session.get(ChatAvatar, chat.id)
    if preview.photo_url is None:
        if stored is not None:
            await session.delete(stored)
    elif (photo := await fetch_photo(http, preview.photo_url)) is not None and (
        stored is None or stored.unique_id != photo.unique_id
    ):
        await avatars.store(session, chat_id=chat.id, unique_id=photo.unique_id, content=photo.content)
        if stored is not None:
            session.expire(stored)
    chat.last_synced_at = utc_now()
    return preview
