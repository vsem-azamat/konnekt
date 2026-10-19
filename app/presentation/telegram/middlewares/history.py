from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware, types
from aiogram.types import TelegramObject

from app.core.logging import get_logger
from app.moderation import ad_detector_service, history_service, spam_service
from app.presentation.telegram.utils import other

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("middleware.history")


class HistoryMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        db: AsyncSession = data["db"]
        if isinstance(event, types.Update) and isinstance(event.message, types.Message):
            message = event.message
            user = message.from_user

            if isinstance(user, types.User):
                try:
                    await history_service.merge_user(db, user)
                except Exception as err:
                    logger.error("merge_user_failed", error=str(err))

            # Approval is only ever decided for groups. A private chat with the
            # bot is not a chat it moderates, so it is neither recorded nor
            # screened: a spam warning there would address absent moderators.
            if message.chat.type not in ("group", "supergroup"):
                return await handler(event, data)

            try:
                await history_service.save_message(db, message)
            except Exception as err:
                logger.error("save_message_failed", error=str(err))

            if not data.get("chat_is_approved", False):
                return await handler(event, data)

            if isinstance(user, types.User):
                try:
                    await ad_detector_service.record_ad_signals(
                        db,
                        chat_id=message.chat.id,
                        user_id=user.id,
                        message_id=message.message_id,
                        text=message.text or message.caption,
                    )
                except Exception as err:
                    logger.error("ad_detector_failed", error=str(err))

            if await spam_service.detect_spam(db, message):
                # Addressed to whoever is in the room, not to the author: the
                # bot only suspects, and the suspicion is that a first-ever
                # message matches something a moderator already called spam.
                answer = await event.message.answer(
                    "⚠️ Похоже на спам: первое сообщение участника совпадает с ранее помеченным. Модераторы, проверьте."
                )
                other.sleep_and_delete(answer, 15)

        return await handler(event, data)
