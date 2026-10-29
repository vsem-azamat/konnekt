"""What the bot says, in the language the recipient chose.

The mini app has a translation catalog; the bot cannot use it, because these
strings are produced by the server while the recipient's app is closed — which
is the entire reason to send them. Kept as plain dictionaries rather than
another gettext setup: there are a handful of strings, and a missing key here
should be a loud KeyError in a test, not a silent fallback in production.

Values are HTML — the bot is built with parse_mode=HTML — so anything
interpolated has to be escaped by the caller.
"""

from students_cz.db.models.enums import UiLang

# The button under a notification. Opening the app is the only action any of
# these messages asks for, so there is exactly one label per language.
OPEN_APP: dict[UiLang, str] = {
    UiLang.RU: "Открыть",
    UiLang.CS: "Otevřít",
    UiLang.EN: "Open",
    UiLang.UK: "Відкрити",
}

# Someone answered a request you posted.
NEW_RESPONSE: dict[UiLang, str] = {
    UiLang.RU: (
        "<b>Отклик на твою заявку</b>\n"
        "{topic}\n\n"
        "{helper} готов помочь{price}.\n"
        "«{message}»"
    ),
    UiLang.CS: (
        "<b>Odpověď na tvůj inzerát</b>\n"
        "{topic}\n\n"
        "{helper} nabízí pomoc{price}.\n"
        "„{message}“"
    ),
    UiLang.EN: (
        "<b>Someone answered your request</b>\n"
        "{topic}\n\n"
        "{helper} can help{price}.\n"
        "“{message}”"
    ),
    UiLang.UK: (
        "<b>Відгук на твою заявку</b>\n"
        "{topic}\n\n"
        "{helper} готовий допомогти{price}.\n"
        "«{message}»"
    ),
}

# The price clause, appended to the line above. Separate because a response
# without a price must not leave a dangling "for" in the sentence.
FOR_PRICE: dict[UiLang, str] = {
    UiLang.RU: " за {price}",
    UiLang.CS: " za {price}",
    UiLang.EN: " for {price}",
    UiLang.UK: " за {price}",
}

# The student picked your answer.
#
# It does not tell the helper to write first. The conversation happens in
# Telegram and we do not host it, so the helper can only start it if the
# student has a public username — which most do not. The student always can,
# because answering a request requires one. `{contact}` fills in only when
# the helper genuinely has somewhere to write.
RESPONSE_ACCEPTED: dict[UiLang, str] = {
    UiLang.RU: ("<b>Твой отклик приняли</b>\n{topic}\n\n{student} выбрал тебя.{contact}"),
    UiLang.CS: (
        "<b>Tvoje nabídka byla přijata</b>\n{topic}\n\n{student} si tě vybral.{contact}"
    ),
    UiLang.EN: (
        "<b>Your answer was accepted</b>\n{topic}\n\n{student} chose you.{contact}"
    ),
    UiLang.UK: ("<b>Твій відгук прийняли</b>\n{topic}\n\n{student} обрав тебе.{contact}"),
}

# Appended above when the student has a public username, so the helper does
# not have to wait to be written to.
WRITE_TO: dict[UiLang, str] = {
    UiLang.RU: " Написать: @{username}",
    UiLang.CS: " Napsat: @{username}",
    UiLang.EN: " Write to them: @{username}",
    UiLang.UK: " Написати: @{username}",
}

# And when they do not: the student has the button, so this is the honest
# version rather than an instruction the helper cannot follow.
WAIT_FOR_MESSAGE: dict[UiLang, str] = {
    UiLang.RU: " Он напишет сам — ответь, когда придёт сообщение.",
    UiLang.CS: " Ozve se sám — odpověz, až zpráva přijde.",
    UiLang.EN: " They will write to you — answer when the message arrives.",
    UiLang.UK: " Він напише сам — відповідай, коли надійде повідомлення.",
}


# Somebody posted a request this helper's services cover. The only message
# here that answers nothing the recipient did, so it says how to stop it; the
# switch is in «О себе и как работаю», and services/request_alerts.py keeps it rare.
NEW_REQUEST_FOR_HELPER: dict[UiLang, str] = {
    UiLang.RU: (
        "<b>Новая заявка по твоей услуге</b>\n"
        "{topic}\n"
        "«{text}»{budget}\n\n"
        "Выключить такие сообщения можно в «О себе и как работаю»."
    ),
    UiLang.CS: (
        "<b>Nová poptávka k tvé službě</b>\n"
        "{topic}\n"
        "„{text}“{budget}\n\n"
        "Tyto zprávy vypneš v „O mně a jak pracuji“."
    ),
    UiLang.EN: (
        "<b>A new request for your service</b>\n"
        "{topic}\n"
        "“{text}”{budget}\n\n"
        "You can turn these messages off in “About me and how I work”."
    ),
    UiLang.UK: (
        "<b>Нова заявка на твою послугу</b>\n"
        "{topic}\n"
        "«{text}»{budget}\n\n"
        "Вимкнути такі повідомлення можна в «Про себе і як працюю»."
    ),
}

# The budget line, on its own line under the request. Absent when the author
# named no budget.
BUDGET_UP_TO: dict[UiLang, str] = {
    UiLang.RU: "\nБюджет до {amount}",
    UiLang.CS: "\nRozpočet do {amount}",
    UiLang.EN: "\nBudget up to {amount}",
    UiLang.UK: "\nБюджет до {amount}",
}

# Its button, which opens the request in the helper's incoming list.
VIEW_REQUEST: dict[UiLang, str] = {
    UiLang.RU: "Посмотреть заявку",
    UiLang.CS: "Zobrazit poptávku",
    UiLang.EN: "View request",
    UiLang.UK: "Переглянути заявку",
}

# What the owner is told, the ping's button and the two pings with their
# fillers, and the only strings here with no table behind them. Nobody reading
# these chose a language: they go to one address, `OWNER_TG_ID`, and they
# report on the catalog rather than saying anything to a person who is using
# it. See docs/architecture.md.
OWNER_OPEN_CONSOLE = "Открыть в консоли"
OWNER_NEW_HELPER = "<b>Новая анкета</b>\n{name}\n{services}"
OWNER_NEW_REQUEST = "<b>Новая заявка</b>\n{topic}\n«{text}»"
OWNER_NO_SERVICES = "без услуг"
OWNER_NOTHING_PARSED = "ничего не разобрали"


def pick(table: dict[UiLang, str], lang: UiLang) -> str:
    """Read a string, falling back to Russian for a language we have not written.

    A new UiLang member should not be able to raise inside a notification and
    take the request that triggered it with it.
    """
    return table.get(lang) or table[UiLang.RU]
