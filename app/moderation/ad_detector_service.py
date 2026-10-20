"""Persist ad-detector hits.

Thin glue: pure detector + DB insert. Lives in moderation/ so it stays
next to the regex module instead of bleeding into the middleware.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import SpamPing
from app.moderation.ad_detector import extract_ad_signals

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = get_logger("moderation.ad_detector")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


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
    signals = extract_ad_signals(text, whitelist=settings.moderation.ad_detector_whitelist) if text else []
    snippet = _truncate(text, settings.moderation.ad_detector_snippet_chars) if text else None
    by_kind: dict[str, list[str]] = {}
    for sig in signals:
        by_kind.setdefault(sig.kind, []).append(sig.canonical)

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
