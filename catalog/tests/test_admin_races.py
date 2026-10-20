"""An operator's moderation and the owner's own save, at the same moment.

Each test commits for real on two connections, because a race is what one
transaction cannot show: the loser has to be blocked on the winner's row and
read it again once it commits. The rows are removed at the end.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from students_cz.db.models import HelperProfile, User
from students_cz.db.models.enums import PublishStatus, UiLang
from students_cz.schemas import HelperUpsert
from students_cz.services import admin, helpers
from students_cz.services.errors import Conflict, Forbidden

pytestmark = pytest.mark.asyncio

TG_ID = 97901
# Long enough for the other transaction to reach the lock and wait on it.
WAIT = 0.3


@pytest_asyncio.fixture
async def listed(engine: AsyncEngine) -> AsyncIterator[int]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        # A run that died before its teardown must not block the next one.
        await session.execute(delete(User).where(User.tg_id == TG_ID))
        user = User(
            tg_id=TG_ID, first_name="Race", ui_lang=UiLang.RU, spoken_langs=["ru"]
        )
        session.add(user)
        await session.flush()
        user_id = user.id
        session.add(
            HelperProfile(
                user_id=user_id,
                status=PublishStatus.PUBLISHED,
                published_at=datetime.now(UTC),
            )
        )
        await session.commit()
    yield user_id
    async with AsyncSession(engine) as session:
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


async def _status(engine: AsyncEngine, user_id: int) -> PublishStatus:
    async with AsyncSession(engine) as session:
        status = await session.scalar(
            select(HelperProfile.status).where(HelperProfile.user_id == user_id)
        )
        assert status is not None
        return status


async def test_an_owner_hiding_first_is_not_overwritten_by_a_ban(
    engine: AsyncEngine, listed: int
) -> None:
    """The operator saw it listed; by the time the ban lands the owner took it
    down. A ban then would be lifted by «Вернуть» into a listing the owner
    never asked for."""

    async def ban() -> None:
        async with AsyncSession(engine) as session:
            await admin.hide_profile(session, UiLang.RU, listed)
            await session.commit()

    async with AsyncSession(engine) as owner:
        profile = await owner.scalar(
            select(HelperProfile).where(HelperProfile.user_id == listed).with_for_update()
        )
        assert profile is not None
        profile.status = PublishStatus.HIDDEN
        await owner.flush()
        banning = asyncio.create_task(ban())
        await asyncio.sleep(WAIT)
        await owner.commit()

    with pytest.raises(Conflict):
        await banning
    assert await _status(engine, listed) == PublishStatus.HIDDEN


async def test_an_owner_saving_over_a_ban_is_refused(
    engine: AsyncEngine, listed: int
) -> None:
    """The ban lands while the owner's save is on its way: the save must see
    the ban, not turn it into the owner's own «hidden»."""

    async def save() -> None:
        async with AsyncSession(engine) as session:
            user = await session.get(User, listed)
            assert user is not None
            await helpers.save_profile(
                session, user=user, spec=HelperUpsert(publish=False), lang=UiLang.RU
            )
            await session.commit()

    async with AsyncSession(engine) as operator:
        await admin.hide_profile(operator, UiLang.RU, listed)
        saving = asyncio.create_task(save())
        await asyncio.sleep(WAIT)
        await operator.commit()

    with pytest.raises(Forbidden):
        await saving
    assert await _status(engine, listed) == PublishStatus.BANNED
