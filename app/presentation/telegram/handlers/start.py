"""The front door: a greeting and a справочник.

`/start` and `/help` were one handler answering one wall of text. That wall was
the first thing a first-year saw, it listed commands they could not run, it
never mentioned the site the whole catalogue lives on, and it deleted itself
after sixty seconds.

They are two questions. `/start` answers "what is this and where do I go" and
stays on screen; `/help` answers "what can I type" and still grows with the
role of whoever asked.
"""

from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import intro
from app.core.config import settings
from app.core.logging import get_logger
from app.core.text import plural
from app.db.repositories import AdminRepository
from app.presentation.telegram.utils import buttons as buttons_service
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
        "/chats — чаты списком\n"
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
async def get_chats(message: types.Message, db: AsyncSession) -> None:
    text = "<b>Студенческие чаты:</b>\n\nПожалуйста, соблюдайте правила!\n\n"
    builder = await buttons_service.get_chat_buttons(db)
    bot_message = await message.answer(text, reply_markup=builder.as_markup())
    await message.delete()
    other.sleep_and_delete(bot_message)


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
