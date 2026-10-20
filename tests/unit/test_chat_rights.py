"""The bot asks for every group right Telegram has, save two.

Telegram adds rights as the Bot API grows, and aiogram makes each new one a
required field: 3.31 added `can_send_welcome_messages`, and until the bot named
it, nothing that imported the rights could even start.
"""

from aiogram.types import ChatAdministratorRights
from app.chats.rights import DEFAULT_ADMIN_RIGHTS

# Anonymity, and appointing administrators: a leaked token must not be able to
# hand anybody the chat.
WITHHELD = {"is_anonymous", "can_promote_members"}


def test_every_group_right_but_two_is_asked_for() -> None:
    # Required fields are the ones a group administrator holds; the optional
    # ones are for channels and default to None.
    group_rights = {name for name, field in ChatAdministratorRights.model_fields.items() if field.is_required()}
    asked = {name for name in group_rights if getattr(DEFAULT_ADMIN_RIGHTS, name) is True}

    assert asked == group_rights - WITHHELD
