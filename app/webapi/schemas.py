"""Pydantic response schemas for the web UI API."""

from __future__ import annotations

import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import SpamVerdict

ChatResourceStatus = Literal["discovered", "approved", "observed", "external", "disabled"]

# What may be stored as a chat's public link.
#
# Whatever goes in this column is rendered as an `href` on a page anybody can
# open, so the shape is checked at the boundary rather than trusted because an
# admin typed it. Telegram has three forms — a public username, a modern invite
# hash, and the older joinchat one — and anything else is not a chat link. A
# `javascript:` URL is the reason this is a whitelist and not a "does it look
# like a URL" check.
PUBLIC_LINK = re.compile(
    r"^https://t\.me/(?:\+[\w-]{10,}|joinchat/[\w-]{10,}|[A-Za-z][\w]{3,31})$",
)


class PublicCatalogItem(BaseModel):
    """What a stranger may know about a chat.

    The shape is the safety rather than any check downstream: there is no
    Telegram id here, no moderation state, nothing about who is in the room. A
    public page cannot leak a field this model does not carry, however
    carelessly it is written. How many are in the room is here: the app shows it
    before a stranger leaves for the chat, and Telegram shows the same number on
    the chat's own public page.

    ``group`` is the section's title: the parent chat's for a chat under one
    ("ČVUT" above "ČVUT FIT"), the chat's own for a chat others sit under, and
    none for a loose chat — so the catalogue reads by university rather than as
    forty-five rows.
    """

    title: str
    link: str
    group: str | None = None
    # The university's code in the catalog, the group's own: every app user
    # can read the catalog's taxonomy, and it lets the app put a student's first.
    institution: str | None = None
    # "unknown" is a real answer, not a missing one: it says the recording
    # behind the other three values is too short to stand on. A page shows
    # nothing for it rather than guessing.
    activity: Literal["unknown", "quiet", "active", "busy"]
    # The newest snapshot the bot wrote; None when it never measured the chat,
    # which is not the same claim as an empty room.
    member_count: int | None = None
    # Telegram's topics, so the preview can say the chat is split into them.
    is_forum: bool = False
    # Somebody else's chat, listed so a student can find it. The one thing a
    # stranger learns about how a chat is run, because it is the one thing they
    # need: the rules in there are not ours. A chat we only observe is still
    # ours and is not marked.
    external: bool = False


class PublicReachGroup(BaseModel):
    """One university's worth of catalogue, as an advertiser would ask about it.

    Aggregated per group: a sum is what somebody buying a placement is
    actually asking for. Each room's own size is on the catalogue.
    """

    name: str
    chats: int
    members: int


class PublicReach(BaseModel):
    """How far a post across the published catalogue would carry.

    ``measured_chats`` is the honesty of ``members``: the counts come from
    snapshots the userbot managed to take, and Telegram does not answer for
    every chat every time. When it is lower than ``chats``, the total is a sum
    over part of the catalogue and the page has to say so — a reach figure that
    quietly covers two thirds of what it names is the kind of number somebody
    would pay against.
    """

    chats: int
    members: int
    measured_chats: int
    groups: list[PublicReachGroup]


