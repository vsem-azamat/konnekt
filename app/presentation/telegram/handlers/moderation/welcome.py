"""!welcome command — set per-chat welcome message."""

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.utils.text_decorations import html_decoration

from app.db.repositories import ChatRepository

router = Router()

_USAGE = (
    "Напишите приветствие после команды: <code>!welcome Добро пожаловать! Правила — в закрепе.</code>\n"
    "Жирный, курсив и ссылки сохранятся."
)


def _greeting(message: types.Message) -> str:
    """The text after the command as HTML, from the message's own entities.

    Rendered by Telegram's rules, so the admin's formatting survives and a `<`
    they typed is escaped: the raw text was stored and sent as HTML, and one
    typo broke the greeting for every join. Cut in the plain text and then
    rendered, never sliced out of rendered HTML, which split formatting that
    began before the cut and lost the first word after a newline.
    """
    text = message.text or ""
    start = 0
    while start < len(text) and not text[start].isspace():
        start += 1
    while start < len(text) and text[start].isspace():
        start += 1
    body = text[start:]
    # Entity offsets count UTF-16 code units.
    cut = len(text[:start].encode("utf-16-le")) // 2
    entities = []
    for entity in message.entities or []:
        end = entity.offset + entity.length
        if entity.type == "bot_command" or end <= cut:
            continue
        offset = max(entity.offset, cut)
        entities.append(entity.model_copy(update={"offset": offset - cut, "length": end - offset}))
    return html_decoration.unparse(body, entities).strip()


@router.message(Command("welcome", prefix="!/"))
async def welcome_change(message: types.Message, chat_repo: ChatRepository) -> None:
    welcome_message = _greeting(message)
    if not welcome_message:
        await message.answer(_USAGE)
        return
    await chat_repo.update_welcome_message(message.chat.id, welcome_message)
    await message.answer("<b>Приветствие сохранено и включено.</b> Так его увидят новые участники:")
    await message.answer(welcome_message)
    await message.delete()
