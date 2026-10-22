"""The bits of notification that are pure logic.

Sending itself needs a bot token and Telegram; what can be tested here is
everything that decides *what* gets sent — and that is where the bugs are,
because the bot speaks HTML and the text comes from strangers.
"""

from typing import cast

import pytest
from aiogram import Bot

from students_cz.bot.texts import (
    BUDGET_UP_TO,
    NEW_REQUEST_FOR_HELPER,
    NEW_RESPONSE,
    OPEN_APP,
    RESPONSE_ACCEPTED,
    VIEW_REQUEST,
    WAIT_FOR_MESSAGE,
    WRITE_TO,
    pick,
)
from students_cz.db.models.enums import UiLang
from students_cz.services.notify import Notifier, Recipient, _keyboard, quote, tell


def test_quote_escapes_html() -> None:
    """The bot sends HTML, and "<3" is a thing people write."""
    assert quote("матан <3 & čeština") == "матан &lt;3 &amp; čeština"


def test_quote_collapses_whitespace() -> None:
    assert quote("нужен\n\n  матан   срочно") == "нужен матан срочно"


def test_quote_truncates() -> None:
    quoted = quote("а" * 500, limit=50)
    assert len(quoted) == 50
    assert quoted.endswith("…")


def test_quote_truncates_before_escaping_is_undone() -> None:
    """An entity must not be cut in half.

    Escaping after truncation is what guarantees it: cutting "&amp;" at four
    characters would leave "&amp" and Telegram rejects the whole message.
    """
    quoted = quote("<" * 100, limit=20)
    assert "&lt;" in quoted
    assert not quoted.rstrip("…").endswith("&l")


@pytest.mark.parametrize("lang", list(UiLang))
def test_every_language_has_every_string(lang: UiLang) -> None:
    """A missing key must not raise inside a notification."""
    for table in (
        OPEN_APP,
        NEW_RESPONSE,
        RESPONSE_ACCEPTED,
        WRITE_TO,
        WAIT_FOR_MESSAGE,
        NEW_REQUEST_FOR_HELPER,
        BUDGET_UP_TO,
        VIEW_REQUEST,
    ):
        assert pick(table, lang)


def test_the_templates_take_the_parameters_the_callers_pass() -> None:
    """Every placeholder the route fills, filled — a KeyError here is a 500."""
    for lang in UiLang:
        assert pick(NEW_RESPONSE, lang).format(
            topic="матан", helper="Marek", price="", message="помогу"
        )
        assert pick(RESPONSE_ACCEPTED, lang).format(
            topic="матан", student="Азамат", contact=""
        )
        assert pick(WRITE_TO, lang).format(username="vsem_azamat")
        assert pick(WAIT_FOR_MESSAGE, lang)


def test_the_acceptance_message_never_tells_the_helper_to_write_first() -> None:
    """It used to, and the helper has no way to — see the note in texts.py.

    Both endings are complete sentences on their own, because which one is
    appended depends on whether the student has a public username.
    """
    for lang in UiLang:
        with_contact = pick(RESPONSE_ACCEPTED, lang).format(
            topic="матан",
            student="Азамат",
            contact=pick(WRITE_TO, lang).format(username="vsem_azamat"),
        )
        assert "@vsem_azamat" in with_contact

        without = pick(RESPONSE_ACCEPTED, lang).format(
            topic="матан", student="Азамат", contact=pick(WAIT_FOR_MESSAGE, lang)
        )
        assert "@" not in without


def test_no_button_without_an_https_address() -> None:
    """A web_app button requires https, and local development has none."""
    assert _keyboard(UiLang.RU, None) is None
    assert _keyboard(UiLang.RU, "http://localhost:8000") is None
    assert _keyboard(UiLang.RU, "https://tutors.example.com") is not None


@pytest.mark.asyncio
async def test_telling_nobody_is_not_an_error() -> None:
    """The API runs without a bot locally; every caller must still work."""
    assert await tell(None, tg_id=1, text="привет", lang=UiLang.RU, app_url=None) is False


class _Bot:
    """Just enough of aiogram's `Bot` to say whether a send happened.

    A fake rather than a mock: the assertion below is about what reached
    Telegram, and a recorded call is the closest this can get to that without
    a token.
    """

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.sent.append(kwargs)


