"""What a mute takes away and what an unmute gives back.

`!mute` and the control plane's `mute_user` used to spell their own sets, and
both still sent `can_send_media_messages` after Telegram had split it into six
fields, so the two mutes differed and neither named what it meant to deny.
"""

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


# The documented way to lift a restriction: every permission True. A member is
# never allowed more than the chat allows everyone, so this hands back nothing
# the chat forbids. Restoring the chat's defaults instead would keep a per-member
# restriction that goes stale the moment the chat's own settings change.
UNMUTED = ChatPermissions(**dict.fromkeys(ChatPermissions.model_fields, True))
