"""Persist ad-detector hits.

Thin glue: pure detector + DB insert. Lives in moderation/ so it stays
next to the regex module instead of bleeding into the middleware.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Chat, Message, SpamPing, User
from app.moderation.ad_detector import AdSignal, extract_ad_signals

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = get_logger("moderation.ad_detector")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _configured() -> list[str]:
    """Handles never flagged by configuration: the whitelist and the ads bot."""
    ours = list(settings.moderation.ad_detector_whitelist)
    if settings.ads_bot.contact_username:
        ours.append(settings.ads_bot.contact_username)
    return ours


async def _catalog(db: AsyncSession) -> list[str]:
    """The links of the chats our catalog lists.

    Only listed ones: a discovered chat is someone else's, and a link to it is
    exactly what an ad carries. A link is a username or an invite; either way
    the detector's whitelist reduces it to what a link or mention of it matches.
    """
    links = await db.scalars(select(Chat.public_link).where(Chat.resource_status.in_(Chat.LISTABLE_STATUSES)))
    return [link for link in links if link]


async def _without_classmates(
    db: AsyncSession, signals: list[AdSignal], *, chat_id: int, user_id: int, flagged: set[str]
) -> list[AdSignal]:
    """Drop mentions of people, other than the sender, who have written in this chat.

    Students tag each other; an ad sends readers to someone they have not
    met. The sender is not exempt: a message naming its own author is how a
    stranger advertises themselves. Nor is anyone a moderator has turned
    away: their spam and their block do not make them a classmate.

    A mention this message was already flagged for stays flagged: someone
    writing in the chat later does not take back an ad, nor its answer.
    """
    handles = [
        sig.canonical.removeprefix("@") for sig in signals if sig.kind == "mention" and sig.canonical not in flagged
    ]
    if not handles:
        return signals
    classmates = set(
        await db.scalars(
            select(func.lower(User.username)).where(
                func.lower(User.username).in_(handles),
                User.id != user_id,
                User.blocked.is_(False),
                select(Message.id)
                .where(Message.chat_id == chat_id, Message.user_id == User.id, Message.spam.is_(False))
                .exists(),
            )
        )
    )
    return [sig for sig in signals if sig.kind != "mention" or sig.canonical.removeprefix("@") not in classmates]


async def record_ad_signals(
    db: AsyncSession,
    *,
    chat_id: int,
    user_id: int,
    message_id: int,
    text: str | None,
    replace: bool = False,
) -> list[SpamPing]:
    """Detect ad signals and persist one SpamPing row per kind hit.

    Returns the persisted rows (empty list if disabled or no hits).
    Commits: nothing after the history middleware commits a plain message, so
    rows left for "the caller" were rolled back with the update.
    """
    if not settings.moderation.ad_detector_enabled:
        return []
    # An edit: what the message holds now replaces what it held, so a message
    # edited three times is still one message with one ad. A hit whose links
    # did not change is the same hit and keeps its answer; other links are a
    # new question.
    earlier: dict[str, SpamPing] = {}
    if replace:
        earlier = {
            ping.kind: ping
            for ping in await db.scalars(
                select(SpamPing).where(SpamPing.chat_id == chat_id, SpamPing.message_id == message_id)
            )
        }

    signals = extract_ad_signals(text, whitelist=_configured()) if text else []
    if signals:
        signals = extract_ad_signals(text, whitelist=_configured() + await _catalog(db))
    flagged = {match for ping in earlier.values() for match in ping.matches}
    signals = await _without_classmates(db, signals, chat_id=chat_id, user_id=user_id, flagged=flagged)
    snippet = _truncate(text, settings.moderation.ad_detector_snippet_chars) if text else None
    by_kind: dict[str, list[str]] = {}
    for sig in signals:
        by_kind.setdefault(sig.kind, []).append(sig.canonical)

    if replace:
        for kind, ping in earlier.items():
            if kind not in by_kind:
                await db.delete(ping)

    rows: list[SpamPing] = []
    for kind, matches in by_kind.items():
        row = earlier.get(kind)
        if row is None:
            row = SpamPing(
                chat_id=chat_id, user_id=user_id, message_id=message_id, kind=kind, matches=matches, snippet=snippet
            )
            db.add(row)
        else:
            if row.matches != matches:
                row.matches = matches
                row.verdict = None
                row.reviewed_at = None
                row.reviewed_by = None
            row.snippet = snippet
        rows.append(row)
    if rows or earlier:
        await db.commit()
    if not rows:
        return []

    logger.info(
        "ad_signals_detected",
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        kinds=list(by_kind),
        match_count=len(signals),
    )
    return rows
