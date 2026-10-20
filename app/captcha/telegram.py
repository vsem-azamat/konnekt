"""Calls to Telegram that may meet flood control on the way."""

import asyncio
from collections.abc import Awaitable, Callable

from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from app.core.logging import get_logger

logger = get_logger("captcha.telegram")

_ATTEMPTS = 3
# Longer than this and the request is better left to the admins than waited on.
_LONGEST_WAIT = 60


async def with_retry(call: Callable[[], Awaitable[object]]) -> bool:
    """Make the call, waiting out short flood control; False if it never went through.

    Failures are logged, not raised: a request somebody else already closed is
    the common case, and it is no reason to stop working through the rest.
    """
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            await call()
            return True
        except TelegramRetryAfter as err:
            if attempt == _ATTEMPTS or err.retry_after > _LONGEST_WAIT:
                logger.warning("captcha_call_flood_control", retry_after=err.retry_after)
                return False
            await asyncio.sleep(err.retry_after)
        except TelegramAPIError as err:
            logger.info("captcha_call_refused", error=str(err))
            return False
    return False
