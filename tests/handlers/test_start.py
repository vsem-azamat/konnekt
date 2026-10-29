"""The front door: `/start` and `/help`.

`/start` and `/help` used to be one handler, so the first thing anybody saw was
a справочник — twenty lines of commands, most of which they could not run,
which then deleted itself after a minute. The site was mentioned nowhere, and
the console could only be reached by knowing that a command called `/adminlink`
existed.

What is pinned here is who sees what. The wording will move; the rule that a
stranger is not handed the moderator's toolbox, and that `/start` offers one
way in, should not.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from app.core import intro
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


@pytest.fixture(autouse=True)
def _no_media(monkeypatch):
    """Text unless a test sets the media, whatever a developer's .env holds."""
    _media(monkeypatch, photo="", video="", cover="")


def _media(monkeypatch, *, photo: str, video: str, cover: str) -> None:
    monkeypatch.setattr(start_handlers.settings.telegram, "intro_photo", photo)
    monkeypatch.setattr(start_handlers.settings.telegram, "intro_video", video)
    monkeypatch.setattr(start_handlers.settings.telegram, "intro_video_cover", cover)


def _private(factory, command: str, user):
    return factory.create_command_message(
        command=command, user=user, chat=factory.create_chat(id=user.id, type="private", title=None)
    )


def _in_group(factory, command: str, user):
    return factory.create_command_message(command=command, user=user, chat=factory.create_chat())


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
        assert [b.text for b in buttons] == ["Открыть Konnekt 📱"]

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
        assert [b.text for b in buttons] == ["Открыть Konnekt 📱"]

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

    async def test_a_super_admin_is_pointed_at_help_and_nothing_more(self, telegram_factory, admin_repo, site):
        """The console is in the Mini App's header now, for whoever may open it."""
        message = _private(telegram_factory, "start", create_admin_user(id=SUPER_ADMIN_ID))

        await start_handlers.start_private(message, admin_repo)

        text, buttons = _answered(message)
        assert "Вы главный администратор. Все команды — /help" in text
        assert [b.text for b in buttons] == ["Открыть Konnekt 📱"]

    async def test_without_a_configured_site_it_still_answers(self, telegram_factory, admin_repo, monkeypatch):
        """A missing WEBAPI_PUBLIC_URL must not produce a button to nowhere."""
        monkeypatch.setattr(start_handlers.settings.webapi, "public_url", "")
        monkeypatch.setattr(start_handlers.settings.admin, "super_admins", [])
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        assert message.answer.call_args[0][0] == start_handlers.GREETING
        assert message.answer.call_args[1]["reply_markup"] is None


PHOTO = "AgACAgIAAxkBAAIBfake"
VIDEO = "BAACAgIAAxkBAAIBfake"
COVER = "AgACAgIAAxkBAAIcover"


def _album(message) -> list:
    return message.answer_media_group.call_args.kwargs["media"]


