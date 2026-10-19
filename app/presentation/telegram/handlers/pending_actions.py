"""Confirm or drop destructive actions proposed by an external runtime.

This router belongs to the moderator dispatcher because that is the identity
that sent the message — Telegram hands a button press back to the sending bot,
and a proposal rendered by any other identity would show buttons that do
nothing. See the callback-ownership invariant in `docs/invariants.md`.
"""

from aiogram import Bot, Router, types
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ProtectedUserError
from app.core.logging import get_logger
from app.moderation.pending_actions import PendingActionDecision

logger = get_logger("handler.pending_actions")

pending_actions_router = Router()


@pending_actions_router.callback_query(PendingActionDecision.filter())
async def handle_pending_action(
    callback: types.CallbackQuery,
    callback_data: PendingActionDecision,
    bot: Bot,
    db: AsyncSession,
) -> None:
    if not callback.from_user:
        await callback.answer("Ошибка")
        return

    if callback.from_user.id not in settings.admin.super_admins:
        await callback.answer("Только для супер-админов", show_alert=True)
        return

    from app.moderation.pending_actions import PendingActionService

    service = PendingActionService(bot, db)
    confirming = bool(callback_data.confirm)

    try:
        resolved = (
            await service.confirm(callback_data.pending_id, admin_id=callback.from_user.id)
            if confirming
            else await service.reject(callback_data.pending_id, admin_id=callback.from_user.id)
        )
    except ProtectedUserError:
        note = "Не выполнено: главного администратора забанить нельзя."
        await callback.answer(note, show_alert=True)
        await _strip_keyboard(callback, note)
        return
    except Exception:
        # Recorded as failed by the service; the admin must see it too, or
        # the buttons stay and the press looks like it went nowhere.
        logger.exception("pending_action_press_failed", pending_id=callback_data.pending_id)
        note = "Не выполнено: Telegram отказал. Запрос закрыт, ничего не изменилось."
        await callback.answer(note, show_alert=True)
        await _strip_keyboard(callback, note)
        return

    if resolved is None:
        # Already pressed, already gone, or its deadline passed while it sat here.
        await callback.answer("Запрос уже обработан или истёк")
        await _strip_keyboard(callback, "Запрос уже неактуален.")
        return

    verdict = "Подтверждено и выполнено." if confirming else "Отклонено. Ничего не выполнено."
    await callback.answer(verdict)
    await _strip_keyboard(callback, verdict)


async def _strip_keyboard(callback: types.CallbackQuery, note: str) -> None:
    """Leave the outcome in place of the buttons so the record stays readable."""
    message = callback.message
    if not isinstance(message, types.Message) or not message.text:
        return
    try:
        # html_text, not text: the proposal was rendered with its reason escaped,
        # and the plain text would send that reason back as live markup.
        await message.edit_text(f"{message.html_text}\n\n<b>{note}</b>", reply_markup=None)
    except Exception:
        logger.warning("pending_action_edit_failed", message_id=message.message_id)
