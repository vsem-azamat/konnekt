"""Chats — list + detail endpoints.

Reads, mostly from our own tables. The heatmap comes from the `messages` rows
the moderator handlers write, and member counts from the snapshots the bot
records hourly — asking Telegram once per chat per page load would be a
rate-limit waiting for a second browser tab.

The one exception is the refresh endpoint, which exists to ask.

A chat the bot has never seen carries `None` rather than a zero: not measured
and empty are different claims.
"""

from __future__ import annotations

import datetime
from typing import Annotated, cast

import aiohttp
from aiogram import Bot
from aiogram.exceptions import (
    ClientDecodeError,
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats import previews
from app.chats.avatars import sync_photo
from app.chats.invite_links import is_invite_link
from app.chats.metadata import BotNotInChatError, fetch_member_count, fetch_metadata, username_of
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import Chat, ChatMemberSnapshot, Message, User
from app.webapi.deps import (
    get_publish_bot,
    get_session,
    require_super_admin,
)
from app.webapi.schemas import (
    ChatDetail,
    ChatKind,
    ChatNode,
    ChatRead,
    ChatResourceStatus,
    ChatSender,
    ChatTopic,
    ChatUpdate,
    ExternalChatCreate,
    HeatmapCell,
    JoinMode,
    MemberSnapshotPoint,
)
from app.webapi.services import member_counts, public_answers
from app.webapi.services.spam_pings import read_pings

logger = get_logger("webapi.routes.chats")

router = APIRouter(prefix="/chats", tags=["chats"])

_HEATMAP_LOOKBACK_DAYS = 7
_HEATMAP_MAX_ROWS = 50_000
_SNAPSHOTS_LIMIT = 50
_SPAM_PINGS_LIMIT = 30
_RECENT_SENDERS_LOOKBACK_DAYS = 7
_RECENT_SENDERS_LIMIT = 25


def _resource_status(status: str) -> ChatResourceStatus:
    return cast("ChatResourceStatus", status)


def _topic(topic: str | None) -> ChatTopic | None:
    return cast("ChatTopic | None", topic)


def _join_mode(mode: str) -> JoinMode:
    return cast("JoinMode", mode)


def _kind(kind: str) -> ChatKind:
    return cast("ChatKind", kind)


def _mode_without_captcha(chat: Chat) -> str:
    """What switching the captcha off leaves, the bot's behaviour without it unchanged.

    A chat with the bot's invite link is private, and that link asked for no
    request without a captcha. Anything else may be public, whose requests come
    from its own setting and went to the admins; so does a private chat that
    asks for requests itself.
    """
    private = chat.public_link is not None and is_invite_link(chat.public_link)
    return Chat.JOIN_OPEN if private and chat.join_by_request is not True else Chat.JOIN_ADMINS


def _build_heatmap(timestamps: list[datetime.datetime]) -> list[HeatmapCell]:
    grid: dict[tuple[int, int], int] = {}
    for ts in timestamps:
        key = (ts.weekday(), ts.hour)
        grid[key] = grid.get(key, 0) + 1
    return [HeatmapCell(weekday=w, hour=h, count=c) for (w, h), c in sorted(grid.items())]


@router.get("", response_model=list[ChatRead])
async def list_chats(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin_id: Annotated[int, Depends(require_super_admin)],
) -> list[ChatRead]:
    chats = (await session.execute(select(Chat).order_by(Chat.title))).scalars().all()
    counts = await member_counts.latest_for(session, [chat.id for chat in chats])
    return [
        ChatRead(
            id=chat.id,
            title=chat.title,
            resource_status=_resource_status(chat.resource_status),
            is_forum=chat.is_forum,
            kind=_kind(chat.kind),
            is_welcome_enabled=chat.is_welcome_enabled,
            is_captcha_enabled=chat.is_captcha_enabled,
            join_mode=_join_mode(chat.join_mode),
            join_by_request=chat.join_by_request,
            is_service_cleanup_enabled=chat.is_service_cleanup_enabled,
            parent_chat_id=chat.parent_chat_id,
            relation_notes=chat.relation_notes,
            public_link=chat.public_link,
            institution_code=chat.institution_code,
            city=chat.city,
            topic=_topic(chat.topic),
            member_count=counts.get(chat.id),
            has_photo=chat.photo_file_id is not None,
            last_synced_at=chat.last_synced_at,
            created_at=chat.created_at,
        )
        for chat in chats
    ]


@router.get("/{chat_id}", response_model=ChatDetail)
async def get_chat(
    chat_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin_id: Annotated[int, Depends(require_super_admin)],
) -> ChatDetail:
    chat = (await session.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")

    since = utc_now() - datetime.timedelta(days=_HEATMAP_LOOKBACK_DAYS)
    timestamps_rows = (
        await session.execute(
            select(Message.timestamp)
            .where(Message.chat_id == chat_id)
            .where(Message.timestamp >= since)
            .limit(_HEATMAP_MAX_ROWS)
        )
    ).all()
    timestamps = [row[0] for row in timestamps_rows]

    snapshot_rows = (
        (
            await session.execute(
                select(ChatMemberSnapshot)
                .where(ChatMemberSnapshot.chat_id == chat_id)
                .order_by(ChatMemberSnapshot.captured_at.desc())
                .limit(_SNAPSHOTS_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    snapshots_ascending = list(reversed(snapshot_rows))

    member_count = await member_counts.latest(session, chat.id)

    children_rows = (
        (await session.execute(select(Chat).where(Chat.parent_chat_id == chat_id).order_by(Chat.title))).scalars().all()
    )
    children_nodes = [
        ChatNode(
            id=c.id,
            title=c.title,
            relation_notes=c.relation_notes,
            has_photo=c.photo_file_id is not None,
            children=[],
        )
        for c in children_rows
    ]

    spam_pings = await read_pings(session, chat_id=chat_id, limit=_SPAM_PINGS_LIMIT)

    senders_since = utc_now() - datetime.timedelta(days=_RECENT_SENDERS_LOOKBACK_DAYS)
    senders_rows = (
        await session.execute(
            select(
                Message.user_id,
                func.count(Message.id).label("message_count"),
                func.max(Message.timestamp).label("last_seen"),
                User.username,
                User.first_name,
                User.last_name,
                User.blocked,
            )
            .outerjoin(User, User.id == Message.user_id)
            .where(Message.chat_id == chat_id)
            .where(Message.timestamp >= senders_since)
            .group_by(Message.user_id, User.username, User.first_name, User.last_name, User.blocked)
            .order_by(func.count(Message.id).desc())
            .limit(_RECENT_SENDERS_LIMIT)
        )
    ).all()
    recent_senders = [
        ChatSender(
            user_id=r.user_id,
            username=r.username,
            first_name=r.first_name,
            last_name=r.last_name,
            message_count=int(r.message_count),
            last_seen=r.last_seen,
            blocked=bool(r.blocked) if r.blocked is not None else False,
        )
        for r in senders_rows
    ]

    return ChatDetail(
        id=chat.id,
        title=chat.title,
        resource_status=_resource_status(chat.resource_status),
        is_forum=chat.is_forum,
        kind=_kind(chat.kind),
        is_welcome_enabled=chat.is_welcome_enabled,
        is_captcha_enabled=chat.is_captcha_enabled,
        join_mode=_join_mode(chat.join_mode),
        join_by_request=chat.join_by_request,
        is_service_cleanup_enabled=chat.is_service_cleanup_enabled,
        parent_chat_id=chat.parent_chat_id,
        relation_notes=chat.relation_notes,
        public_link=chat.public_link,
        institution_code=chat.institution_code,
        city=chat.city,
        topic=_topic(chat.topic),
        member_count=member_count,
        has_photo=chat.photo_file_id is not None,
        last_synced_at=chat.last_synced_at,
        created_at=chat.created_at,
        welcome_message=chat.welcome_message,
        time_delete=chat.time_delete,
        modified_at=chat.modified_at,
        heatmap=_build_heatmap(timestamps),
        member_snapshots=[
            MemberSnapshotPoint(captured_at=s.captured_at, member_count=s.member_count) for s in snapshots_ascending
        ],
        children=children_nodes,
        spam_pings=spam_pings,
        recent_senders=recent_senders,
    )


@router.patch("/{chat_id}", response_model=ChatRead)
async def update_chat(
    chat_id: int,
    payload: ChatUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin_id: Annotated[int, Depends(require_super_admin)],
) -> ChatRead:
    chat = (await session.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")

    fields = payload.model_dump(exclude_unset=True)
    if "time_delete" in fields and fields["time_delete"] is not None and fields["time_delete"] <= 0:
        raise HTTPException(status_code=422, detail="time_delete must be positive")
    if "resource_status" in fields and fields["resource_status"] is not None:
        status: ChatResourceStatus = fields["resource_status"]
        if status not in Chat.VALID_RESOURCE_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown resource status")
        # Somebody else's channel is only listed; see Chat.KIND_CHANNEL.
        if chat.kind == Chat.KIND_CHANNEL and status not in {Chat.STATUS_EXTERNAL, Chat.STATUS_DISABLED}:
            raise HTTPException(status_code=409, detail="A channel is only ever listed as somebody else's")
        # Nor is a chat known only by its invite link; see Chat.PREVIEW_ID_CEILING.
        if chat.is_preview_only and status not in {Chat.STATUS_EXTERNAL, Chat.STATUS_DISABLED}:
            raise HTTPException(status_code=409, detail="A chat the bot cannot reach is only ever listed")
    if "parent_chat_id" in fields and fields["parent_chat_id"] == chat_id:
        raise HTTPException(status_code=422, detail="A chat cannot be its own parent")
    if "parent_chat_id" in fields and fields["parent_chat_id"] is not None:
        parent_id = fields["parent_chat_id"]
        parent_rows = (
            await session.execute(select(Chat.id, Chat.parent_chat_id).where(Chat.id.in_([chat_id, parent_id])))
        ).all()
        known_ids = {row.id for row in parent_rows}
        if parent_id not in known_ids:
            raise HTTPException(status_code=422, detail=f"Parent chat {parent_id} not found")

        all_links = (await session.execute(select(Chat.id, Chat.parent_chat_id))).all()
        parent_by_id = {row.id: row.parent_chat_id for row in all_links}
        parent_by_id[chat_id] = parent_id
        seen: set[int] = set()
        cursor = parent_id
        while cursor is not None:
            if cursor == chat_id or cursor in seen:
                raise HTTPException(status_code=422, detail="Chat hierarchy cannot contain cycles")
            seen.add(cursor)
            cursor = parent_by_id.get(cursor)

        # Both lists group one level deep; see docs/invariants.md.
        if parent_by_id.get(parent_id) is not None:
            raise HTTPException(status_code=409, detail="A chat goes only under a top-level chat")
        if any(parent == chat_id for child, parent in parent_by_id.items() if child != chat_id):
            raise HTTPException(status_code=409, detail="A chat others sit under stays at the top")

    # A chat under a parent takes its university from it: refused on a child,
    # and a code left from when it stood at the top goes when it moves under one.
    will_have_parent = fields.get("parent_chat_id", chat.parent_chat_id) is not None
    if will_have_parent and fields.get("institution_code") is not None:
        raise HTTPException(status_code=409, detail="A chat under a parent takes its university from it")
    if will_have_parent:
        fields["institution_code"] = None

    captcha = fields.pop("is_captcha_enabled", None)
    if captcha is not None and fields.get("join_mode") is None:
        fields["join_mode"] = Chat.JOIN_CAPTCHA if captcha else _mode_without_captcha(chat)
    if "join_mode" in fields and fields["join_mode"] is None:
        del fields["join_mode"]

    for key, value in fields.items():
        setattr(chat, key, value)
    await session.commit()
    # The public page shows what was just changed, not the minute-old answer.
    public_answers.forget()
    await session.refresh(chat)

    member_count = await member_counts.latest(session, chat.id)
    return ChatRead(
        id=chat.id,
        title=chat.title,
        resource_status=_resource_status(chat.resource_status),
        is_forum=chat.is_forum,
        kind=_kind(chat.kind),
        is_welcome_enabled=chat.is_welcome_enabled,
        is_captcha_enabled=chat.is_captcha_enabled,
        join_mode=_join_mode(chat.join_mode),
        join_by_request=chat.join_by_request,
        is_service_cleanup_enabled=chat.is_service_cleanup_enabled,
        parent_chat_id=chat.parent_chat_id,
        relation_notes=chat.relation_notes,
        public_link=chat.public_link,
        institution_code=chat.institution_code,
        city=chat.city,
        topic=_topic(chat.topic),
        member_count=member_count,
        has_photo=chat.photo_file_id is not None,
        last_synced_at=chat.last_synced_at,
        created_at=chat.created_at,
    )


@router.post("/{chat_id}/refresh", response_model=ChatRead)
async def refresh_chat_from_telegram(
    chat_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    bot: Annotated[Bot, Depends(get_publish_bot)],
    _admin_id: Annotated[int, Depends(require_super_admin)],
) -> ChatRead:
    """Pull the title and photo from Telegram now, for one chat.

    Manual counterpart to the hourly loop, and over the same Bot API call.
    The title leg used to go through Telethon, which this process has never
    had — so the button refreshed the photo, bumped the timestamp, and left
    the title exactly as it was.

    The member count comes back fresh here, because somebody who pressed a
    button marked "refresh" is entitled to a number that moved. The loop is
    what writes the row; this reads past it.
    """
    chat = (await session.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")
    if chat.is_preview_only:
        # Nothing to ask the bot: the page behind the invite link is all there is.
        async with aiohttp.ClientSession() as http:
            preview = await previews.sync(session, http, chat)
        await session.commit()
        await session.refresh(chat)
        public_answers.forget()
        member_count = preview.member_count if preview is not None else None
        if member_count is None:
            member_count = await member_counts.latest(session, chat.id)
        return _as_read(chat, member_count=member_count)

    metadata = await fetch_metadata(
        bot=bot, chat_id=chat_id, username=username_of(chat.public_link) if chat.public_link else None
    )
    if metadata is not None:
        if metadata.title and metadata.title != chat.title:
            chat.title = metadata.title
        chat.join_by_request = metadata.join_by_request
        await sync_photo(session=session, bot=bot, chat=chat, metadata=metadata)

    try:
        member_count = await fetch_member_count(bot=bot, chat_id=chat.id)
    except BotNotInChatError:
        member_count = None
    else:
        # Somebody who added the bot and pressed this should not wait a day for the hourly counts.
        if member_count is not None:
            chat.bot_absent_at = None

    chat.last_synced_at = utc_now()
    await session.commit()
    await session.refresh(chat)
    # The public catalog remembers its answer for a minute, and it carries the picture's address.
    public_answers.forget()

    if member_count is None:
        member_count = await member_counts.latest(session, chat.id)
    return ChatRead(
        id=chat.id,
        title=chat.title,
        resource_status=_resource_status(chat.resource_status),
        is_forum=chat.is_forum,
        kind=_kind(chat.kind),
        is_welcome_enabled=chat.is_welcome_enabled,
        is_captcha_enabled=chat.is_captcha_enabled,
        join_mode=_join_mode(chat.join_mode),
        join_by_request=chat.join_by_request,
        is_service_cleanup_enabled=chat.is_service_cleanup_enabled,
        parent_chat_id=chat.parent_chat_id,
        relation_notes=chat.relation_notes,
        public_link=chat.public_link,
        institution_code=chat.institution_code,
        city=chat.city,
        topic=_topic(chat.topic),
        member_count=member_count,
        has_photo=chat.photo_file_id is not None,
        last_synced_at=chat.last_synced_at,
        created_at=chat.created_at,
    )


@router.post("/external", response_model=ChatRead, status_code=201)
async def add_external_chat(
    payload: ExternalChatCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    bot: Annotated[Bot, Depends(get_publish_bot)],
    _admin_id: Annotated[int, Depends(require_super_admin)],
) -> ChatRead:
    """List a chat the bot is not in, marked as somebody else's.

    Telegram is asked by username, which it answers for any public chat, so the
    id and title are its own rather than typed into the console. A chat already
    in the table is refused rather than turned external: adding a link must
    never be the way moderation is switched off somewhere we run.

    Every refusal is a short code the console turns into words. Telegram
    failing is told apart from the link being wrong, and is not waited out:
    a flood wait can be minutes, which is no time to hold a request open.
    """
    if (invite := previews.invite_hash_of(payload.public_link)) is not None:
        return await _add_by_invite(session, invite)
    username = username_of(payload.public_link)
    if username is None:
        raise HTTPException(status_code=422, detail="not_public")
    try:
        found = await bot.get_chat(f"@{username}")
    except (TelegramRetryAfter, TelegramNetworkError, TelegramServerError, ClientDecodeError) as err:
        logger.warning("external_chat_lookup_failed", username=username, error=str(err), error_type=type(err).__name__)
        raise HTTPException(status_code=503, detail="telegram_unavailable") from err
    except TelegramAPIError as err:
        logger.info("external_chat_not_found", username=username, error=str(err), error_type=type(err).__name__)
        raise HTTPException(status_code=422, detail="not_found") from err
    # A channel is listed like a group: a student reads it rather than talks in
    # it, and the catalogue says which. A person's account is never listed.
    if found.type not in ("group", "supergroup", "channel"):
        raise HTTPException(status_code=422, detail="not_a_group")
    if await session.get(Chat, found.id) is not None:
        raise HTTPException(status_code=409, detail="already_known")

    chat = Chat(
        id=found.id,
        title=found.title,
        resource_status=Chat.STATUS_EXTERNAL,
        is_forum=bool(found.is_forum),
        kind=Chat.KIND_CHANNEL if found.type == "channel" else Chat.KIND_GROUP,
        public_link=f"https://t.me/{username}",
    )
    session.add(chat)
    try:
        await session.commit()
    except IntegrityError as err:
        # The bot recorded the chat between the check and the insert: it was
        # just added there, and whatever it recorded stands.
        await session.rollback()
        raise HTTPException(status_code=409, detail="already_known") from err
    public_answers.forget()
    await session.refresh(chat)
    return _as_read(chat, member_count=None)


async def _add_by_invite(session: AsyncSession, invite: str) -> ChatRead:
    """List a private chat by its invite link, from what its public page shows.

    The bot is not there and cannot learn the id, so the row gets one of ours
    (Chat.PREVIEW_ID_CEILING) and is kept current from the page. The same link
    always gives the same id, so adding it twice is refused like any other.
    """
    chat_id = Chat.preview_id_for(invite)
    if await session.get(Chat, chat_id) is not None:
        raise HTTPException(status_code=409, detail="already_known")
    link = previews.invite_link(invite)
    async with aiohttp.ClientSession() as http:
        preview = await previews.fetch(http, link)
        if preview is None:
            # A dead link and an unreachable t.me look the same from here.
            raise HTTPException(status_code=422, detail="not_found")
        chat = Chat(
            id=chat_id,
            title=preview.title,
            resource_status=Chat.STATUS_EXTERNAL,
            kind=Chat.KIND_CHANNEL if preview.is_channel else Chat.KIND_GROUP,
            public_link=link,
        )
        session.add(chat)
        await previews.sync(session, http, chat)
    try:
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        raise HTTPException(status_code=409, detail="already_known") from err
    public_answers.forget()
    await session.refresh(chat)
    return _as_read(chat, member_count=preview.member_count)


def _as_read(chat: Chat, *, member_count: int | None) -> ChatRead:
    return ChatRead(
        id=chat.id,
        title=chat.title,
        resource_status=_resource_status(chat.resource_status),
        is_forum=chat.is_forum,
        kind=_kind(chat.kind),
        is_welcome_enabled=chat.is_welcome_enabled,
        is_captcha_enabled=chat.is_captcha_enabled,
        join_mode=_join_mode(chat.join_mode),
        join_by_request=chat.join_by_request,
        is_service_cleanup_enabled=chat.is_service_cleanup_enabled,
        parent_chat_id=chat.parent_chat_id,
        relation_notes=chat.relation_notes,
        public_link=chat.public_link,
        institution_code=chat.institution_code,
        city=chat.city,
        topic=_topic(chat.topic),
        member_count=member_count,
        has_photo=chat.photo_file_id is not None,
        last_synced_at=chat.last_synced_at,
        created_at=chat.created_at,
    )
