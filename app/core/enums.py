"""Core enumerations shared across all layers."""

from enum import StrEnum


class ModerationEventAction(StrEnum):
    """An action worth a line in the record.

    Everything a moderator can do to a member appears here, including
    the reversals: "unbanned an hour later" is the half of the story that says
    whether the ban stuck.
    """

    BAN = "ban"
    UNBAN = "unban"
    KICK = "kick"
    MUTE = "mute"
    UNMUTE = "unmute"
    BLACKLIST = "blacklist"
    UNBLACKLIST = "unblacklist"
    # Trusting somebody with a chat, and taking it back: the most consequential
    # thing a person can do here.
    GRANT = "grant"
    REVOKE = "revoke"
    # Acting on a message rather than its author; the target is the author.
    DELETE = "delete"
    PURGE = "purge"
    PIN = "pin"
    UNPIN = "unpin"


class ModerationEventSource(StrEnum):
    """How the action was asked for.

    Separate from the actor, who is always a person. ``MCP`` stays for the
    history: confirmed proposals from the retired MCP control plane were
    recorded under it, with the admin who pressed confirm as their actor.
    """

    COMMAND = "command"
    MCP = "mcp"
    CONSOLE = "console"


class Touchpoint(StrEnum):
    """Where a person met us. The bots among them are also who may write back.

    The retired bots count as a place someone came to, but nobody is reached
    through them: they only point at the main bot.
    """

    MAIN_BOT = "main_bot"
    CONTACT_BOT = "contact_bot"
    MINI_APP = "mini_app"
    MOVED_BOT = "moved_bot"


class SpamVerdict(StrEnum):
    """What a moderator said about an ad-detector hit.

    ``DONE`` and ``NOT_AD`` are answered in the console; ``NOT_AD`` is a false
    alarm, kept to tune the detector by. ``AD`` is written by a ban, on every
    hit of the author still waiting, once the ban took in some chat.
    """

    DONE = "done"
    NOT_AD = "not_ad"
    AD = "ad"
