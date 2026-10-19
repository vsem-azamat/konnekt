"""Unit tests for configuration classes, container, and two-bot wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# ModerationSettings validation
# ---------------------------------------------------------------------------


class TestContainerTryGetBot:
    def test_returns_none_when_not_set(self):
        from app.core.container import Container

        c = Container()
        assert c.try_get_bot() is None

    def test_returns_bot_when_set(self):
        from app.core.container import Container

        c = Container()
        bot = MagicMock()
        c.set_bot(bot)
        assert c.try_get_bot() is bot
