"""Membership changes in managed chats.

Only reached for approved chats: the approval gate runs on `dp.update` and stops
membership updates for anything still awaiting a decision, so nothing here needs
to re-check that.
"""

import datetime
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import LEFT, MEMBER, ChatMemberUpdatedFilter
from aiogram.types import ChatJoinRequest, ChatMemberUpdated, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import Chat, JoinCheck, User
from app.presentation.telegram.utils.filters import ChatTypeFilter
from app.presentation.telegram.utils.other import sleep_and_delete

logger = get_logger("handler.events")
router = Router()

JOIN_CHECK_MINUTES = 15


@router.chat_member(ChatTypeFilter(["group", "supergroup"]), ChatMemberUpdatedFilter(member_status_changed=MEMBER))
async def user_joined(event: ChatMemberUpdated, bot: Bot, db: AsyncSession) -> None:
    """Greet a new member if the chat is configured to.

    A plain message rather than an ephemeral one. Bot API 10.2 says ephemeral
    delivery "is not guaranteed... especially if they are offline", which is
    acceptable for a reply to a command and useless for a greeting the new
    arrival may never see. It is cleaned up after `time_delete` seconds instead.
    """
    joined = event.new_chat_member.user
    logger.info("user_joined", chat_id=event.chat.id, user_id=joined.id)

    chat = await db.scalar(select(Chat).where(Chat.id == event.chat.id))
    if chat is None or not chat.is_welcome_enabled or not chat.welcome_message:
        return

    try:
        message = await bot.send_message(
            chat_id=event.chat.id,
            text=f"{joined.mention_html()}, {chat.welcome_message}",
        )
    except Exception as err:
        # A greeting Telegram refuses is the chat's problem, not the join's.
        logger.warning("welcome_not_sent", chat_id=event.chat.id, error=str(err))
        return

    if chat.time_delete:
        sleep_and_delete(message, chat.time_delete)


@router.chat_member(ChatTypeFilter(["group", "supergroup"]), ChatMemberUpdatedFilter(member_status_changed=LEFT))
async def user_left(event: ChatMemberUpdated) -> None:
    logger.info("user_left", chat_id=event.chat.id, user_id=event.new_chat_member.user.id)


@router.message(ChatTypeFilter(["group", "supergroup"]), F.new_chat_members | F.left_chat_member)
async def remove_membership_notice(message: Message, db: AsyncSession) -> None:
    """Take Telegram's own "joined"/"left" notice out of the chat.

    In a chat that sees a message a week these are most of what is in it, and a
    wall of them reads as a dead room. The membership itself is not hidden —
    the member list is still the member list, the bot still records the event,
    and a welcome message, if the chat has one, still gets posted.

    Only the notice Telegram generated is removed, never anything a person
    wrote: this handler is reached solely for messages that *are* the notice.
    """
    chat = await db.scalar(select(Chat).where(Chat.id == message.chat.id))
    if chat is None or not chat.is_service_cleanup_enabled:
        return

    try:
        await message.delete()
    except TelegramBadRequest as err:
        # Missing the right, or the notice is older than Telegram lets a bot
        # delete. Neither is worth an alert; the chat is merely noisier.
        logger.debug("service_notice_not_removed", chat_id=message.chat.id, error=str(err))


@router.chat_join_request()
async def join_requested(event: ChatJoinRequest, bot: Bot, db: AsyncSession) -> None:
    """Answer a request to join: turn blacklisted people away, check the rest.

    A chat that requires approval never produces the join event the blacklist
    middleware watches, so without this a blacklisted person is only stopped
    once an operator has already let them in.

    Nobody is approved outright. With the check configured the applicant is
    shown a Mini App and approves themselves by passing it; otherwise `queue`
    hands the decision to the humans. A guard bot must answer either way —
    leaving the query unanswered hangs the request.
    """
    applicant = event.from_user
    chat = await db.scalar(select(Chat).where(Chat.id == event.chat.id))
    if chat is None:
        logger.info("join_request_ignored_unknown_chat", chat_id=event.chat.id)
        return

    blocked = await db.scalar(select(User.blocked).where(User.id == applicant.id))

    if blocked:
        logger.info("join_request_declined", chat_id=event.chat.id, user_id=applicant.id)
        if event.query_id:
            await bot.answer_chat_join_request_query(chat_join_request_query_id=event.query_id, result="decline")
        else:
            await bot.decline_chat_join_request(chat_id=event.chat.id, user_id=applicant.id)
        return

    if not event.query_id:
        # Not this chat's guard bot: approving is the operator's call to make.
        logger.info("join_request_left_to_admins", chat_id=event.chat.id, user_id=applicant.id)
        return

    if await _offer_check(event, bot, db, chat):
        return

    logger.info("join_request_queued", chat_id=event.chat.id, user_id=applicant.id)
    await bot.answer_chat_join_request_query(chat_join_request_query_id=event.query_id, result="queue")


async def _offer_check(event: ChatJoinRequest, bot: Bot, db: AsyncSession, chat: Chat) -> bool:
    """Show the Mini App check. False when this chat has none to show."""
    base_url = settings.webapi.public_url
    if not chat.is_captcha_enabled or not base_url:
        return False

    query_id = event.query_id
    if query_id is None:  # pragma: no cover - caller checked
        return False

    db.add(
        JoinCheck(
            query_id=query_id,
            chat_id=event.chat.id,
            user_id=event.from_user.id,
            expires_at=utc_now() + datetime.timedelta(minutes=JOIN_CHECK_MINUTES),
        )
    )
    await db.commit()

    # The query id travels in the URL, but holding it proves nothing: the
    # endpoint checks the caller's signed identity against the stored applicant.
    await bot.send_chat_join_request_web_app(
        chat_join_request_query_id=query_id,
        web_app_url=f"{base_url.rstrip('/')}/join?q={quote(query_id)}",
    )
    logger.info("join_check_offered", chat_id=event.chat.id, user_id=event.from_user.id)
    return True
