"""The console's search across everything: chats and people, from the top bar.

A few of each, enough to jump to one; the Chats and Audience screens are where
a longer list is read.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AudienceMember, Chat, User
from app.webapi.deps import get_session
from app.webapi.schemas import SearchChat, SearchPerson, SearchResults

router = APIRouter(prefix="/search", tags=["search"])

_LIMIT = 6
_MAX_ID = 2**63 - 1
_NUMBER = re.compile(r"-?\d{1,19}")


def _like(text: str) -> str:
    """A pattern for the text as typed: % and _ are letters here, not wildcards."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _chat_ids(number: int) -> set[int]:
    """The chats a typed number may mean: as typed, or a group's id typed
    without its minus, or a supergroup's without its -100."""
    digits = str(abs(number))
    ids = {number, -abs(number), int("-100" + digits)}
    return {i for i in ids if -_MAX_ID <= i <= _MAX_ID}


@router.get("", response_model=SearchResults)
async def search(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(max_length=64)] = "",
) -> SearchResults:
    text = q.strip().removeprefix("@").strip()
    if not text:
        return SearchResults(chats=[], people=[])
    like = _like(text)
    number = int(text) if _NUMBER.fullmatch(text) else None

    chat_matches = [Chat.title.ilike(like, escape="\\"), Chat.public_link.ilike(like, escape="\\")]
    if number is not None:
        chat_matches.append(Chat.id.in_(_chat_ids(number)))
    chats = await session.scalars(
        select(Chat).where(or_(*chat_matches)).order_by(Chat.title.asc(), Chat.id).limit(_LIMIT)
    )

    person = number if number is not None and 0 < number <= _MAX_ID else None

    def person_matches(key, username, first_name, last_name) -> list:
        matches = [column.ilike(like, escape="\\") for column in (username, first_name, last_name)]
        if person is not None:
            matches.append(key == person)
        return matches

    by_member = person_matches(
        AudienceMember.user_id, AudienceMember.username, AudienceMember.first_name, AudienceMember.last_name
    )
    by_user = person_matches(User.id, User.username, User.first_name, User.last_name)
    members = list(
        await session.scalars(
            select(AudienceMember)
            .where(or_(*by_member))
            .order_by(AudienceMember.last_seen_at.desc(), AudienceMember.user_id)
            .limit(_LIMIT)
        )
    )
    users = list(
        await session.scalars(
            select(User).where(or_(*by_user)).order_by(User.modified_at.desc(), User.id).limit(_LIMIT)
        )
    )
    # One entry a person, with the audience's profile where there is one: it
    # is what the card the entry opens shows. The blacklist is the users'.
    blocked = {user.id for user in users if user.blocked}
    if members:
        blocked |= set(
            await session.scalars(
                select(User.id).where(User.id.in_([m.user_id for m in members]), User.blocked.is_(True))
            )
        )
    # Someone the audience knows under another name still has a card.
    carded = set(
        await session.scalars(select(AudienceMember.user_id).where(AudienceMember.user_id.in_([u.id for u in users])))
    )
    people: dict[int, SearchPerson] = {}
    for member in members:
        people[member.user_id] = SearchPerson(
            user_id=member.user_id,
            username=member.username,
            first_name=member.first_name,
            last_name=member.last_name,
            in_audience=True,
            blocked=member.user_id in blocked,
        )
    for user in users:
        people.setdefault(
            user.id,
            SearchPerson(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                in_audience=user.id in carded,
                blocked=user.blocked,
            ),
        )

    return SearchResults(
        chats=[
            SearchChat(id=chat.id, title=chat.title, resource_status=chat.resource_status, public_link=chat.public_link)
            for chat in chats
        ],
        people=list(people.values())[:_LIMIT],
    )
