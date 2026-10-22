"""Konnekt introducing itself: the demo video and the one button into the app.

Said in three places — `/start`, the greeting in a chat and the private chat
after the captcha — and kept here so the button reads the same in all of them
and the video is one setting, off until the final cut is approved.
"""

import html
import re

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("intro")

OPEN_BUTTON = "Открыть Konnekt 📱"

# Telegram's limit for a caption, counted after the markup is parsed.
CAPTION_LIMIT = 1024


def private_markup() -> InlineKeyboardMarkup | None:
    """The button into «Чаты» for a private chat: a Mini App where Telegram accepts one, a link otherwise."""
    site = settings.webapi.public_url.rstrip("/")
    if not site:
        return None
    url = f"{site}/chats"
    button = (
        InlineKeyboardButton(text=OPEN_BUTTON, web_app=WebAppInfo(url=url))
        if url.startswith("https://")
        else InlineKeyboardButton(text=OPEN_BUTTON, url=url)
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def fits_caption(text: str) -> bool:
    return len(html.unescape(re.sub(r"<[^>]+>", "", text))) <= CAPTION_LIMIT


async def send(bot: Bot, chat_id: int, text: str, markup: InlineKeyboardMarkup | None) -> tuple[Message, bool]:
    """Send `text` as the video's caption when there is a video, as a message otherwise.

    Returns the message and whether it is the video, which decides how it is
    edited later. A video Telegram refuses — another bot's file_id, a URL it
    could not fetch — falls back to text: the words matter more than the clip.
    Network errors are not caught, since the video may have arrived.
    """
    video = settings.telegram.intro_video
    if video and fits_caption(text):
        try:
            return await bot.send_video(chat_id=chat_id, video=video, caption=text, reply_markup=markup), True
        except TelegramBadRequest as err:
            logger.error("intro_video_refused", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
    sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, disable_web_page_preview=True)
    return sent, False
