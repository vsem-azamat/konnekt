"""Taps on the join captcha and on a wave alert, and the card's way into the captcha.

Both are answers to messages this bot sent, which is why they live on the
moderator dispatcher: Telegram returns a press to the identity that sent it.
Each handler answers the press itself, so the dispatcher's automatic answer is
turned off for them; a second answer to one press is an error.
"""

from aiogram import Bot, F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession

from app.captcha import challenge, in_chat, service, waves
from app.captcha.challenge import CaptchaPick
from app.captcha.waves import WaveDecision
from app.core.config import settings
from app.core.time import utc_now
from app.db.models import JoinCaptcha

router = Router()

_ANSWERS_ITSELF = {"callback_answer": {"disabled": True}}

_REPLIES = {
    service.Outcome.PASSED: "Готово!",
    service.Outcome.RETRY: "Не то, попробуй ещё раз",
    service.Outcome.FAILED: "Заявка отклонена",
    service.Outcome.CLOSED: "Эта проверка уже закрыта",
    service.Outcome.GONE: "Заявку рассмотрят админы чата",
}


@router.message(F.chat.type == "private", CommandStart(deep_link=True, magic=F.args == challenge.START_PAYLOAD))
async def captcha_start(message: types.Message, bot: Bot, db: AsyncSession) -> None:
    """The button on a card in the chat: the question, for each chat this person waits in.

    Nothing to ask (passed already, out of time, or somebody else's card),
    and it is a plain /start.
    """
    if message.from_user is None or not await in_chat.ask(bot, db, message.from_user.id, utc_now()):
        raise SkipHandler


@router.callback_query(CaptchaPick.filter(), flags=_ANSWERS_ITSELF)
async def captcha_pick(callback: types.CallbackQuery, callback_data: CaptchaPick, bot: Bot, db: AsyncSession) -> None:
    outcome = await service.answer(
        bot, db, challenge_id=callback_data.challenge_id, user_id=callback.from_user.id, pick=callback_data.pick
    )
    if outcome is service.Outcome.RETRY and (row := await db.get(JoinCaptcha, callback_data.challenge_id)):
        # Not an alert: it goes by itself and the board stays usable under it.
        await callback.answer(challenge.retry_hint(row.answer, row.attempts_left))
        return
    await callback.answer(_REPLIES[outcome])


@router.callback_query(WaveDecision.filter(), flags=_ANSWERS_ITSELF)
async def wave_decision(callback: types.CallbackQuery, callback_data: WaveDecision, bot: Bot, db: AsyncSession) -> None:
    if callback.from_user.id not in settings.admin.super_admins:
        await callback.answer("Только для супер-админов", show_alert=True)
        return

    decided = await waves.decision_of(db, callback_data.wave_id)
    if decided is not None and decided != callback_data.action:
        await callback.answer("По этой волне уже решили иначе", show_alert=True)
        return

    # Answered before the work: declining a wave of hundreds takes minutes, and
    # Telegram stops waiting for an answer long before that. The outcome
    # replaces the alert's text once it is done.
    await callback.answer("Принято")
    await waves.decide(
        bot,
        db,
        wave_id=callback_data.wave_id,
        action=callback_data.action,
        admin_id=callback.from_user.id,
        admin_name=callback.from_user.full_name,
    )
