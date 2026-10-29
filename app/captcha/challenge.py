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


def duration(minutes: int) -> str:
    """«15 минут», «24 часа», «23 часа 56 минут»: hours from an hour up, so a long window reads as a day, not as 1440."""
    hours, rest = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} {plural(hours, 'час', 'часа', 'часов')}")
    if rest or not hours:
        parts.append(f"{rest} {plural(rest, 'минута', 'минуты', 'минут')}")
    return " ".join(parts)


def ask_text(chat_title: str, answer: str, minutes: int) -> str:
    # The answer in capitals and bold, here and wherever it is named again:
    # it is the one word the applicant has to find on the board.
    return (
        f"🔐 Проверка для чата <b>{html.escape(chat_title)}</b>\n\n"
        f"Нажми на <b>{NAMES[answer].upper()}</b>, и заявку примут.\n\n"
        f"⏱ На ответ {duration(minutes)}."
    )


def waits(answer: str) -> str:
    return "ждут" if answer in _PLURAL else "ждёт"


def reminder_text(answer: str, minutes_left: int) -> str:
    return f"⏳ Ещё {duration(minutes_left)} — <b>{NOMINATIVE[answer].upper()}</b> {waits(answer)} в сообщении выше."


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


# --- asked in the chat (app/captcha/in_chat.py) ------------------------------

# What the card's button opens the bot with: `/start captcha`.
START_PAYLOAD = "captcha"
CARD_BUTTON = "Пройти капчу"


def card_text(names: list[str], minutes: int) -> str:
    """The message in the chat naming who may not write yet; `names` are HTML, mentions or plain."""
    if len(names) == 1:
        who, verb, whom = names[0], "нажми", ""
    else:
        who, verb, whom = ", ".join(names), "нажмите", " каждому"
    return (
        f"👋 {who}, чтобы писать в чат, {verb} «{CARD_BUTTON}»: бот задаст{whom} один вопрос в личке.\n\n"
        f"⏱ На это {duration(minutes)}, потом бот уберёт из чата."
    )


def ask_in_chat_text(chat_title: str, answer: str, minutes_left: int) -> str:
    return (
        f"🔐 Проверка для чата <b>{html.escape(chat_title)}</b>\n\n"
        f"Нажми на <b>{NAMES[answer].upper()}</b>, и сможешь писать в чате.\n\n"
        f"⏱ Осталось {duration(minutes_left)}."
    )


def unmuted_text(chat_title: str, link: str | None) -> str:
    title = html.escape(chat_title)
    where = f'<a href="{html.escape(link)}">{title}</a>' if link else f"<b>{title}</b>"
    return f"✅ Готово, теперь можно писать в {where}!"


def removed_text(chat_title: str, *, expired: bool, removed: bool, may_return: bool) -> str:
    """Out of tries or time; `removed` and `may_return` say how far the removal got."""
    title = html.escape(chat_title)
    why = f"Время на проверку в <b>{title}</b> вышло" if expired else f"Проверка для <b>{title}</b> не пройдена"
    if not removed:
        return f"{why}: писать в чате пока нельзя, дальше решат админы чата."
    return f"{why}, бот убрал тебя из чата." + (" Можно вступить ещё раз." if may_return else "")


def no_longer_needed_text(chat_title: str) -> str:
    return f"Проверка для чата <b>{html.escape(chat_title)}</b> больше не нужна."