class ChatRead(BaseModel):
    """List-page view of a managed chat."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    resource_status: ChatResourceStatus
    is_forum: bool
    is_welcome_enabled: bool
    is_captcha_enabled: bool
    is_service_cleanup_enabled: bool = True
    parent_chat_id: int | None = None
    relation_notes: str | None = None
    # Set means the chat is in the public catalogue. Shown here so the console
    # can say which chats are not, rather than leaving it to be discovered by
    # looking at the public page and counting.
    public_link: str | None = None
    institution_code: str | None = None
    member_count: int | None = None  # last recorded snapshot; None when never measured
    has_photo: bool = False
    last_synced_at: datetime.datetime | None = None
    created_at: datetime.datetime


_INSTITUTION_CODE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


class ChatUpdate(BaseModel):
    """Editable per-chat moderation settings. All fields optional — only the
    keys present in the body are applied (``exclude_unset``)."""

    title: str | None = None
    resource_status: ChatResourceStatus | None = None
    welcome_message: str | None = None
    is_welcome_enabled: bool | None = None
    is_captcha_enabled: bool | None = None
    is_service_cleanup_enabled: bool | None = None
    time_delete: int | None = None
    parent_chat_id: int | None = None
    relation_notes: str | None = None
    # Setting this publishes the chat; clearing it takes it down. Nothing else
    # does either, which is why it is one field and not a field plus a switch.
    public_link: str | None = None
    # the catalog's code for a university; empty clears it.
    institution_code: str | None = None

    @field_validator("institution_code")
    @classmethod
    def _check_institution_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = value.strip().lower()
        if not code:
            return None
        if not _INSTITUTION_CODE.fullmatch(code):
            raise ValueError("An institution code is a short latin slug, e.g. cvut")
        return code

    @field_validator("public_link")
    @classmethod
    def _check_public_link(cls, value: str | None) -> str | None:
        """Reject anything that is not a Telegram chat link.

        A cleared field arrives from a form as an empty string, which must mean
        "take it down" rather than "publish with no link" — the catalogue keys
        off the column being set, so an empty string would list a chat whose
        card leads nowhere.
        """
        if value is None:
            return None
        link = value.strip()
        if not link:
            return None
        if not PUBLIC_LINK.match(link):
            raise ValueError("Public link must be a Telegram chat link, e.g. https://t.me/cvut_fit")
        return link


# A public username, the one form of chat link Telegram resolves for a bot that
# is not in the chat; an invite opens only for whoever joins through it. Taken
# as people paste it: "@name", "name", "t.me/name" or the full link.
_USERNAME = re.compile(r"^(?:@|(?:https?://)?(?:t\.me|telegram\.me)/)?(?P<username>[A-Za-z][\w]{3,31})/?$")


def username_of(link: str) -> str | None:
    """The username a pasted link names, or None when it names no public chat."""
    match = _USERNAME.match(link.strip())
    return match["username"] if match else None


class ExternalChatCreate(BaseModel):
    """A chat the bot is not in, named by the link a student would follow.

    Checked in the route rather than here, so that a refusal carries the same
    plain code as the others the console has to tell apart.
    """

    public_link: str = Field(max_length=200)


class ChatNode(BaseModel):
    """A chat listed under its parent on the chat's own screen."""

    id: int
    title: str | None
    relation_notes: str | None = None
    has_photo: bool = False
    children: list[ChatNode] = []


class HeatmapCell(BaseModel):
    """One cell of the weekday×hour chat activity grid.

    weekday: 0 = Monday, 6 = Sunday (matches datetime.weekday()).
    hour: 0..23, UTC.
    count: number of messages recorded in `messages` table for that cell
           over the lookback window.
    """

    weekday: int
    hour: int
    count: int


class MemberSnapshotPoint(BaseModel):
    captured_at: datetime.datetime
    member_count: int


class ChatSender(BaseModel):
    """Recent sender in a chat — used for moderation actions."""

    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    message_count: int
    last_seen: datetime.datetime
    blocked: bool


class ChatDetail(ChatRead):
    """Full chat payload — adds heatmap grid + member-snapshot series + relationships."""

    welcome_message: str | None
    time_delete: int
    modified_at: datetime.datetime
    heatmap: list[HeatmapCell]
    member_snapshots: list[MemberSnapshotPoint]
    children: list[ChatNode] = []
    spam_pings: list[SpamPingRead] = []
    recent_senders: list[ChatSender] = []


class UserBlockRequest(BaseModel):
    """Body for POST /api/users/{id}/block. Set ``revoke_messages`` to also
    delete the user's recorded messages from all known chats."""

    revoke_messages: bool = False


