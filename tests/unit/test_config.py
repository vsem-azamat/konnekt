"""Unit tests for configuration classes, container, and two-bot wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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


@pytest.mark.parametrize("name", ["intro_video", "intro_video_cover", "intro_photo"])
def test_the_intro_media_are_read_without_the_newline_they_were_pasted_with(monkeypatch, name):
    """A file_id with its newline would be refused on every /start."""
    from app.core.config import TelegramSettings

    monkeypatch.setenv(f"MODERATOR_BOT_{name.upper()}", " BAACAgIAAxkB \n")

    assert getattr(TelegramSettings(_env_file=None), name) == "BAACAgIAAxkB"
