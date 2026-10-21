"""A member asks the moderators to look at a message.

Mechanical: the bot builds a summary with links back to the original and sends
it to the report chat. Nothing is decided here.

There used to be two of these — `/report` reached one implementation and
`!report` another, in different files, producing different summaries from the
same event. This is the one that survived, because it carries the target's id
and a link straight to the message, which is what an administrator needs before
they can act.
"""

from aiogram import Bot, types

from app.core.config import settings
from app.core.logging import get_logger
from app.core.text import escape_html

logger = get_logger("moderation.report")

# Long enough to judge a message by, short enough that a wall of text cannot
# push the links off an administrator's screen.
_SNIPPET_LIMIT = 500


def _chat_link(chat: types.Chat) -> str:
    if chat.username:
        return f"https://t.me/{chat.username}"
    raw_id = str(chat.id)
    return f"https://t.me/c/{raw_id[4:] if raw_id.startswith('-100') else raw_id.lstrip('-')}"


def _message_link(message: types.Message) -> str:
    return f"{_chat_link(message.chat)}/{message.message_id}"


def _display_name(user: types.User) -> str:
    return user.full_name or user.username or f"User {user.id}"


async def report_to_moderators(
    bot: Bot, reporter: types.User, reported: types.User, reported_message: types.Message
) -> None:
    """Send one summary to the report chat.

    Everything a person typed goes through `escape_html`. The reported text is
    the whole reason this function exists, and it is written by exactly the
    person somebody is complaining about — markup they control must not survive
    into a message the administrators read.
    """
    snippet = reported_message.text or reported_message.caption or "[нет текста]"
    if len(snippet) > _SNIPPET_LIMIT:
        snippet = snippet[:_SNIPPET_LIMIT] + "…"

    chat = reported_message.chat
    chat_title = escape_html(chat.title) if chat.title else str(chat.id)
    username_part = f" (@{escape_html(reported.username)})" if reported.username else ""

    summary = (
        "📢 <b>Жалоба</b>\n\n"
        f'💬 Чат: <a href="{_chat_link(chat)}">{chat_title}</a>\n'
        f'👤 На кого: <a href="tg://user?id={reported.id}">{escape_html(_display_name(reported))}</a>'
        f"{username_part}\n"
        f"🆔 ID: <code>{reported.id}</code>\n"
        f"📝 От кого: {escape_html(_display_name(reporter))}\n"
        f'🔗 <a href="{_message_link(reported_message)}">Перейти к сообщению</a>\n\n'
        f"📄 Сообщение:\n<blockquote>{escape_html(snippet)}</blockquote>"
    )

    try:
        await bot.send_message(chat_id=settings.admin.default_report_chat_id, text=summary)
    except Exception as err:
        # The member is told their report went through either way. Telling them
        # otherwise would ask them to do something about a failure that is ours.
        logger.error("report_forward_failed", error=str(err), exc_info=True, target_user_id=reported.id)
