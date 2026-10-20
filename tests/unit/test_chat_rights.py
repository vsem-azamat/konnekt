"""The bot asks for every group right Telegram has, save two.

Telegram adds rights as the Bot API grows. aiogram makes some of them required,
and a required one the bot does not name fails at import on its own; an
optional one would be left out in silence. This holds every right but the
channels' to an answer.
"""

from aiogram.types import ChatAdministratorRights
from app.chats.rights import DEFAULT_ADMIN_RIGHTS

# Anonymity, and appointing administrators: a leaked token must not be able to
# hand anybody the chat.
WITHHELD = {"is_anonymous", "can_promote_members"}
# Rights that exist only in channels, which the bot does not moderate.
CHANNEL_ONLY = {"can_post_messages", "can_edit_messages", "can_manage_direct_messages"}


def test_every_group_right_but_two_is_asked_for() -> None:
    group_rights = set(ChatAdministratorRights.model_fields) - CHANNEL_ONLY
    asked = {name for name in group_rights if getattr(DEFAULT_ADMIN_RIGHTS, name) is True}

    assert asked == group_rights - WITHHELD


def test_no_group_right_is_left_unanswered() -> None:
    """None means "not mentioned", and Telegram reads that as off."""
    unanswered = {
        name
        for name in set(ChatAdministratorRights.model_fields) - CHANNEL_ONLY
        if getattr(DEFAULT_ADMIN_RIGHTS, name) is None
    }

    assert unanswered == set()
