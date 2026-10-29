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


@pytest.mark.usefixtures("classmate")
async def test_someone_whose_messages_were_spam_is_no_classmate(session: AsyncSession) -> None:
    session.add(User(id=4, username="spam_boss"))
    session.add(Message(chat_id=CHAT, user_id=4, message_id=12, message="Нужны люди", spam=True))
    await session.commit()

    assert await _record(session, "пишите @spam_boss") == {"@spam_boss"}


@pytest.mark.usefixtures("classmate")
async def test_a_blocked_user_is_no_classmate(session: AsyncSession) -> None:
    session.add(User(id=4, username="banned_one", blocked=True))
    session.add(Message(chat_id=CHAT, user_id=4, message_id=12, message="привет"))
    await session.commit()

    assert await _record(session, "пишите @banned_one") == {"@banned_one"}


@pytest.mark.usefixtures("classmate")
async def test_an_ad_answered_keeps_its_answer_when_the_named_account_writes_later(session: AsyncSession) -> None:
    (ping,) = await record_ad_signals(
        session, chat_id=CHAT, user_id=SENDER, message_id=100, text="Кастинг, пишите @puppet_b"
    )
    ping.verdict = "ad"
    session.add(User(id=5, username="puppet_b"))
    session.add(Message(chat_id=CHAT, user_id=5, message_id=13, message="hi"))
    await session.commit()

    rows = await record_ad_signals(
        session, chat_id=CHAT, user_id=SENDER, message_id=100, text="Кастинг, пишите  @puppet_b", replace=True
    )

    assert [(row.matches, row.verdict) for row in rows] == [(["@puppet_b"], "ad")]


async def test_an_invite_link_in_the_catalog_clears_only_that_invite(session: AsyncSession) -> None:
    session.add(
        Chat(id=OTHER_CHAT, title="FEL", resource_status=Chat.STATUS_APPROVED, public_link="https://t.me/+AbCdEf123")
    )
    await session.commit()

    assert await _record(session, "https://t.me/+AbCdEf123 и https://t.me/+Other999") == {"t.me/+other999"}


async def test_a_link_to_a_discovered_chat_is_still_flagged(session: AsyncSession) -> None:
    session.add(
        Chat(
            id=OTHER_CHAT, title="Работа", resource_status=Chat.STATUS_DISCOVERED, public_link="https://t.me/rabota_cz"
        )
    )
    await session.commit()

    assert await _record(session, "все подробности https://t.me/rabota_cz") == {"t.me/rabota_cz"}


@pytest.mark.usefixtures("classmate")
async def test_an_ad_edited_out_and_back_in_is_flagged_again(session: AsyncSession) -> None:
    await record_ad_signals(session, chat_id=CHAT, user_id=SENDER, message_id=100, text="Кастинг, пишите @puppet_b")
    session.add(User(id=5, username="puppet_b"))
    session.add(Message(chat_id=CHAT, user_id=5, message_id=101, message="hi"))
    await session.commit()
    await record_ad_signals(session, chat_id=CHAT, user_id=SENDER, message_id=100, text="Кастинг", replace=True)

    rows = await record_ad_signals(
        session, chat_id=CHAT, user_id=SENDER, message_id=100, text="Кастинг, пишите @puppet_b", replace=True
    )

    assert [row.matches for row in rows] == [["@puppet_b"]]