@pytest.mark.handlers
class TestTheAlbum:
    """The photo and the video under one caption, then the button in its own message (W2-f)."""

    async def test_the_greeting_is_the_albums_caption_and_the_button_follows(
        self, telegram_factory, admin_repo, site, monkeypatch
    ):
        """Telegram takes no button on an album, so it comes in a message of its own."""
        _media(monkeypatch, photo=PHOTO, video=VIDEO, cover=COVER)
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        text, buttons = _answered(message)
        assert text == "Открывай 👇"
        [button] = buttons
        assert (button.text, button.web_app.url) == ("Открыть Konnekt 📱", f"{SITE}/chats")
        photo, video = _album(message)
        assert (photo.type, photo.media, photo.caption) == ("photo", PHOTO, start_handlers.GREETING)
        assert (video.type, video.media, video.cover, video.caption) == ("video", VIDEO, COVER, None)
        assert video.supports_streaming is True

    async def test_without_a_site_it_is_text(self, telegram_factory, admin_repo, site, monkeypatch):
        """No button to follow the album, and no menu button either: the text says it all."""
        _media(monkeypatch, photo=PHOTO, video=VIDEO, cover=COVER)
        monkeypatch.setattr(start_handlers.settings.webapi, "public_url", "")
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        message.answer_media_group.assert_not_called()
        text, buttons = _answered(message)
        assert (text, buttons) == (start_handlers.GREETING, [])

    def test_a_caption_too_long_is_no_album(self, monkeypatch):
        _media(monkeypatch, photo=PHOTO, video=VIDEO, cover=COVER)

        assert intro.album("П" * (intro.CAPTION_LIMIT + 1)) is None

    async def test_without_a_cover_the_video_shows_its_first_frame(
        self, telegram_factory, admin_repo, site, monkeypatch
    ):
        _media(monkeypatch, photo=PHOTO, video=VIDEO, cover="")
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        assert _album(message)[1].cover is None

    @pytest.mark.parametrize(("photo", "video"), [("", VIDEO), (PHOTO, "")])
    async def test_half_an_album_is_text(self, telegram_factory, admin_repo, site, monkeypatch, photo, video):
        _media(monkeypatch, photo=photo, video=video, cover=COVER)
        message = _private(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        message.answer_media_group.assert_not_called()
        text, buttons = _answered(message)
        assert text == start_handlers.GREETING
        assert [b.text for b in buttons] == ["Открыть Konnekt 📱"]

    async def test_the_super_admin_reads_where_help_is_in_the_caption(
        self, telegram_factory, admin_repo, site, monkeypatch
    ):
        _media(monkeypatch, photo=PHOTO, video=VIDEO, cover=COVER)
        message = _private(telegram_factory, "start", create_admin_user(id=SUPER_ADMIN_ID))

        await start_handlers.start_private(message, admin_repo)

        assert "/help" in _album(message)[0].caption

    async def test_a_lost_connection_does_not_greet_twice(self, telegram_factory, admin_repo, site, monkeypatch):
        """The album may have arrived before the connection dropped."""
        _media(monkeypatch, photo=PHOTO, video=VIDEO, cover=COVER)
        message = _private(telegram_factory, "start", create_normal_user(id=555))
        message.answer_media_group.side_effect = TelegramNetworkError(method=MagicMock(), message="timeout")

        with pytest.raises(TelegramNetworkError):
            await start_handlers.start_private(message, admin_repo)

        message.answer.assert_not_called()

    async def test_a_group_gets_no_album(self, telegram_factory, admin_repo, site, monkeypatch):
        """It would stay in the chat for everybody, after a /start maybe meant for another bot."""
        _media(monkeypatch, photo=PHOTO, video=VIDEO, cover=COVER)
        message = _in_group(telegram_factory, "start", create_normal_user(id=555))

        await start_handlers.start_private(message, admin_repo)

        message.answer_media_group.assert_not_called()
        assert message.answer.call_args[0][0] == start_handlers.GREETING

    def test_the_longest_caption_fits(self) -> None:
        """Telegram caps a caption at 1024 characters, a message at 4096."""
        longest = start_handlers.GREETING + "\n\nВы модерируете 1000 чатов. Все команды — /help"
        assert intro.fits_caption(longest)

    async def test_a_refused_album_still_greets(self, telegram_factory, admin_repo, site, monkeypatch):
        """A stale file_id must not leave /start silent."""
        _media(monkeypatch, photo=PHOTO, video=VIDEO, cover=COVER)
        message = _private(telegram_factory, "start", create_normal_user(id=555))
        message.answer_media_group.side_effect = TelegramBadRequest(
            method=MagicMock(), message="Bad Request: wrong file identifier/HTTP URL specified"
        )

        await start_handlers.start_private(message, admin_repo)

        message.answer_media_group.assert_awaited_once()
        text, buttons = _answered(message)
        assert text == start_handlers.GREETING
        assert [b.text for b in buttons] == ["Открыть Konnekt 📱"]


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
