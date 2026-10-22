"""The front door: `/start`, `/help`, and the way into the console.

`/start` and `/help` used to be one handler, so the first thing anybody saw was
a справочник — twenty lines of commands, most of which they could not run,
which then deleted itself after a minute. The site was mentioned nowhere, and
the console could only be reached by knowing that a command called `/adminlink`
existed.

What is pinned here is who sees what. The wording will move; the rule that a
stranger is not handed the moderator's toolbox, and that the console button
belongs to super administrators alone, should not.
"""

from unittest.mock import AsyncMock, patch

import pytest
from app.presentation.telegram.handlers import start as start_handlers

from tests.plain_language import slang
from tests.telegram_helpers import TelegramObjectFactory, create_admin_user, create_normal_user

SUPER_ADMIN_ID = 123456789
SITE = "https://konnekt.example"
CONTACT = "konnekt_ads_example_bot"


@pytest.fixture
def telegram_factory():
    return TelegramObjectFactory()


@pytest.fixture
def admin_repo():
    repo = AsyncMock()
    repo.is_admin.return_value = False
    repo.chats_for.return_value = []
    return repo


@pytest.fixture
def site(monkeypatch):
    """A configured public URL, so the web buttons have somewhere to point."""
    monkeypatch.setattr(start_handlers.settings.webapi, "public_url", SITE)
    monkeypatch.setattr(start_handlers.settings.admin, "super_admins", [SUPER_ADMIN_ID])
    monkeypatch.setattr(start_handlers.settings.ads_bot, "contact", CONTACT)


def _private(factory, command: str, user):
    return factory.create_command_message(
        command=command, user=user, chat=factory.create_chat(id=user.id, type="private", title=None)
    )


def _in_group(factory, command: str, user):
    return factory.create_command_message(command=command, user=user, chat=factory.create_chat())


def _rows(message) -> list[list]:
    markup = message.answer.call_args[1].get("reply_markup")
    return markup.inline_keyboard if markup else []


def _answered(message) -> tuple[str, list]:
    text = message.answer.call_args[0][0]
    markup = message.answer.call_args[1].get("reply_markup")
    buttons = [b for row in markup.inline_keyboard for b in row] if markup else []
    return text, buttons


