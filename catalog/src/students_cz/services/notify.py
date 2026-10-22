"""Reaching someone whose app is closed.

Every notification here answers something the recipient started — they posted a
request, or they answered one — so this is not the announcement channel and
deliberately does not consult `unsubscribed_at`: that opts out of us writing
unprompted, not out of being told that the thing you asked for happened.

The one exception is `tell_of_request`: a request somebody else posted is
news the helper did not ask for, so whoever sends it honours that opt-out and
the helper's own switch. See services/request_alerts.py.

Nothing in here may raise. A notification is a side effect of an action that has
already been committed; if Telegram is down, the response was still recorded and
the person will see it in the app.
"""

import asyncio
import logging
from dataclasses import dataclass
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    WebAppInfo,
)

from students_cz.bot.texts import OPEN_APP, OWNER_OPEN_CONSOLE, VIEW_REQUEST, pick
from students_cz.core.metrics import NOTIFICATIONS
from students_cz.db.models import User
from students_cz.db.models.enums import UiLang
from students_cz.db.session import get_sessionmaker
from students_cz.services.people import mark_unreachable

log = logging.getLogger("students_cz.notify")

# Telegram occasionally takes seconds to answer. The caller is a background
# task, but an unbounded wait still leaks a task per stuck send.
SEND_TIMEOUT = 10.0


def _web_app_button(text: str, url: str | None) -> InlineKeyboardMarkup | None:
    """One button that opens the Mini App at `url`, when that is https.

    A web_app button requires an https URL; during local development there is
    none, and a notification without a button is better than a failed send.
    """
    if not url or not url.startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]]
    )


def _keyboard(lang: UiLang, app_url: str | None) -> InlineKeyboardMarkup | None:
    """The app, in the recipient's language."""
    return _web_app_button(pick(OPEN_APP, lang), app_url)


def _console_keyboard(app_url: str | None) -> InlineKeyboardMarkup | None:
    """The console's catalog screen, in Russian like the ping itself."""
    url = f"{app_url.rstrip('/')}/console/catalog" if app_url else None
    return _web_app_button(OWNER_OPEN_CONSOLE, url)


def _incoming_keyboard(
    lang: UiLang, app_url: str | None, request_id: int
) -> InlineKeyboardMarkup | None:
    """The helper's incoming requests, with this one open to answer."""
    url = (
        f"{app_url.rstrip('/')}/mine?tab=incoming&request={request_id}"
        if app_url
        else None
    )
    return _web_app_button(pick(VIEW_REQUEST, lang), url)


@dataclass(frozen=True)
class Recipient:
    """Everything a notification needs to know about a person.

    A snapshot, taken while the session that loaded them is still open. The
    send happens in a background task, which runs after the response and
    therefore after the request's transaction has closed — so a task holding
    the ORM row itself would be reading a detached object, and works only for
    as long as nothing expires it. That is a dependency on
    `expire_on_commit=False` that nothing states and a `MissingGreenlet` at the
    end of it.

    `reachable` is decided here rather than at the send, for the same reason:
    it is a fact about the row, and the row is only trustworthy now.
    """

    tg_id: int
    lang: UiLang
    reachable: bool

    @classmethod
    def of(cls, user: User) -> "Recipient":
        """Take the snapshot, and with it the decision about writing at all.

        `bot_started_at`, not only `bot_can_message`: the latter defaults to
        true for every row including someone who opened the app without
        letting the bot write to them — `bot_started_at` is set only when
        initData says they did. Telegram answers that send with
        a 403, which `tell` reads as "blocked" — so the notification is lost
        *and* the person is recorded as having blocked a bot they never met.

        `unsubscribed_at` is deliberately not consulted. It opts out of us
        writing unprompted; every message that goes through here is the answer
        to something the recipient set in motion.
        """
        return cls(
            tg_id=user.tg_id,
            lang=user.ui_lang,
            reachable=user.bot_started_at is not None and user.bot_can_message,
        )


