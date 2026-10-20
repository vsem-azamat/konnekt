"""Public read-only endpoints.

Keep this router intentionally narrow. Public pages should consume explicit
safe projections from here instead of reusing admin DTOs by accident.
"""

from __future__ import annotations

import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.time import utc_now
from app.db.models import Chat, Message
from app.webapi.deps import get_session
from app.webapi.schemas import PublicCatalogItem, PublicReach, PublicReachGroup
from app.webapi.services import member_counts, public_answers

router = APIRouter(prefix="/public", tags=["public"])

# How far back "is this chat alive" looks. A university chat goes quiet over the
# summer and busy in September, so a fortnight would call half the catalogue
# dead every August.
ACTIVITY_WINDOW = datetime.timedelta(days=30)

# Messages in that window. The bands are coarse deliberately: the reader is
# deciding whether a chat is worth joining, not comparing two of them.
BUSY_FROM = 100
ACTIVE_FROM = 10

# Days within the window on which anything at all was recorded, below which the
# window is not evidence about anybody.
#
# The bot was out of these chats between 22 May and 3 August, so on the day it
# returned a thirty-day count held one day of traffic. Every chat that had seen
# a single message read "active", including the one with seven thousand messages
# to its name and the one with two. The count was correct and the claim was
# false, which is the worst combination to ship: nothing looks broken.
#
# So the claim is withheld until there is a fortnight behind it, and it comes
# back on its own. This is a property of the recording, not of any one chat —
# a gap affects all of them at once.
MIN_OBSERVED_DAYS = 14

# How old a member count may be and still be shown. The bot writes one an hour;
# a chat it has not counted for three days is one it left or cannot see, and
# its last number would read as today's.
MEMBER_COUNT_FRESH_FOR = datetime.timedelta(days=3)

# Sorts after every real title, so ungrouped chats land at the end rather than
# at the top where an empty string would put them.
_UNGROUPED = "￿"

# What a chat with no university above it is called on the reach table. The
# catalogue page picks the same word for the same rows.
UNGROUPED_LABEL = "Остальные"


def _section(parent: type[Chat]):
    """The heading a chat is listed under.

    A faculty chat belongs to its university, which is the chat above it. But a
    university's own chat has nothing above it, and the rule "parent title, or
    else ungrouped" therefore filed the universities themselves under
    "Остальные" — beside a section carrying their own faculties. Of nineteen
    published chats eleven landed in that one bucket, five of them universities,
    and the page showed three sections where it had seven to show.

    A chat that is itself the parent of others is the section, so it stands
    under its own name. One with neither a parent nor children is genuinely
    loose and still falls through to NULL, which the caller reads as
    "Остальные".
    """
    child = aliased(Chat)
    leads_a_section = select(1).where(child.parent_chat_id == Chat.id).exists()

    # A parent names the section only once it was decided to list it: an
    # undecided chat's Telegram title is not for a public page, whatever sits
    # under it.
    named_parent = parent.title.is_not(None) & parent.resource_status.in_(Chat.LISTABLE_STATUSES)
    return case((named_parent, parent.title), (leads_a_section, Chat.title)).label("group_title")


def _activity(messages: int, *, grounded: bool) -> Literal["unknown", "quiet", "active", "busy"]:
    if not grounded:
        return "unknown"
    if messages >= BUSY_FROM:
        return "busy"
    if messages >= ACTIVE_FROM:
        return "active"
    return "quiet"


async def _observed_days(session: AsyncSession, since: datetime.datetime) -> int:
    """Days in the window on which the bot recorded anything, anywhere.

    Counted across the whole network rather than per chat: a quiet chat with no
    messages is a fact about the chat, while a quiet *database* is a fact about
    whether the bot was there to listen.
    """
    result = await session.execute(
        select(func.count(func.distinct(func.date(Message.timestamp)))).where(Message.timestamp >= since)
    )
    return result.scalar() or 0