@pytest.mark.handlers
class TestStart:
    async def test_a_stranger_gets_one_way_in(self, telegram_factory, admin_repo, site):
        """Advertising and «Написать нам» live in the Mini App's profile and /contacts."""
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        text, buttons = _answered(message)
        assert text == start_handlers.GREETING
        assert [b.text for b in buttons] == ["Открыть Konnekt"]

    async def test_the_way_in_is_the_catalogue(self, telegram_factory, admin_repo, site):
        """Where the menu button «Открыть» goes too: most people come for a chat.

        As a Mini App rather than a link: opened as a site, a tap on a chat
        leaves Telegram for a browser which then reopens Telegram.
        """
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        _, buttons = _answered(message)
        assert buttons[0].web_app is not None
        assert buttons[0].web_app.url == f"{SITE}/chats"
        assert buttons[0].url is None

    async def test_a_stranger_is_not_handed_the_command_list(self, telegram_factory, admin_repo, site):
        """The greeting answers "what is this", not "what can you type"."""
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        text, _ = _answered(message)
        assert "/help" not in text
        assert "/mute" not in text

    async def test_a_moderator_is_pointed_at_help(self, telegram_factory, admin_repo, site):
        admin_repo.is_admin.return_value = True
        admin_repo.chats_for.return_value = [-100_1, -100_2]
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        text, buttons = _answered(message)
        assert text.startswith(start_handlers.GREETING)
        assert "Вы модерируете 2 чата" in text
        assert "/help" in text
        assert [b.text for b in buttons] == ["Открыть Konnekt"]

    async def test_a_deep_link_gets_the_same_answer(self, telegram_factory, admin_repo, site):
        """?start=<source> is recorded by the audience middleware; the greeting ignores it."""
        message = telegram_factory.create_command_message(
            command="start",
            args="matfyz",
            user=create_normal_user(id=555),
            chat=telegram_factory.create_chat(id=555, type="private", title=None),
        )

        await start_handlers.start_private(message, admin_repo)

        text, buttons = _answered(message)
        assert text == start_handlers.GREETING
        assert buttons[0].web_app.url == f"{SITE}/chats"

    async def test_the_greeting_speaks_as_us(self, telegram_factory, admin_repo, site):
        """A stranger's greeting says what happens to spam, not who does it."""
        assert "модер" not in start_handlers.GREETING.lower()

    async def test_the_greeting_is_plain_language(self, telegram_factory, admin_repo, site):
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        text, buttons = _answered(message)
        assert slang(text) == []
        assert [b.text for b in buttons if slang(b.text)] == []

    async def test_in_a_group_the_site_stays_an_ordinary_link(self, telegram_factory, admin_repo, site):
        """Telegram refuses a web_app button outside a private chat.

        It refuses the message, not the button: `/start` in a group would answer
        nothing at all rather than answer with one button missing.
        """
        message = _in_group(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        _, buttons = _answered(message)
        assert all(b.web_app is None for b in buttons)
        assert buttons[0].url == f"{SITE}/chats"

    async def test_a_site_without_tls_stays_an_ordinary_link(self, telegram_factory, admin_repo, monkeypatch):
        """Telegram requires https for a Mini App; local development has none."""
        monkeypatch.setattr(start_handlers.settings.webapi, "public_url", "http://localhost:5173")
        monkeypatch.setattr(start_handlers.settings.admin, "super_admins", [])
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        _, buttons = _answered(message)
        assert all(b.web_app is None for b in buttons)
        assert buttons[0].url == "http://localhost:5173/chats"

    async def test_the_greeting_is_not_deleted(self, telegram_factory, admin_repo, site):
        """It is the first screen of the product, not a service reply.

        The old one self-destructed after sixty seconds, taking the only thing
        that explained the bot with it.
        """
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        with patch.object(start_handlers.other, "sleep_and_delete") as scheduled:
            await start_handlers.start_private(message, admin_repo)

        scheduled.assert_not_called()

    async def test_no_console_button_for_an_ordinary_person(self, telegram_factory, admin_repo, site):
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        _, buttons = _answered(message)
        assert not any("онсол" in b.text for b in buttons)

    async def test_a_super_admin_is_offered_the_console_on_top(self, telegram_factory, admin_repo, site):
        """This replaces having to know that `/adminlink` exists."""
        message = _private(telegram_factory, "start", create_admin_user(id=SUPER_ADMIN_ID))

        await start_handlers.start_private(message, admin_repo)

        text, buttons = _answered(message)
        assert "/help" in text
        assert [len(row) for row in _rows(message)] == [1, 1]
        console, way_in = buttons
        assert "онсол" in console.text
        # Straight into the console as a Mini App. It used to be a callback that
        # minted a sign-in link; the console now reads the signature Telegram
        # already attached, so there is no link to mint and none to leak.
        assert console.web_app is not None
        assert console.web_app.url == f"{SITE}/console"
        assert way_in.web_app.url == f"{SITE}/chats"

    async def test_the_console_is_not_offered_where_it_cannot_open(self, telegram_factory, admin_repo, site):
        """Signing in means handing over `initData`, which only a Mini App has.

        In a group the button would have to be a plain link, and the browser it
        opened would reach a console able to do nothing but turn them away.
        """
        message = _in_group(telegram_factory, "start", create_admin_user(id=SUPER_ADMIN_ID))

        await start_handlers.start_private(message, admin_repo)

        _, buttons = _answered(message)
        assert not any("онсол" in b.text for b in buttons)

    async def test_without_a_configured_site_it_still_answers(self, telegram_factory, admin_repo, monkeypatch):
        """A missing WEBAPI_PUBLIC_URL must not produce a button to nowhere."""
        monkeypatch.setattr(start_handlers.settings.webapi, "public_url", "")
        monkeypatch.setattr(start_handlers.settings.admin, "super_admins", [])
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        assert message.answer.call_args[0][0] == start_handlers.GREETING
        assert message.answer.call_args[1]["reply_markup"] is None


@pytest.mark.handlers
class TestHelp:
    async def test_a_stranger_sees_only_what_they_can_run(self, telegram_factory, admin_repo, site):
        message = _private(telegram_factory, "help", create_normal_user(id=555))

        await start_handlers.help_command(message, admin_repo)

        text, _ = _answered(message)
        assert "/report" in text
        assert "/mute" not in text
        assert "/banall" not in text
        # The section everybody sees speaks as the video does; the moderator's
        # own section, which they alone see, still says who they are.
        assert "модер" not in text.lower()

    async def test_a_moderator_sees_the_chat_scoped_commands(self, telegram_factory, admin_repo, site):
        admin_repo.is_admin.return_value = True
        admin_repo.chats_for.return_value = [-100_1, -100_2]
        message = _private(telegram_factory, "help", create_normal_user(id=555))

        await start_handlers.help_command(message, admin_repo)

        text, _ = _answered(message)
        assert "/mute" in text
        assert "/ban" in text
        # Reaching every chat at once is not theirs to do.
        assert "/banall" not in text

    async def test_a_super_admin_sees_the_global_ones(self, telegram_factory, admin_repo, site):
        message = _private(telegram_factory, "help", create_admin_user(id=SUPER_ADMIN_ID))

        await start_handlers.help_command(message, admin_repo)

        text, _ = _answered(message)
        assert "/banall" in text
        assert "/blacklist" in text

    async def test_the_global_reach_stops_at_approval(self, telegram_factory, admin_repo, site):
        """A blacklist entry acts in approved chats only, so help does not promise every chat."""
        message = _private(telegram_factory, "help", create_admin_user(id=SUPER_ADMIN_ID))

        await start_handlers.help_command(message, admin_repo)

        text, _ = _answered(message)
        assert "везде" not in text
        assert "во всех чатах" not in text
        assert "во всех одобренных чатах" in text

    async def test_the_dead_and_the_debug_commands_are_not_advertised(self, telegram_factory, admin_repo, site):
        """`/adminlink` no longer exists, and `/json` is a debugging dump."""
        message = _private(telegram_factory, "help", create_admin_user(id=SUPER_ADMIN_ID))

        await start_handlers.help_command(message, admin_repo)

        text, _ = _answered(message)
        assert "/adminlink" not in text
        assert "/webadmin" not in text
        assert "/json" not in text


@pytest.mark.handlers
class TestTheContact:
    """Where advertisers and anybody with a question write: one configured username.

    The same variable gives the web's ads pages their button, so the bot and
    the site cannot point to different people.
    """

    async def test_contacts_names_the_configured_contact(self, telegram_factory, site):
        message = _in_group(telegram_factory, "contacts", create_normal_user(id=555))

        with patch.object(start_handlers.other, "sleep_and_delete"):
            await start_handlers.get_contacts(message)

        text = message.answer.call_args[0][0]
        assert f"@{CONTACT}" in text
        # Any question, not only cooperation: the contact desk answers them all.
        assert "Написать нам" in text
        assert "по любому вопросу" in text
        assert "Сотрудничество" not in text

    async def test_without_a_contact_contacts_leaves_the_line_out(self, telegram_factory, site, monkeypatch):
        monkeypatch.setattr(start_handlers.settings.ads_bot, "contact", "")
        message = _in_group(telegram_factory, "contacts", create_normal_user(id=555))

        with patch.object(start_handlers.other, "sleep_and_delete"):
            await start_handlers.get_contacts(message)

        assert "Написать нам" not in message.answer.call_args[0][0]
