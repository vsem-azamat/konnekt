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

from app.core.text import plural

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
# The same, as the subject of «… ждёт в сообщении выше».
NOMINATIVE = {
    "🐱": "кошка",
    "🐶": "собака",
    "🍕": "пицца",
    "🍎": "яблоко",
    "🍌": "банан",
    "🚲": "велосипед",
    "🚗": "машина",
    "✈️": "самолёт",
    "🎸": "гитара",
    "⚽": "мяч",
    "🔑": "ключ",
    "🌧": "туча с дождём",
    "☀️": "солнце",
    "🌙": "луна",
    "🏠": "дом",
    "📚": "книги",
    "☕": "чашка кофе",
    "🎁": "подарок",
    "🐟": "рыба",
    "🌵": "кактус",
}
_PLURAL = {"📚"}

OPTIONS = 8
ATTEMPTS = 2

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


def ask_text(chat_title: str, answer: str, minutes: int) -> str:
    # The answer in capitals and bold, here and wherever it is named again:
    # it is the one word the applicant has to find on the board.
    return (
        f"🔐 Проверка для чата <b>{html.escape(chat_title)}</b>\n\n"
        f"Нажми на <b>{NAMES[answer].upper()}</b>, и заявку примут.\n\n"
        f"⏱ {minutes} {plural(minutes, 'минута', 'минуты', 'минут')}."
    )


def waits(answer: str) -> str:
    return "ждут" if answer in _PLURAL else "ждёт"


def reminder_text(answer: str, minutes_left: int) -> str:
    return (
        f"⏳ Ещё {minutes_left} {plural(minutes_left, 'минута', 'минуты', 'минут')} — "
        f"<b>{NOMINATIVE[answer].upper()}</b> {waits(answer)} в сообщении выше."
    )


def retry_hint(answer: str, attempts_left: int) -> str:
    """The popup after a wrong tap. A popup takes no markup, so the capitals carry the answer alone."""
    return (
        f"Не то — нажми на {NAMES[answer].upper()}. "
        f"{plural(attempts_left, 'Осталась', 'Осталось', 'Осталось')} {attempts_left} "
        f"{plural(attempts_left, 'попытка', 'попытки', 'попыток')}"
    )


def passed_text(chat_title: str, link: str | None) -> str:
    """The chat's name is its link: one tap into the chat without a button of its own."""
    title = html.escape(chat_title)
    where = f'<a href="{html.escape(link)}">{title}</a>' if link else f"<b>{title}</b>"
    return f"✅ Готово, ты в {where}!"


# Under the video after the captcha, with the button into the app.
INTRO = "👋 Это Konnekt: чаты других факультетов и общежитий и люди, которые помогут с учёбой."


def failed_text(chat_title: str) -> str:
    return f"Заявка в <b>{html.escape(chat_title)}</b> отклонена: проверка не пройдена. Можно подать её ещё раз."


def expired_text(chat_title: str) -> str:
    return f"Заявка в <b>{html.escape(chat_title)}</b> отклонена: время вышло. Можно подать её ещё раз."


def gone_text(chat_title: str) -> str:
    return f"Заявку в <b>{html.escape(chat_title)}</b> уже рассмотрели админы чата."


def handed_back_text(chat_title: str) -> str:
    return f"Заявку в <b>{html.escape(chat_title)}</b> рассмотрят админы чата."


def superseded_text(chat_title: str) -> str:
    return f"Эта проверка для чата <b>{html.escape(chat_title)}</b> больше не действует: ты подал(а) новую заявку."
