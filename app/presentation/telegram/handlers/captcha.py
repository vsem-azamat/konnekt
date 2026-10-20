"""Taps on the join captcha and on a wave alert.

Both are answers to messages this bot sent, which is why they live on the
moderator dispatcher: Telegram returns a press to the identity that sent it.
"""

from aiogram import Bot, Router, types
from sqlalchemy.ext.asyncio import AsyncSession

from app.captcha import service, waves
from app.captcha.challenge import CaptchaPick
from app.captcha.waves import WaveDecision
from app.core.config import settings

router = Router()

_REPLIES = {
    service.Outcome.PASSED: "Готово!",
    service.Outcome.RETRY: "Не то, попробуй ещё раз",
    service.Outcome.FAILED: "Заявка отклонена",
    service.Outcome.CLOSED: "Эта проверка уже закрыта",
    service.Outcome.GONE: "Заявку уже рассмотрели",
}


@router.callback_query(CaptchaPick.filter())
async def captcha_pick(callback: types.CallbackQuery, callback_data: CaptchaPick, bot: Bot, db: AsyncSession) -> None:
    outcome = await service.answer(
        bot, db, challenge_id=callback_data.challenge_id, user_id=callback.from_user.id, pick=callback_data.pick
    )
    await callback.answer(_REPLIES[outcome])


@router.callback_query(WaveDecision.filter())
async def wave_decision(callback: types.CallbackQuery, callback_data: WaveDecision, bot: Bot, db: AsyncSession) -> None:
    if callback.from_user.id not in settings.admin.super_admins:
        await callback.answer("Только для супер-админов", show_alert=True)
        return

    # Answered first: declining a wave of hundreds takes minutes, and Telegram
    # stops waiting for an answer long before that. The outcome replaces the
    # alert's text once it is done.
    await callback.answer("Принято")
    await waves.decide(
        bot,
        db,
        wave_id=callback_data.wave_id,
        action=callback_data.action,
        admin_id=callback.from_user.id,
        admin_name=callback.from_user.full_name,
    )
