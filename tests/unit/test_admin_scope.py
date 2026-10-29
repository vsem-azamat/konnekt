"""Granting and taking back the right to moderate one chat.

The rules worth pinning down are the ones a reader would not guess: an
administrator with no chats is not kept around, and revoking a chat somebody
never had is not an error, just a no.
"""

import pytest
from app.db.models import Admin, Chat
from app.db.repositories import AdminRepository

pytestmark = pytest.mark.unit

MODERATOR = 555
GRANTED_BY = 111

HOME = -1001370017010  # ČVUT FIT
ELSEWHERE = -1001497722835  # Strahov


@pytest.fixture
async def repo(session) -> AdminRepository:
    for chat_id in (HOME, ELSEWHERE):
        session.add(Chat(id=chat_id, title=str(chat_id), resource_status=Chat.STATUS_APPROVED))
    await session.commit()
    return AdminRepository(session)


class TestGranting:
    async def test_a_first_grant_creates_the_administrator(self, repo, session) -> None:
        assert await repo.grant(MODERATOR, HOME, granted_by=GRANTED_BY) is True

        assert await repo.is_admin_in(MODERATOR, HOME) is True
        assert await session.get(Admin, MODERATOR) is not None

    async def test_the_scope_does_not_leak_to_other_chats(self, repo) -> None:
        await repo.grant(MODERATOR, HOME)

        assert await repo.is_admin_in(MODERATOR, ELSEWHERE) is False

    async def test_granting_twice_changes_nothing(self, repo) -> None:
        await repo.grant(MODERATOR, HOME)

        assert await repo.grant(MODERATOR, HOME) is False
        assert await repo.chats_for(MODERATOR) == [HOME]

    async def test_a_second_chat_is_added_not_swapped(self, repo) -> None:
        await repo.grant(MODERATOR, HOME)
        await repo.grant(MODERATOR, ELSEWHERE)

        assert set(await repo.chats_for(MODERATOR)) == {HOME, ELSEWHERE}


class TestRevoking:
    async def test_only_the_named_chat_is_taken_back(self, repo) -> None:
        await repo.grant(MODERATOR, HOME)
        await repo.grant(MODERATOR, ELSEWHERE)

        assert await repo.revoke(MODERATOR, HOME) is True

        assert await repo.is_admin_in(MODERATOR, HOME) is False
        assert await repo.is_admin_in(MODERATOR, ELSEWHERE) is True

    async def test_losing_the_last_chat_ends_the_job(self, repo, session) -> None:
        """Otherwise the administrator list grows names that moderate nothing."""
        await repo.grant(MODERATOR, HOME)

        await repo.revoke(MODERATOR, HOME)

        assert await session.get(Admin, MODERATOR) is None
        assert await repo.is_admin(MODERATOR) is False

    async def test_revoking_what_was_never_granted_is_a_no_not_a_crash(self, repo) -> None:
        assert await repo.revoke(MODERATOR, HOME) is False

    async def test_revoking_one_chat_leaves_the_others_reachable(self, repo) -> None:
        await repo.grant(MODERATOR, HOME)
        await repo.grant(MODERATOR, ELSEWHERE)

        await repo.revoke(MODERATOR, HOME)

        assert await repo.is_admin(MODERATOR) is True


class TestDeactivation:
    async def test_a_deactivated_administrator_may_act_nowhere(self, repo, session) -> None:
        """`state` is the whole-person switch; the scope rows are left alone."""
        await repo.grant(MODERATOR, HOME)

        admin = await session.get(Admin, MODERATOR)
        admin.state = False
        await session.commit()

        assert await repo.is_admin_in(MODERATOR, HOME) is False
