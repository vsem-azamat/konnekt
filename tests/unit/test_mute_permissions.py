"""The muted permission set, shared by `!mute` and the control plane's `mute_user`."""

from aiogram.types import ChatPermissions
from app.moderation.mute_permissions import MUTED


def test_muted_denies_every_send_permission_the_api_has() -> None:
    """A field the API added later is a hole in the mute until it is listed here."""
    send_fields = [f for f in ChatPermissions.model_fields if f.startswith("can_send_")]
    send_fields += ["can_add_web_page_previews", "can_react_to_messages"]

    assert {f: getattr(MUTED, f) for f in send_fields} == dict.fromkeys(send_fields, False)


def test_muted_carries_no_retired_field() -> None:
    assert "can_send_media_messages" not in MUTED.model_dump(exclude_none=True)