def _person(**overrides):
    from datetime import UTC, datetime

    from students_cz.db.models import User

    defaults = {
        "tg_id": 42,
        "first_name": "Азамат",
        "ui_lang": UiLang.RU,
        "bot_started_at": datetime.now(UTC),
        "bot_can_message": True,
    }
    return User(**{**defaults, **overrides})


@pytest.mark.asyncio
async def test_nobody_is_written_to_who_never_started_the_bot() -> None:
    """`bot_can_message` defaults to true for everyone, including them.

    Someone who opened the mini app from a direct link and never messaged the
    bot cannot be written to: Telegram answers 403, which `tell` reads as a
    block — losing the notification *and* recording them as having blocked a
    bot they never met.
    """
    bot = _Bot()
    notifier = Notifier(cast(Bot, bot))

    assert (
        await notifier.tell(Recipient.of(_person(bot_started_at=None)), "привет") is False
    )
    assert bot.sent == []


@pytest.mark.asyncio
async def test_nobody_is_written_to_who_blocked_the_bot() -> None:
    bot = _Bot()
    notifier = Notifier(cast(Bot, bot))

    assert (
        await notifier.tell(Recipient.of(_person(bot_can_message=False)), "привет")
        is False
    )
    assert bot.sent == []


@pytest.mark.asyncio
async def test_a_notifier_without_a_bot_delivers_nothing_and_says_so() -> None:
    """The API runs without a token locally; the action must still succeed."""
    assert await Notifier(None).tell(Recipient.of(_person()), "привет") is False


@pytest.mark.asyncio
async def test_a_reachable_person_is_written_to() -> None:
    """The positive control.

    Without it the three above pass for the wrong reason — nothing is sent in
    any of them, so they would all still pass with the guard deleted and the
    bot removed.
    """
    bot = _Bot()

    assert await Notifier(cast(Bot, bot)).tell(Recipient.of(_person()), "привет") is True
    assert bot.sent[0]["chat_id"] == 42
    assert bot.sent[0]["text"] == "привет"


@pytest.mark.asyncio
async def test_the_owner_is_told_when_somebody_is_watching() -> None:
    bot = _Bot()
    notifier = Notifier(cast(Bot, bot), None, owner_tg_id=777)

    assert await notifier.tell_owner("новая анкета") is True
    assert bot.sent[0]["chat_id"] == 777
    assert bot.sent[0]["text"] == "новая анкета"


@pytest.mark.asyncio
async def test_no_owner_means_no_ping_rather_than_an_error() -> None:
    """How it runs until somebody sets `OWNER_TG_ID`, which is most of the time."""
    bot = _Bot()

    assert await Notifier(cast(Bot, bot), None).tell_owner("новая анкета") is False
    assert bot.sent == []


@pytest.mark.asyncio
async def test_the_owner_ping_opens_the_console() -> None:
    """The ping is the reason to look; the console's catalog is where to look."""
    bot = _Bot()
    notifier = Notifier(cast(Bot, bot), "https://tests.example", owner_tg_id=777)

    await notifier.tell_owner("новая заявка")

    (row,) = bot.sent[0]["reply_markup"].inline_keyboard
    (button,) = row
    assert button.text == "Открыть в консоли"
    assert button.web_app.url == "https://tests.example/console/catalog"


@pytest.mark.asyncio
async def test_without_https_the_owner_ping_has_no_button() -> None:
    """A web_app button needs https; a ping without one beats a failed send."""
    bot = _Bot()
    notifier = Notifier(cast(Bot, bot), "http://localhost:5173", owner_tg_id=777)

    await notifier.tell_owner("новая заявка")

    assert bot.sent[0]["reply_markup"] is None


def test_a_request_alert_opens_the_request_among_the_incoming() -> None:
    from students_cz.services.notify import _incoming_keyboard

    keyboard = _incoming_keyboard(UiLang.CS, "https://app.example/", 42)
    assert keyboard is not None
    [[button]] = keyboard.inline_keyboard
    assert button.text == "Zobrazit poptávku"
    assert button.web_app is not None
    assert button.web_app.url == "https://app.example/mine?tab=incoming&request=42"