@router.get("/catalog", response_model=list[PublicCatalogItem])
async def get_public_catalog(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PublicCatalogItem]:
    """Every chat a stranger may join, under the university above it.

    A chat is here when it was decided to list it (approved, observed or
    external) *and* has a public link. The link is the decision — there is no
    separate flag that could disagree with it — so a private faculty group
    without one cannot appear by accident, and taking a chat down means
    clearing one column.
    """
    if (cached := public_answers.remembered("catalog")) is not None:
        return cast("list[PublicCatalogItem]", cached)
    parent = aliased(Chat)
    since = utc_now() - ACTIVITY_WINDOW
    grounded = await _observed_days(session, since) >= MIN_OBSERVED_DAYS

    recent_messages = (
        select(Message.chat_id, func.count().label("messages"))
        .where(Message.timestamp >= since)
        .group_by(Message.chat_id)
        .subquery()
    )

    rows = (
        await session.execute(
            select(
                Chat.id,
                Chat.title,
                Chat.public_link,
                Chat.is_forum,
                Chat.resource_status,
                _section(parent),
                # The group's university: the parent's under one, the chat's own
                # at the top. Never a child's own: one left from when it stood at
                # the top would split its group.
                case((Chat.parent_chat_id.is_(None), Chat.institution_code), else_=parent.institution_code).label(
                    "institution"
                ),
                func.coalesce(recent_messages.c.messages, 0).label("messages"),
            )
            .outerjoin(parent, parent.id == Chat.parent_chat_id)
            .outerjoin(recent_messages, recent_messages.c.chat_id == Chat.id)
            .where(Chat.resource_status.in_(Chat.LISTABLE_STATUSES))
            .where(Chat.public_link.is_not(None))
        )
    ).all()
    counts = await member_counts.latest_for(session, [row.id for row in rows], since=utc_now() - MEMBER_COUNT_FRESH_FOR)

    items = [
        PublicCatalogItem(
            title=row.title,
            link=row.public_link,
            group=row.group_title,
            institution=row.institution,
            activity=_activity(row.messages, grounded=grounded),
            member_count=counts.get(row.id),
            is_forum=bool(row.is_forum),
            external=row.resource_status == Chat.STATUS_EXTERNAL,
        )
        for row in rows
        if row.title and row.public_link
    ]
    # Grouped and alphabetical, so the page renders what the server already
    # decided instead of sorting forty-five rows again in the browser.
    answer = sorted(
        items,
        key=lambda item: (
            (item.group or _UNGROUPED).lower(),
            # A section opens with its own chat: the university's general room
            # above its faculties, rather than alphabetised in among them.
            item.title != item.group,
            item.title.lower(),
        ),
    )
    public_answers.remember("catalog", answer)
    return answer


@router.get("/reach", response_model=PublicReach)
async def get_public_reach(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PublicReach:
    """How far a post across the published catalogue would carry.

    Counted over the chats in `/catalog` that the bot moderates, and no others.
    Reach summed across private chats would be a claim about rooms nobody being
    quoted a price can see, and publishing their size is not ours to do; summed
    across chats we only observe or are not in, it would sell an audience no
    post of ours can reach.

    Member counts come from the snapshots the userbot writes, never from
    Telethon at request time: this endpoint answers strangers, and a public URL
    that reaches into the account behind it is a public URL somebody can point
    at the account. The newest snapshot per chat is the answer — the loop writes
    a row per poll, and summing all of them would count the same people once per
    observation — and, as on the catalogue, none older than
    MEMBER_COUNT_FRESH_FOR: a chat the bot stopped counting is unmeasured.
    """
    if (cached := public_answers.remembered("reach")) is not None:
        return cast("PublicReach", cached)
    parent = aliased(Chat)
    rows = (
        await session.execute(
            select(Chat.id, _section(parent))
            .outerjoin(parent, parent.id == Chat.parent_chat_id)
            .where(Chat.resource_status == Chat.STATUS_APPROVED)
            .where(Chat.public_link.is_not(None))
        )
    ).all()
    counts = await member_counts.latest_for(session, [row.id for row in rows], since=utc_now() - MEMBER_COUNT_FRESH_FOR)

    groups: dict[str, PublicReachGroup] = {}
    measured = 0
    for row in rows:
        name = row.group_title or UNGROUPED_LABEL
        group = groups.setdefault(name, PublicReachGroup(name=name, chats=0, members=0))
        group.chats += 1
        if (count := counts.get(row.id)) is not None:
            group.members += count
            measured += 1

    # Largest first: the table is read as "where would this post land", and the
    # answer starts with the biggest room. Sorted into a name of its own rather
    # than inline, because Pydantic will also accept a mapping for this field —
    # and inline, that widens what the type checker believes `group` to be.
    ordered = sorted(groups.values(), key=lambda group: (-group.members, group.name.lower()))

    answer = PublicReach(
        chats=len(rows),
        members=sum(group.members for group in ordered),
        measured_chats=measured,
        groups=ordered,
    )
    public_answers.remember("reach", answer)
    return answer
