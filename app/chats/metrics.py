"""What the chat services tell Prometheus. Never a chat or a person as a label."""

from __future__ import annotations

from prometheus_client import Counter, Gauge

# kept, created, replaced, username, transient, failed, and each problem the
# bot cannot mend (no_invite_right, not_in_chat, create_failed).
INVITE_LINK_EVENTS = Counter("invite_link_events_total", "Outcomes of checking a listed chat's link", ["event"])
INVITE_LINK_PROBLEMS = Gauge("invite_link_problems", "Listed chats whose link the bot cannot mend", ["problem"])
# left, not_admin, no_delete, no_restrict, no_invite, and unknown for an approved
# chat nobody has asked about yet.
BOT_RIGHTS_MISSING = Gauge("bot_chat_rights_missing", "Approved chats where the bot lacks what it needs", ["problem"])