class BlockedUserRead(BaseModel):
    """One entry of the global blacklist, as /blacklist shows it in the bot."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    # When the row last changed. Not when the block went on: a rename or a
    # repeated block changes it too, and there is no column for the block.
    changed_at: datetime.datetime


class UserBlockResponse(BaseModel):
    user_id: int
    blocked: bool
    message: str
    # The approved chats where Telegram refused, and how many it took in:
    # none of either means there was no approved chat to act in.
    failed_chats: list[int] = []
    banned_in: int = 0


class AdminSessionRead(BaseModel):
    """Active admin session row — used by /settings to list logins."""

    id: str
    user_id: int
    created_at: datetime.datetime
    last_seen_at: datetime.datetime
    expires_at: datetime.datetime
    user_agent: str | None
    ip: str | None
    is_current: bool = False


class FeatureFlagRead(BaseModel):
    """One feature flag — surfaced as a badge in /settings."""

    name: str
    enabled: bool
    source: str = "env"


class SystemStatus(BaseModel):
    """Read-only operational status for the /settings system card."""

    super_admin_ids: list[int]
    publish_bot_ready: bool
    allowed_origins: list[str]
    session_ttl_days: int
    feature_flags: list[FeatureFlagRead]


ChatNode.model_rebuild()


class ChatHeatmapSummary(BaseModel):
    """Home tile: one of the busiest chats of the last 24 hours.

    Its messages by UTC hour of day over those 24 hours, not the week's grid,
    to keep the home payload small; the full grid lives on /chats/:id.
    """

    chat_id: int
    title: str | None
    total_messages: int
    hours: list[int]


class MembersDeltaEntry(BaseModel):
    """Home tile: members Δ over a window.

    delta_24h / delta_7d: None when no baseline snapshot exists yet
    (first run, or snapshot history too short).
    """

    chat_id: int
    title: str | None
    current: int | None
    delta_24h: int | None
    delta_7d: int | None


class SpamPingRead(BaseModel):
    """One ad-detection event surfaced to the UI."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    chat_id: int
    chat_title: str | None = None
    user_id: int
    # The author as the bot last saw them; none of it for somebody never stored.
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    blocked: bool = False
    message_id: int
    kind: str
    matches: list[str]
    snippet: str | None
    detected_at: datetime.datetime
    verdict: SpamVerdict | None = None


class SpamReviewRequest(BaseModel):
    """Body for POST /api/spam/pings/{id}/review. «ad» is a ban's to write."""

    verdict: Literal[SpamVerdict.DONE, SpamVerdict.NOT_AD]


class SpamQueueCount(BaseModel):
    count: int


class SpamPingsSummary(BaseModel):
    """Home tile: rolling spam-ping counters + recent samples."""

    count_24h: int
    count_7d: int
    # Hits nobody answered yet, of any age: the console's ads queue.
    unreviewed: int = 0
    recent: list[SpamPingRead] = []


class HomeStats(BaseModel):
    """Aggregated response backing the home dashboard's live tiles.

    Keeps home to one round-trip; skeleton tiles are FE-only and don't
    appear here.
    """

    chat_heatmap: list[ChatHeatmapSummary] = []
    members_delta: list[MembersDeltaEntry] = []
    spam_pings: SpamPingsSummary = SpamPingsSummary(count_24h=0, count_7d=0, recent=[])


class WebAppLoginPayload(BaseModel):
    """The opaque `initData` string Telegram hands the Mini App.

    Passed through untouched: it is a signed query string, and any parsing on
    the way in would have to be undone byte for byte to check the signature.
    """

    init_data: str


class AuthMeResponse(BaseModel):
    user_id: int
    is_authenticated: bool = True


AudienceStatus = Literal["reachable", "never_started", "blocked", "opted_out"]


class AudienceLanguage(BaseModel):
    code: str
    count: int


class AudienceSummary(BaseModel):
    """The top of the Audience page: how many, who may be written to, where they came from."""

    total: int
    # By status, about the main bot: see app.audience.views.
    reach: dict[AudienceStatus, int]
    # By the touchpoint each person used first.
    first_touch: dict[str, int]
    # New people per seven days, oldest first, the last entry ending now.
    new_by_week: list[int]
    new_this_week: int
    languages: list[AudienceLanguage]


class AudienceMemberRead(BaseModel):
    """One person in the audience list. Only what Telegram itself tells about them."""

    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    status: AudienceStatus
    touchpoints: list[str]


class AudiencePage(BaseModel):
    total: int
    items: list[AudienceMemberRead]
    # Pass as `cursor` for the next page; None on the last one.
    next: str | None


class AudienceTouchRead(BaseModel):
    touchpoint: str
    first_at: datetime.datetime
    last_at: datetime.datetime
    count: int


class AudienceReachRead(BaseModel):
    bot: str
    started_at: datetime.datetime | None
    blocked_at: datetime.datetime | None


class AudiencePersonRead(BaseModel):
    """One person's card: profile, every touchpoint, and whether each bot may write."""

    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    status: AudienceStatus
    is_premium: bool
    source: str | None
    opted_out_at: datetime.datetime | None
    touches: list[AudienceTouchRead]
    reach: list[AudienceReachRead]
