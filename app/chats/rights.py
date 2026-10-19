"""The administrator rights the bot asks for in a chat.

Owned here rather than by the bot's profile: the chat audit holds every chat
to them, and the audit runs from the web API and the control plane too.
"""

from aiogram.types import ChatAdministratorRights

# What the bot asks for when somebody adds it as an administrator: everything a
# group administrator can hold, by the owner's rule that the bot moderates with
# full rights. Two stay off: anonymity, and appointing administrators, which
# would let a leaked token hand anybody the chat. Who may *use* the bot's power
# is decided by the bot (super admins, admin_chats), never by these rights.
DEFAULT_ADMIN_RIGHTS = ChatAdministratorRights(
    is_anonymous=False,
    can_manage_chat=True,
    can_delete_messages=True,
    can_manage_video_chats=True,
    can_restrict_members=True,
    can_promote_members=False,
    can_change_info=True,
    can_invite_users=True,
    can_post_stories=True,
    can_edit_stories=True,
    can_delete_stories=True,
    can_pin_messages=True,
    can_manage_topics=True,
    can_manage_tags=True,
)
