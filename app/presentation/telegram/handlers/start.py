"""The front door: a greeting and a справочник.

`/start` and `/help` were one handler answering one wall of text. That wall was
the first thing a first-year saw, it listed commands they could not run, it
never mentioned the site the whole catalogue lives on, and it deleted itself
after sixty seconds.

They are two questions. `/start` answers "what is this and where do I go" and
stays on screen; `/help` answers "what can I type" and still grows with the
role of whoever asked.
"""

from contextlib import suppress

from aiogram import Bot, Router, types
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats import faculty_list
from app.core import intro
from app.core.config import settings
from app.core.logging import get_logger
from app.core.text import plural
from app.db.repositories import AdminRepository
from app.presentation.telegram.utils import other

router = Router()
logger = get_logger("handlers.start")


def _site() -> str:
    return settings.webapi.public_url.rstrip("/")


def _open_button(text: str, url: str, *, private: bool) -> types.InlineKeyboardButton:
    """Open the site inside Telegram where that is allowed, as a link where it is not.

    A Mini App is the difference between reading the catalogue and using it: it
    inherits the client's theme, and a tap on a chat opens that chat in place
    instead of bouncing out to a browser and back.
    """
    if private and url.startswith("https://"):
        return types.InlineKeyboardButton(text=text, web_app=types.WebAppInfo(url=url))
    return types.InlineKeyboardButton(text=text, url=url)


# The copy lives in app/core/intro.py, shared with the greeting in a chat.
GREETING = intro.ABOUT
OPEN_BUTTON = intro.OPEN_BUTTON
# Under the album, which takes no button of its own.
BUTTON_NOTE = "Открывай 👇"
# /chats where the bot knows no university to list, and in private.
CHATS_IN_APP = "Все студенческие чаты Чехии — в Konnekt 👇"
# Where the app records that somebody came from /chats in a group.
CHATS_SOURCE = "chats"
# How long /chats and its answer stay in a group.
CHATS_ANSWER_SECONDS = 300
# The last /chats answer in each group, which the next one replaces.
_chats_answers: dict[int, int] = {}


@router.message(Command("start", prefix="/!"))
async def start_private(message: types.Message, admin_repo: AdminRepository) -> None:
    """Say what this is, and offer one way in: the chats.

    The album, then the button in a message of its own, since Telegram takes
    none on an album (W2-f); text with the button where there is no album. The
    console is in the Mini App's header for whoever may open it. A deep link
    (`/start <source>`) gets the same answer; the audience middleware has
    already recorded the source.
    """
    if not message.from_user:
        return

    text = GREETING
    # Only those who have more to type than a stranger are pointed at /help.
    if message.from_user.id in settings.admin.super_admins:
        text += "\n\nВы главный администратор. Все команды — /help"
    elif await admin_repo.is_admin(message.from_user.id):
        chats = await admin_repo.chats_for(message.from_user.id)
        moderates = plural(len(chats), "чат", "чата", "чатов")
        text += f"\n\nВы модерируете {len(chats)} {moderates}. Все команды — /help"

    private = message.chat.type == "private"
    markup = None
    if settings.webapi.public_url:
        button = _open_button(OPEN_BUTTON, f"{_site()}/chats", private=private)
        markup = types.InlineKeyboardMarkup(inline_keyboard=[[button]])

    # Deliberately not scheduled for deletion: this is the message somebody
    # comes back to. The album only in a private chat: in a group it would stay
    # for everybody, after a /start that may have been meant for another bot.
    # And only with a button to follow it: without a site there is no menu
    # button either, and the text is all there is.
    if private and markup and (media := intro.album(text)):
        try:
            await message.answer_media_group(media=media)
        except TelegramBadRequest as err:
            # A file_id of another bot, or a URL Telegram could not fetch, must
            # not leave /start silent. Network errors are not caught: the album
            # may have arrived, and a second greeting would follow it.
            logger.error("start_album_refused", error=str(err), error_type=type(err).__name__)
        else:
            await message.answer(BUTTON_NOTE, reply_markup=markup)
            return

    await message.answer(text, disable_web_page_preview=True, reply_markup=markup)


