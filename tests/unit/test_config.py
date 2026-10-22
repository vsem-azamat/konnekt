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


def test_the_start_video_is_read_without_the_newline_it_was_pasted_with(monkeypatch):
    """A file_id with its newline would be refused on every /start."""
    from app.core.config import TelegramSettings

    monkeypatch.setenv("MODERATOR_BOT_INTRO_VIDEO", " BAACAgIAAxkB \n")

    assert TelegramSettings(_env_file=None).intro_video == "BAACAgIAAxkB"
