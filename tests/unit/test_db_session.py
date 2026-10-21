"""The bot's database is on another host; a blip must fail fast, not hang."""

from __future__ import annotations

from app.db import session as session_module


def test_connections_and_queries_have_timeouts(monkeypatch) -> None:
    """A connect with no timeout waited out every blip, holding each update while it did."""
    seen: dict = {}

    def capture(url, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(session_module, "create_async_engine", capture)

    session_module.create_engine()

    assert seen["pool_pre_ping"] is True
    assert 0 < seen["connect_args"]["timeout"] <= 15
    assert 0 < seen["connect_args"]["command_timeout"] <= 60
    assert 0 < seen["pool_timeout"] <= 30


def test_error_messages_do_not_quote_the_parameters() -> None:
    """A database error names the statement's parameters: message text, names, ids."""
    assert session_module.create_engine().sync_engine.hide_parameters is True
