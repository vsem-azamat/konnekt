"""Calls to Telegram that may meet flood control on the way, and what their refusals mean."""

import asyncio
from collections.abc import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("captcha.telegram")

_ATTEMPTS = 3
# Longer than this and the request is better left to the admins than waited on.
_LONGEST_WAIT = 60


async def with_retry[T](call: Callable[[], Awaitable[T]]) -> T:
    """Make the call, waiting out short flood control; raises what Telegram said otherwise."""
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            return await call()
        except TelegramRetryAfter as err:
            if attempt == _ATTEMPTS or err.retry_after > _LONGEST_WAIT:
                raise
            await asyncio.sleep(err.retry_after)
    raise AssertionError("unreachable")  # pragma: no cover


def request_gone(err: TelegramAPIError) -> bool:
    """Telegram's word for "there is no such request": somebody already settled it."""
    return "HIDE_REQUESTER_MISSING" in err.message


def lacks_rights(err: TelegramAPIError) -> bool:
    """A refusal the chat's admins can fix by giving the bot its rights back."""
    return isinstance(err, TelegramForbiddenError) or any(
        sign in err.message for sign in ("CHAT_ADMIN_REQUIRED", "not enough rights", "USER_NOT_PARTICIPANT")
    )


def already_member(err: TelegramAPIError) -> bool:
    return "USER_ALREADY_PARTICIPANT" in err.message


async def report(bot: Bot, text: str) -> None:
    """One line to the report chat, for what the admins should know about."""
    try:
        await bot.send_message(chat_id=settings.admin.default_report_chat_id, text=text)
    except TelegramAPIError as err:
        logger.warning("captcha_report_not_sent", error=str(err), error_type=type(err).__name__)
