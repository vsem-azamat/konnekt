"""A scheduled deletion is kept alive until it has run."""

import asyncio
import gc
from unittest.mock import AsyncMock

import pytest
from app.presentation.telegram.utils import other

pytestmark = pytest.mark.asyncio


async def test_the_deletion_survives_garbage_collection() -> None:
    """The loop holds tasks weakly; an unreferenced one can vanish before it runs."""
    message = AsyncMock()

    other.sleep_and_delete(message, 0)
    gc.collect()
    await asyncio.sleep(0.01)

    message.delete.assert_awaited_once()
    assert not other._pending_deletions
