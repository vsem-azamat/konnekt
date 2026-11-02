"""A feature is on when it is configured, and off otherwise.

Separate enable-flags could disagree with the configuration they gate, and only
ever in one direction that matters: a flag saying yes over credentials that are
absent, which produces a subsystem that starts, fails, and says nothing.

So the flags are gone and activation is derived from what is configured.
"""

from __future__ import annotations

import pytest
from app.core.config import WebApiSettings

pytestmark = pytest.mark.unit


class TestWebApi:
    def test_origins_come_from_the_public_url(self) -> None:
        """Two settings obliged to agree are one setting and a bug waiting."""
        settings = WebApiSettings(public_url="https://admin.example.com")

        assert settings.allowed_origins == ["https://admin.example.com"]

    def test_no_public_url_means_no_origins(self) -> None:
        """Local development supplies its own fallback rather than a wrong guess."""
        assert WebApiSettings(public_url="").allowed_origins == []

    def test_a_trailing_slash_does_not_become_a_different_origin(self) -> None:
        """Browsers compare origins exactly; the slash would fail every check."""
        settings = WebApiSettings(public_url="https://admin.example.com/")

        assert settings.allowed_origins == ["https://admin.example.com"]

    def test_secure_cookies_are_the_default(self) -> None:
        """Local development opts out; production cannot forget to opt in."""
        assert WebApiSettings().session_cookie_secure is True
