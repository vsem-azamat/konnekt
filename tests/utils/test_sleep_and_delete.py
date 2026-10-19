"""A scheduled deletion is held until it has run, then let go."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from app.presentation.telegram.utils import other

pytestmark = pytest.mark.asyncio


async def test_the_deletion_is_held_while_it_waits_and_released_after() -> None:
    """asyncio keeps only weak references to tasks; the caller has to hold them."""
    message = AsyncMock()

    other.sleep_and_delete(message, 0)
    assert len(other._pending_deletions) == 1
    await asyncio.sleep(0.01)

    message.delete.assert_awaited_once()
    assert not other._pending_deletions
