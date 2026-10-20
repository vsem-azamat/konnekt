"""Fake Telegram Bot API server for end-to-end testing.

Starts a lightweight aiohttp server that mimics Telegram's Bot API responses.
Handlers record all API calls so tests can assert on them.

Usage:
    async with FakeTelegramServer() as server:
        bot = Bot(token="123:fake", base_url=server.base_url)
        # ... use bot normally, then check server.calls
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aiohttp import web


@dataclass
class ApiCall:
    """Recorded API call to the fake server."""

    method: str
    params: dict[str, Any]


class FakeTelegramServer:
    """Fake Telegram Bot API that records calls and returns configurable responses."""

    def __init__(self, port: int = 0) -> None:
        self.port = port
        self.calls: list[ApiCall] = []
        self._app = web.Application()
        self._app.router.add_route("POST", "/bot{token}/{method}", self._handle)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._base_url: str = ""
        self._message_id_counter = 1000
        # Custom response overrides: method_name -> response dict
        self._responses: dict[str, dict[str, Any]] = {}
        # Chat admin configs: chat_id -> list of admin user IDs
        self._chat_admins: dict[int, list[int]] = {}

    @property
    def base_url(self) -> str:
        """Base URL for the Bot API (e.g. http://localhost:PORT)."""
        return self._base_url

    def set_response(self, method: str, response: dict[str, Any]) -> None:
        """Override the response for a specific API method."""
        self._responses[method] = response

    def set_chat_admins(self, chat_id: int, admin_ids: list[int]) -> None:
        """Configure which user IDs are admins for a chat."""
        self._chat_admins[chat_id] = admin_ids

    def get_calls(self, method: str | None = None) -> list[ApiCall]:
        """Get recorded calls, optionally filtered by method."""
        if method is None:
            return list(self.calls)
        return [c for c in self.calls if c.method == method]

    def reset(self) -> None:
        """Clear recorded calls."""
        self.calls.clear()

    async def _handle(self, request: web.Request) -> web.Response:
        method = request.match_info["method"]

        # Parse params from form data or JSON
        try:
            if request.content_type == "application/json":
                params = await request.json()
            else:
                data = await request.post()
                params = dict(data)
        except Exception:
            params = {}

        self.calls.append(ApiCall(method=method, params=params))

        # Check custom overrides first
        if method in self._responses:
            return web.json_response(self._responses[method])

        # Default responses per method
        handler = getattr(self, f"_handle_{method}", None)
        if handler:
            return handler(params)

        # Generic success for unknown methods
        return web.json_response({"ok": True, "result": True})

    def _handle_getMe(self, params: dict[str, Any]) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "result": {
                    "id": 5145935834,
                    "is_bot": True,
                    "first_name": "Test Bot",
                    "username": "test_bot",
                    "can_join_groups": True,
                    "can_read_all_group_messages": True,
                    "supports_inline_queries": False,
                },
            }
        )

    def _handle_deleteWebhook(self, params: dict[str, Any]) -> web.Response:
        return web.json_response({"ok": True, "result": True})

    def _handle_sendMessage(self, params: dict[str, Any]) -> web.Response:
        self._message_id_counter += 1
        return web.json_response(
            {
                "ok": True,
                "result": {
                    "message_id": self._message_id_counter,
                    "from": {"id": 5145935834, "is_bot": True, "first_name": "Test Bot"},
                    "chat": {
                        "id": int(params.get("chat_id", 0)),
                        "type": "supergroup",
                        "title": "Test Chat",
                    },
                    "date": 1700000000,
                    "text": params.get("text", ""),
                },
            }
        )

    def _handle_editMessageText(self, params: dict[str, Any]) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "result": {
                    "message_id": int(params.get("message_id", 1)),
                    "from": {"id": 5145935834, "is_bot": True, "first_name": "Test Bot"},
                    "chat": {
                        "id": int(params.get("chat_id", 0)),
                        "type": "supergroup",
                        "title": "Test Chat",
                    },
                    "date": 1700000000,
                    "text": params.get("text", ""),
                },
            }
        )

    def _handle_deleteMessage(self, params: dict[str, Any]) -> web.Response:
        return web.json_response({"ok": True, "result": True})

    def _handle_sendMediaGroup(self, params: dict[str, Any]) -> web.Response:
        """Return one minimal Message per item in the media list, with distinct ids."""
        media_raw = params.get("media", "[]")
        try:
            media = json.loads(media_raw) if isinstance(media_raw, str) else list(media_raw)
        except (TypeError, ValueError):
            media = []
        chat_id = int(params.get("chat_id", 0))
        messages: list[dict[str, Any]] = []
        for _ in media:
            self._message_id_counter += 1
            messages.append(
                {
                    "message_id": self._message_id_counter,
                    "from": {"id": 5145935834, "is_bot": True, "first_name": "Test Bot"},
                    "chat": {"id": chat_id, "type": "supergroup", "title": "Test Chat"},
                    "date": 1700000000,
                    "photo": [
                        {
                            "file_id": f"photo-{self._message_id_counter}",
                            "file_unique_id": f"u-{self._message_id_counter}",
                            "width": 800,
                            "height": 600,
                            "file_size": 1024,
                        }
                    ],
                }
            )
        return web.json_response({"ok": True, "result": messages})

    def _handle_deleteMessages(self, params: dict[str, Any]) -> web.Response:
        """Bulk delete. Accept and record the list; return success."""
        return web.json_response({"ok": True, "result": True})

    def _handle_restrictChatMember(self, params: dict[str, Any]) -> web.Response:
        return web.json_response({"ok": True, "result": True})

    def _handle_banChatMember(self, params: dict[str, Any]) -> web.Response:
        return web.json_response({"ok": True, "result": True})

    def _handle_unbanChatMember(self, params: dict[str, Any]) -> web.Response:
        return web.json_response({"ok": True, "result": True})

    def _handle_answerCallbackQuery(self, params: dict[str, Any]) -> web.Response:
        return web.json_response({"ok": True, "result": True})

    def _handle_getChatAdministrators(self, params: dict[str, Any]) -> web.Response:
        chat_id = int(params.get("chat_id", 0))
        admin_ids = self._chat_admins.get(chat_id, [123456789])
        admins = []
        for uid in admin_ids:
            admins.append(
                {
                    "user": {
                        "id": uid,
                        "is_bot": False,
                        "first_name": f"Admin{uid}",
                    },
                    "status": "administrator",
                    "can_be_edited": False,
                    "can_manage_chat": True,
                    "can_change_info": True,
                    "can_delete_messages": True,
                    "can_invite_users": True,
                    "can_restrict_members": True,
                    "can_pin_messages": True,
                    "can_promote_members": False,
                    "can_manage_video_chats": True,
                    "can_post_stories": True,
                    "can_edit_stories": True,
                    "can_delete_stories": True,
                    "can_send_welcome_messages": False,
                    "can_manage_topics": True,
                    "is_anonymous": False,
                }
            )
        return web.json_response({"ok": True, "result": admins})

    def _handle_getChatMember(self, params: dict[str, Any]) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "result": {
                    "user": {
                        "id": int(params.get("user_id", 0)),
                        "is_bot": False,
                        "first_name": "User",
                    },
                    "status": "member",
                },
            }
        )

    def _handle_leaveChat(self, params: dict[str, Any]) -> web.Response:
        return web.json_response({"ok": True, "result": True})

    async def __aenter__(self) -> FakeTelegramServer:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", self.port)
        await self._site.start()
        # Get actual port (useful when port=0 for random)
        actual_port = self._site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        self._base_url = f"http://127.0.0.1:{actual_port}"
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._runner:
            await self._runner.cleanup()
