"""What the ad detector records, given who is in the chat.

The cases are the false positives found on prod (2026-10-19..29): students
tagging a classmate, links to a message in a chat of our own catalog, and our
own posts naming the ads bot. The ads it caught there must still be caught.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from app.core.config import settings
from app.db.models import Chat, Message, User
from app.moderation.ad_detector_service import record_ad_signals

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

CHAT = -100_500
OTHER_CHAT = -100_501
SENDER = 1
CLASSMATE = 2


async def _record(session: AsyncSession, text: str, *, user_id: int = SENDER, message_id: int = 100) -> set[str]:
    rows = await record_ad_signals(session, chat_id=CHAT, user_id=user_id, message_id=message_id, text=text)
    return {match for row in rows for match in row.matches}


@pytest.fixture
async def classmate(session: AsyncSession) -> None:
    session.add_all([User(id=SENDER, username="Sender_1"), User(id=CLASSMATE, username="Daniyar_Sci")])
    session.add(Message(chat_id=CHAT, user_id=CLASSMATE, message_id=10, message="привет"))
    await session.commit()


@pytest.mark.usefixtures("classmate")
async def test_tagging_someone_who_wrote_in_the_chat_is_not_an_ad(session: AsyncSession) -> None:
    assert await _record(session, "@daniyar_sci пошли") == set()


@pytest.mark.usefixtures("classmate")
async def test_a_stranger_next_to_a_classmate_is_still_flagged(session: AsyncSession) -> None:
    assert await _record(session, "@Daniyar_Sci глянь, все подробности @RitiK160") == {"@ritik160"}


@pytest.mark.usefixtures("classmate")
async def test_someone_who_wrote_only_in_another_chat_is_still_flagged(session: AsyncSession) -> None:
    session.add(User(id=3, username="elsewhere_guy"))
    session.add(Message(chat_id=OTHER_CHAT, user_id=3, message_id=11, message="hi"))
    await session.commit()

    assert await _record(session, "пишите @elsewhere_guy") == {"@elsewhere_guy"}


@pytest.mark.usefixtures("classmate")
async def test_advertising_your_own_handle_is_still_flagged(session: AsyncSession) -> None:
    # The history middleware has stored this very message before the detector runs.
    session.add(Message(chat_id=CHAT, user_id=SENDER, message_id=100, message="Кастинг, пишите @sender_1"))
    await session.commit()

    assert await _record(session, "Кастинг, пишите @sender_1") == {"@sender_1"}


async def test_a_link_to_a_message_in_a_catalog_chat_is_not_an_ad(session: AsyncSession) -> None:
    session.add(
        Chat(id=OTHER_CHAT, title="VŠE", resource_status=Chat.STATUS_APPROVED, public_link="https://t.me/vse_chat")
    )
    await session.commit()

    assert await _record(session, "о чём вы? https://t.me/vse_chat/86773 и @VSE_chat") == set()


async def test_a_link_to_a_chat_outside_the_catalog_is_still_flagged(session: AsyncSession) -> None:
    session.add(
        Chat(id=OTHER_CHAT, title="VŠE", resource_status=Chat.STATUS_APPROVED, public_link="https://t.me/vse_chat")
    )
    await session.commit()

    assert await _record(session, "ПЕРЕХОДИТЕ http://t.me/shitgobot?start=ref_1") == {"t.me/shitgobot"}


async def test_the_ads_bot_is_not_an_ad(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.ads_bot, "contact", "@konnekt_ads_bot")

    assert await _record(session, "🤖 Связь с админами по любому вопросу: @konnekt_ads_bot") == set()
