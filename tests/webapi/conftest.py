"""Shared fixtures for webapi tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from app.core.config import settings
from app.webapi.main import app

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def override_super_admins() -> Iterator[None]:
    """Context manager style: set settings.admin.super_admins for the test
    and restore afterwards. Used by tests that exercise the auth dep."""
    original = list(settings.admin.super_admins)
    yield
    settings.admin.super_admins = original


@pytest.fixture(autouse=True)
def authenticated_super_admin() -> Iterator[None]:
    """Most webapi tests exercise endpoint behavior, not auth mechanics."""
    from app.webapi.deps import require_super_admin

    async def _override_require_super_admin() -> int:
        return settings.admin.super_admins[0]

    app.dependency_overrides[require_super_admin] = _override_require_super_admin
    yield
    app.dependency_overrides.pop(require_super_admin, None)


@pytest.fixture(autouse=True)
def _fresh_public_cache() -> None:
    """The public endpoints remember their answers; a test must start from none."""
    from app.webapi.routes import public

    public.forget_cached_answers()
