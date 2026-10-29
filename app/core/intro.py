"""Konnekt introducing itself: what it is, its video and the one button into the app.

Said in three places — `/start`, the greeting in a chat and the private chat
after the captcha. `/start` is an album, the photo and the video under one
caption: the person came to the bot, and the menu button «Открыть» is the way
in, so it carries no button. A chat gets the video alone, since an album takes
no button and the greeting's link is the point there. The media are settings,
each off until it is set.
"""

import html
import re

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
    WebAppInfo,
)
from aiogram.types.media_union import MediaUnion

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("intro")

OPEN_BUTTON = "Открыть Konnekt 📱"

# What Konnekt is, under the /start album and the greeting in a chat alike.
ABOUT = (
    "<b>Konnekt</b> — всё для студентов в Чехии в одном приложении.\n\n"
    "💬 чат своего факультета в пару касаний\n"
    "🎓 репетиторы и помощь с экзаменами\n"
    "📄 страховка, справки, жильё\n"
    "🙋 умеешь то, что нужно другим? Предложи услугу"
)

# Telegram's limit for a caption, counted after the markup is parsed.
CAPTION_LIMIT = 1024
# How Telegram refuses a text with broken HTML.
PARSE_ERROR = "can't parse entities"


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


def album(caption: str) -> list[MediaUnion] | None:
    """The photo, then the video, with `caption` under them; None unless both are set.

    The caption goes on the first item, which is where Telegram shows an
    album's text, below the media.
    """
    photo, video = settings.telegram.intro_photo, settings.telegram.intro_video
    if not (photo and video and fits_caption(caption)):
        return None
    return [
        InputMediaPhoto(media=photo, caption=caption),
        InputMediaVideo(media=video, cover=settings.telegram.intro_video_cover or None, supports_streaming=True),
    ]


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
            sent = await bot.send_video(
                chat_id=chat_id,
                video=video,
                cover=settings.telegram.intro_video_cover or None,
                supports_streaming=True,
                caption=text,
                reply_markup=markup,
            )
            return sent, True
        except TelegramBadRequest as err:
            # The text is at fault, not the video: it fails as a message too.
            if PARSE_ERROR in str(err):
                raise
            logger.error("intro_video_refused", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
    sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, disable_web_page_preview=True)
    return sent, False