@router.message(Command("help", prefix="/!"))
async def help_command(message: types.Message, admin_repo: AdminRepository) -> None:
    """List what this person, specifically, may type.

    Grouped by how far a mistake travels — one chat, or all of them. That split
    is the permission rule the routers already enforce, and a help text that
    grouped them any other way would teach the wrong shape.
    """
    if not message.from_user:
        return

    text = (
        "<b>Команды</b>\n\n"
        "<b>Всем</b>\n"
        "/chats — чаты вуза и факультетов\n"
        "/contacts — написать нам\n"
        "/report — в ответ на сообщение, пожаловаться на него (в группе)\n"
    )

    is_super_admin = message.from_user.id in settings.admin.super_admins
    if is_super_admin or await admin_repo.is_admin(message.from_user.id):
        if is_super_admin:
            where = "во всех одобренных чатах"
        else:
            chats = await admin_repo.chats_for(message.from_user.id)
            where = f"в ваших чатах ({len(chats)})"
        text += (
            f"\n<b>Модератору</b> — {where}\n"
            "/mute, /unmute — заглушить, вернуть голос\n"
            "/kick — удалить, сможет вернуться\n"
            "/ban, /unban — забанить в этом чате\n"
            "/del, /purge — удалить сообщение, удалить пачкой\n"
            "/pin, /unpin — закрепить, открепить\n"
            "/info — что известно о человеке\n"
            "/welcome &lt;текст&gt; — приветствие чата\n"
        )

    if is_super_admin:
        text += (
            "\n<b>Главному администратору</b>\n"
            "/banall — забанить во всех одобренных чатах, в ответ на сообщение\n"
            "/blacklist — чёрный список, поиск по нему\n"
            "/admin, /unadmin — назначить, снять модератора этого чата\n"
        )

    bot_message = await message.answer(text, disable_web_page_preview=True)
    await message.delete()
    other.sleep_and_delete(bot_message)


@router.message(Command("chats", prefix="/!"))
async def get_chats(message: types.Message, bot: Bot, db: AsyncSession) -> None:
    """The chats somebody is looking for, from where they asked.

    In a university's chat its faculties, in a faculty's the whole university,
    from the rows the catalog lists; anywhere else, and in private, the way
    into the catalog itself. In a group the command and the answer both go
    after a while (Azamat, 9737), and a new answer takes the place of the one
    before it. The clock is this process's: a restart within those minutes
    leaves both in the chat.
    """
    me = await bot.me()
    catalogue = types.InlineKeyboardButton(
        text=faculty_list.APP_BUTTON, url=f"https://t.me/{me.username}?startapp={CHATS_SOURCE}"
    )
    if message.chat.type == "private":
        button = (
            _open_button(OPEN_BUTTON, f"{_site()}/chats", private=True) if settings.webapi.public_url else catalogue
        )
        await message.answer(CHATS_IN_APP, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[button]]))
        return

    listing = await faculty_list.listing_for(db, message.chat.id)
    if listing is not None and listing.chats:
        text = faculty_list.text(listing.university, listing.chats, heading=listing.heading)
        markup = faculty_list.markup(faculty_list.app_url(me.username or "", listing.code))
    else:
        text = CHATS_IN_APP
        markup = types.InlineKeyboardMarkup(inline_keyboard=[[catalogue]])
    answer = await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    if (before := _chats_answers.get(message.chat.id)) is not None:
        with suppress(TelegramAPIError):
            await bot.delete_message(message.chat.id, before)
    _chats_answers[message.chat.id] = answer.message_id
    other.sleep_and_delete(message, CHATS_ANSWER_SECONDS)
    other.sleep_and_delete(answer, CHATS_ANSWER_SECONDS)


@router.message(Command("contacts", prefix="/!"))
async def get_contacts(message: types.Message) -> None:
    lines = ["📞 <b>Контакты:</b>", ""]
    if contact := settings.ads_bot.contact_username:
        lines.append(f"• ✉️ <b>Написать нам:</b> @{contact} (по любому вопросу)")
    lines.append("• 🧑🏿‍💻 <b>Dev:</b> @vsem_azamat")
    text = "\n".join(lines)
    bot_message = await message.answer(text)
    await message.delete()
    other.sleep_and_delete(bot_message)
