"""The front door: a greeting, a справочник, and the way into the console.

`/start` and `/help` were one handler answering one wall of text. That wall was
the first thing a first-year saw, it listed commands they could not run, it
never mentioned the site the whole catalogue lives on, and it deleted itself
after sixty seconds.

They are two questions. `/start` answers "what is this and where do I go" and
stays on screen; `/help` answers "what can I type" and still grows with the
role of whoever asked.
"""

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

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


def _mini_app_possible(*, private: bool) -> bool:
    """Whether Telegram will accept a Mini App button here at all.

    It wants a private chat and an https address, and it refuses the whole
    message rather than the offending button — so `/start` in a group would
    answer nothing, and so would a developer pointed at plain http.
    """
    return private and settings.webapi.public_url.startswith("https://")


def _open_button(text: str, url: str, *, private: bool) -> types.InlineKeyboardButton:
    """Open the site inside Telegram where that is allowed, as a link where it is not.

    A Mini App is the difference between reading the catalogue and using it: it
    inherits the client's theme, and a tap on a chat opens that chat in place
    instead of bouncing out to a browser and back.
    """
    if private and url.startswith("https://"):
        return types.InlineKeyboardButton(text=text, web_app=types.WebAppInfo(url=url))
    return types.InlineKeyboardButton(text=text, url=url)


@router.message(Command("start", prefix="/!"))
async def start_private(message: types.Message, admin_repo: AdminRepository) -> None:
    """Say what this is, and offer the two places worth going."""
    if not message.from_user:
        return

    text = (
        "<b>Konnekt</b>\n\n"
        "Каталог студенческих чатов Чехии — по университетам, факультетам "
        "и общежитиям. Спам, скам и фишинг из чатов мы вычищаем.\n\n"
    )
    # Said only when its button is there: the greeting names what it offers.
    if settings.webapi.public_url:
        text += "А ещё здесь люди, которые помогут с учёбой: репетиторы, подготовка к вступительным экзаменам, нострификация.\n\n"

    is_super_admin = message.from_user.id in settings.admin.super_admins
    if is_super_admin:
        text += "Вы главный администратор. Все команды — /help"
    elif await admin_repo.is_admin(message.from_user.id):
        chats = await admin_repo.chats_for(message.from_user.id)
        moderates = plural(len(chats), "чат", "чата", "чатов")
        text += f"Вы модерируете {len(chats)} {moderates}. Все команды — /help"
    else:
        text += "Все команды — /help"

    private = message.chat.type == "private"

    # The console is a Mini App and only a Mini App: signing in means handing
    # over the `initData` Telegram signed, which a browser opened from a group
    # would not have. Offering the button where it cannot work would send the
    # one person who has it to a page that can only turn them away.
    shows_console = is_super_admin and _mini_app_possible(private=private)

    builder = InlineKeyboardBuilder()
    if shows_console:
        builder.add(_open_button("⚙️ Открыть консоль", f"{_site()}/console", private=private))
    if settings.webapi.public_url:
        builder.add(_open_button("🔎 Найти свой чат", f"{_site()}/chats", private=private))
        # The Mini App's first screen. Its own row, second: finding a chat is
        # why most people come.
        builder.add(_open_button("🎓 Помощь с учёбой", _site(), private=private))
        builder.add(_open_button("📣 Реклама в чатах", f"{_site()}/ads", private=private))
    # Where somebody who wants to place an advertisement, or to say anything
    # else, is sent. The bot answers questions about chats; people answer the rest.
    if contact := settings.ads_bot.contact_username:
        builder.add(types.InlineKeyboardButton(text="✉️ Написать нам", url=f"https://t.me/{contact}"))

    # A column of identical full-width buttons reads as a wall, and gives the
    # same weight to the reason somebody opened the bot and to the two things
    # nobody did. Advertising and the contact link share the last row; the
    # shape depends on the console, which only a super administrator is shown.
    lead = [1] * (int(shows_console) + int(bool(settings.webapi.public_url)))
    builder.adjust(*(lead + [1, 2]))

    # Deliberately not scheduled for deletion. This is the message somebody
    # comes back to; the справочник below is the one that may go.
    await message.answer(text, disable_web_page_preview=True, reply_markup=builder.as_markup())


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
        "/contacts — связаться\n"
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
        lines.append(f"• 📧 <b>Сотрудничество:</b> @{contact}")
    lines.append("• 🧑🏿‍💻 <b>Dev:</b> @vsem_azamat")
    text = "\n".join(lines)
    bot_message = await message.answer(text)
    await message.delete()
    other.sleep_and_delete(bot_message)
