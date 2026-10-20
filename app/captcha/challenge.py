"""What the applicant sees: a named emoji to find among eight.

Text and buttons only. An image, as the captcha this replaces used, stops a
script no better than the name of an emoji does, and costs a render per
request in exactly the moment there are thousands of them.
"""

import html
import random
from secrets import SystemRandom

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Each emoji with its name as it reads after «нажми на». Unmistakable at a
# glance, and no two alike: a cat and a dog, never a cat and a kitten.
EMOJI: tuple[tuple[str, str], ...] = (
    ("🐱", "кошку"),
    ("🐶", "собаку"),
    ("🍕", "пиццу"),
    ("🍎", "яблоко"),
    ("🍌", "банан"),
    ("🚲", "велосипед"),
    ("🚗", "машину"),
    ("✈️", "самолёт"),
    ("🎸", "гитару"),
    ("⚽", "мяч"),
    ("🔑", "ключ"),
    ("🌧", "тучу с дождём"),
    ("☀️", "солнце"),
    ("🌙", "луну"),
    ("🏠", "дом"),
    ("📚", "книги"),
    ("☕", "чашку кофе"),
    ("🎁", "подарок"),
    ("🐟", "рыбу"),
    ("🌵", "кактус"),
)
NAMES = dict(EMOJI)

OPTIONS = 8
ATTEMPTS = 2
ANSWER_MINUTES = 5

_random = SystemRandom()


class CaptchaPick(CallbackData, prefix="captcha"):
    challenge_id: int
    pick: int


def draw(rng: random.Random = _random) -> tuple[str, list[str]]:
    """An answer and the options it hides among, the answer included once."""
    options = [emoji for emoji, _ in rng.sample(EMOJI, OPTIONS)]
    return rng.choice(options), options


def keyboard(challenge_id: int, options: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=emoji, callback_data=CaptchaPick(challenge_id=challenge_id, pick=i).pack())
        for i, emoji in enumerate(options)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[:4], buttons[4:]])


def ask_text(chat_title: str, answer: str) -> str:
    return (
        f"Привет! Ты подал(а) заявку в чат <b>{html.escape(chat_title)}</b>.\n\n"
        f"Чтобы мы её приняли, нажми на <b>{NAMES[answer]}</b>.\n\n"
        f"На ответ {ANSWER_MINUTES} минут. Две ошибки, и заявка отклоняется."
    )


def retry_text(chat_title: str, answer: str) -> str:
    return (
        f"Не то. Осталась одна попытка.\n\n"
        f"Чтобы попасть в чат <b>{html.escape(chat_title)}</b>, нажми на <b>{NAMES[answer]}</b>."
    )


def passed_text(chat_title: str) -> str:
    return f"Готово, ты в чате <b>{html.escape(chat_title)}</b>."


def failed_text(chat_title: str) -> str:
    return f"Заявка в <b>{html.escape(chat_title)}</b> отклонена: проверка не пройдена. Можно подать её ещё раз."


def gone_text(chat_title: str) -> str:
    return f"Заявку в <b>{html.escape(chat_title)}</b> уже рассмотрели админы чата."


def open_chat(link: str | None) -> InlineKeyboardMarkup | None:
    if not link:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть чат", url=link)]])
