"""The record of what moderators did.

One function, called after an action succeeds. It exists as a separate module
rather than a method on some service because the actions have no service in
common: ``/ban`` calls the Bot API directly, the blacklist goes through its own
module, and the control plane comes in from outside the bot entirely. What they
share is the sentence they produce — *who did what to whom, where, and how it
was asked for* — so that is what is factored out.

Failures here are logged and swallowed. By the time this runs the ban has
already happened, and a bookkeeping error that surfaced as "что-то пошло не
так" would tell the admin the opposite of the truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.enums import ModerationEventAction, ModerationEventSource

logger = get_logger("moderation.audit")


async def record(
    db: AsyncSession,
    *,
    action: ModerationEventAction,
    source: ModerationEventSource,
    actor_id: int,
    target_user_id: int,
    chat_id: int | None = None,
    detail: str | None = None,
) -> None:
    """Write one line into the moderation record.

    ``detail`` carries whatever the action itself cannot: a mute's duration, the
    reason given for a proposal. It is free text and read by humans.
    """
    from app.db.models import ModerationEvent

    try:
        db.add(
            ModerationEvent(
                action=action,
                source=source,
                actor_id=actor_id,
                target_user_id=target_user_id,
                chat_id=chat_id,
                detail=detail,
            )
        )
        await db.commit()
    except Exception as err:
        await db.rollback()
        logger.error(
            "moderation_event_not_recorded",
            error=str(err),
            exc_info=True,
            action=action,
            actor_id=actor_id,
            target_user_id=target_user_id,
            chat_id=chat_id,
        )
        return

    logger.info(
        "moderation_event",
        action=action,
        source=source,
        actor_id=actor_id,
        target_user_id=target_user_id,
        chat_id=chat_id,
    )
