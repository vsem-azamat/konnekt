"""What a mute takes away and what an unmute gives back.

`!mute` and the control plane's `mute_user` used to spell their own sets, and
both still sent `can_send_media_messages` after Telegram had split it into six
fields, so the two mutes differed and neither named what it meant to deny.
"""

from aiogram import Bot
from aiogram.types import ChatPermissions

MUTED = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    # Added in Bot API 10.0; muting without it leaves the user able to keep
    # reacting to messages.
    can_react_to_messages=False,
)


async def chat_defaults(bot: Bot, chat_id: int) -> ChatPermissions:
    """The permissions every member of the chat has, which an unmute restores.

    Only getChat carries them; the chat inside a message update never does.
    Restoring the chat's own set rather than allowing everything keeps a chat
    that forbids polls to all from handing them back to whoever was muted.
    """
    permissions = (await bot.get_chat(chat_id)).permissions
    if permissions is None:
        raise RuntimeError(f"getChat returned no default permissions for {chat_id}")
    return permissions