class Notifier:
    """Whether a person can be written to, and the writing.

    A dependency rather than something a handler assembles for itself. What a
    route needs in order to notify — a bot, and the address the app lives at —
    is decided once when the process starts, and a route that reaches into
    `app.state` for it is a route that has to decide what to do when it is not
    there. There is one answer to that and it belongs here.

    A notifier with no bot is a working notifier that delivers nothing. That is
    how the API runs locally and under test, and it must not be a branch every
    caller remembers separately.
    """

    def __init__(
        self,
        bot: Bot | None,
        app_url: str | None = None,
        *,
        owner_tg_id: int | None = None,
    ) -> None:
        self._bot = bot
        self._app_url = app_url
        self._owner_tg_id = owner_tg_id

    async def tell(self, recipient: Recipient, text: str) -> bool:
        """Send, if this person can be sent to. Returns whether it arrived.

        A `Recipient` and not a `User`: this runs after the response, when the
        session is gone. Whoever queues it takes the snapshot first, which is
        also where the decision about writing at all was made.
        """
        if not recipient.reachable:
            return False
        return await tell(
            self._bot,
            tg_id=recipient.tg_id,
            text=text,
            lang=recipient.lang,
            app_url=self._app_url,
        )

    async def tell_of_request(
        self, recipient: Recipient, text: str, request_id: int
    ) -> bool:
        """Tell a helper about somebody else's request, with a button to it.

        Unlike the two around it this answers nothing the helper did, which is
        why the caller weighs more than `reachable` before getting here: see
        services/request_alerts.py.
        """
        if not recipient.reachable:
            return False
        return await tell(
            self._bot,
            tg_id=recipient.tg_id,
            text=text,
            lang=recipient.lang,
            keyboard=_incoming_keyboard(recipient.lang, self._app_url, request_id),
        )

    async def tell_owner(self, text: str) -> bool:
        """Say that something happened, to whoever runs this. Once.

        A different kind of message from the two above and kept apart from
        them: those answer something the recipient set in motion, this one
        reports on the catalog to one address that no screen chose. There is
        nobody to consult about language and nothing to opt out of; its one
        button opens the console — see docs/architecture.md.

        Off unless `OWNER_TG_ID` names somebody, which is how it runs
        everywhere but production. Like every notification here it cannot fail
        the action it follows: the send is already guarded, and no owner is
        `False` rather than a raise.
        """
        if self._owner_tg_id is None:
            return False
        return await tell(
            self._bot,
            tg_id=self._owner_tg_id,
            text=text,
            lang=UiLang.RU,
            keyboard=_console_keyboard(self._app_url),
        )


async def tell(
    bot: Bot | None,
    *,
    tg_id: int,
    text: str,
    lang: UiLang,
    app_url: str | None = None,
    keyboard: InlineKeyboardMarkup | None = None,
) -> bool:
    """Send one message. Returns whether it arrived.

    The button is `keyboard` when one is given, else the one that opens the app
    at `app_url`, else none.

    `bot` is None when the API runs without a token, which is how it runs
    locally — so every caller works unchanged with notifications simply not
    happening.
    """
    if bot is None:
        log.debug("no bot configured; not notifying")
        return False

    try:
        await asyncio.wait_for(
            bot.send_message(
                chat_id=tg_id,
                text=text,
                # The caller's own keyboard, else the one that opens the app.
                reply_markup=keyboard or _keyboard(lang, app_url),
                # These are short and self-contained; a link preview would be
                # the only thing in the message with a picture. The options
                # object rather than disable_web_page_preview, which aiogram
                # keeps only as a deprecated alias.
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            ),
            timeout=SEND_TIMEOUT,
        )
    except TelegramForbiddenError as exc:
        # Blocked, or never started the bot. An answer, not a failure: recorded
        # so nothing tries again and finds out the same way.
        async with get_sessionmaker()() as session:
            await mark_unreachable(session, tg_id, str(exc))
            await session.commit()
        NOTIFICATIONS.labels(outcome="blocked").inc()
        return False
    except TelegramRetryAfter as exc:
        # Not retried here. This is a single message to a single person, and
        # holding a background task open for the flood-wait window to deliver
        # something the app already shows is not worth it.
        # No id: the people written to are the audience, whose ids stay out of the logs.
        log.warning("flood wait %ss notifying", exc.retry_after)
        NOTIFICATIONS.labels(outcome="flood").inc()
        return False
    except Exception as exc:
        # Includes the timeout above: asyncio.TimeoutError is TimeoutError is
        # an Exception. Everything here is "the message did not arrive", and
        # none of it is worth failing the caller over.
        log.warning("could not notify: %s", type(exc).__name__)
        NOTIFICATIONS.labels(outcome="failed").inc()
        return False
    NOTIFICATIONS.labels(outcome="sent").inc()
    return True


def quote(value: str, limit: int = 300) -> str:
    """Prepare user-written text for an HTML message.

    Escaped, because the bot sends HTML and someone's request may legitimately
    contain "<3" or an ampersand; truncated, because a notification is a
    summary and Telegram rejects a message over 4096 characters outright.
    """
    collapsed = " ".join(value.split())
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1].rstrip() + "…"
    return escape(collapsed)
