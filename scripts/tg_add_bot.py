"""Put the moderator bot back into the chats it left, quietly.

In May a middleware decided that a chat where the owner's personal account was
not an administrator was a chat worth leaving, and the bot walked out of most of
them. A bot cannot add itself, so this is done by the account that now
administers those chats.

    uv run python scripts/tg_add_bot.py --account work --bot @konnekt_cz_bot --chats scope.txt
    uv run python scripts/tg_add_bot.py --account work --bot @konnekt_cz_bot --chats scope.txt --apply

Without ``--apply`` nothing is sent.

Quietly
-------
Adding someone to a group leaves a service message in it — "X added Y" — and
thirty-five of those across the university chats is noise for several thousand
students who did not ask to watch an administrative repair. So each addition is
followed by deleting the notice it produced. ``--sweep`` extends that to notices
already sitting in the chats from earlier work.

That is the only reason this file reads messages at all, and it reads only
service messages: the ones Telegram generates about membership. It never looks
at, keeps or prints anything a person wrote.

The rights the bot is given
---------------------------
What its own commands use, and nothing more. No ``add_admins`` — a bot that can
appoint administrators turns a leaked token into a way to take over a chat — and
no ``change_info``. It cannot promote, it cannot rename, and it cannot make
itself anonymous.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tg_accounts import SESSIONS_DIR, api_credentials, session_path  # noqa: E402
from tg_promote import MAX_TITLE, Journal, read_scope  # noqa: E402

if TYPE_CHECKING:
    from telethon import TelegramClient

MIN_DELAY = 5.0
MAX_DELAY = 15.0

# How far back to look for the notice an addition just produced. It is the last
# message in the chat unless people are talking, and a chat that busy will have
# pushed it out of reach long before this runs.
NOTICE_LOOKBACK = 25


def bot_rights() -> dict[str, bool]:
    """Moderation, and nothing that could hand the chat over.

    ``invite_users`` is here because approving a join request counts as one;
    without it the bot cannot answer the requests it exists to handle.
    """
    return {
        "change_info": False,
        "post_messages": False,
        "edit_messages": False,
        "delete_messages": True,
        "ban_users": True,
        "invite_users": True,
        "pin_messages": True,
        "add_admins": False,
        "manage_call": False,
        "anonymous": False,
    }


def _client(account: str, directory: Path) -> TelegramClient:
    from telethon import TelegramClient

    api_id, api_hash = api_credentials()
    path = session_path(account, directory=directory)
    if not path.exists():
        raise SystemExit(f"no session for {account!r} at {path}")
    return TelegramClient(str(path.with_suffix("")), api_id, api_hash)


def announces(message: Any, watched: set[int]) -> bool:
    """Whether this is a membership notice about one of the accounts we care about.

    Only service messages reach here, and only their action is examined — who
    arrived, never what anybody said.
    """
    from telethon.tl.types import (
        MessageActionChatAddUser,
        MessageActionChatJoinedByLink,
        MessageActionChatJoinedByRequest,
        MessageService,
    )

    if not isinstance(message, MessageService):
        return False
    action = message.action
    if isinstance(action, MessageActionChatAddUser):
        return any(int(user) in watched for user in action.users)
    if isinstance(action, MessageActionChatJoinedByLink | MessageActionChatJoinedByRequest):
        sender = message.from_id
        return bool(sender and int(getattr(sender, "user_id", 0)) in watched)
    return False


async def clear_notices(client: TelegramClient, chat_id: int, watched: set[int], *, limit: int) -> int:
    """Delete the membership notices about the watched accounts. Returns how many."""
    from telethon.tl.types import MessageService

    doomed = []
    async for message in client.iter_messages(chat_id, limit=limit):
        # The filter runs before anything else touches the message, so a normal
        # message is never examined beyond its type.
        if isinstance(message, MessageService) and announces(message, watched):
            doomed.append(message.id)

    if doomed:
        await client.delete_messages(chat_id, doomed)
    return len(doomed)


async def add_bot(client: TelegramClient, chat_id: int, bot: Any, title: str) -> None:
    import contextlib

    from telethon.errors import UserAlreadyParticipantError
    from telethon.tl import functions

    # Present but not an admin is a normal state to find a bot in, and the
    # invitation is what fails then rather than the promotion.
    with contextlib.suppress(UserAlreadyParticipantError):
        await client(functions.channels.InviteToChannelRequest(channel=chat_id, users=[bot]))
    await client.edit_admin(chat_id, bot, title=title[:MAX_TITLE], **bot_rights())


async def run(
    *,
    account: str,
    bot: str,
    scope: list[Any],
    title: str,
    directory: Path,
    journal_path: Path | None,
    apply: bool,
    sweep: bool,
    min_delay: float,
    max_delay: float,
) -> int:
    from telethon.errors import FloodWaitError, PeerFloodError, UserNotParticipantError

    client = _client(account, directory)
    await client.start()  # type: ignore[func-returns-value]
    journal = Journal(journal_path)

    me = await client.get_me()
    bot_entity = await client.get_entity(bot)
    watched = {int(bot_entity.id), int(me.id)}

    print(f"acting as {me.username or me.first_name} (id {me.id})")
    print(f"adding {getattr(bot_entity, 'username', None) or bot_entity.id} to {len(scope)} chats")
    print("mode:   " + ("APPLY" if apply else "plan only (pass --apply to act)"))
    print()

    added = skipped = failed = notices = 0
    try:
        for entry in scope:
            label = f"{entry.chat_id:>15} {entry.title[:36]:<38}"
            if journal.already(entry.chat_id):
                print(f"{label} done earlier")
                skipped += 1
                continue

            try:
                permissions = await client.get_permissions(entry.chat_id, bot_entity)
                present = True
                is_admin = bool(permissions.is_admin)
            except UserNotParticipantError:
                present, is_admin = False, False
            except Exception as err:  # noqa: BLE001 — reported per chat
                print(f"{label} cannot read: {type(err).__name__}")
                failed += 1
                continue

            if is_admin and not sweep:
                journal.record(entry.chat_id, ok=True, detail="already admin")
                print(f"{label} already admin")
                skipped += 1
                continue

            if not apply:
                print(f"{label} would {'promote' if present else 'add and promote'}")
                continue

            try:
                if not is_admin:
                    await add_bot(client, entry.chat_id, bot_entity, title)
                cleared = await clear_notices(client, entry.chat_id, watched, limit=NOTICE_LOOKBACK)
            except PeerFloodError:
                journal.record(entry.chat_id, ok=False, detail="peer_flood")
                print(f"{label} PEER_FLOOD — stopping. Resume in a few hours with the same journal.")
                failed += 1
                break
            except FloodWaitError as err:
                journal.record(entry.chat_id, ok=False, detail=f"flood_wait {err.seconds}s")
                print(f"{label} flood wait {err.seconds}s — stopping.")
                failed += 1
                break
            except Exception as err:  # noqa: BLE001 — one chat failing must not end the rest
                journal.record(entry.chat_id, ok=False, detail=f"{type(err).__name__}: {err}")
                print(f"{label} failed: {type(err).__name__}")
                failed += 1
                continue

            journal.record(entry.chat_id, ok=True)
            added += 1
            notices += cleared
            print(f"{label} {'promoted' if is_admin else 'added'}{f', {cleared} notice(s) removed' if cleared else ''}")
            await asyncio.sleep(random.uniform(min_delay, max_delay))  # noqa: S311 — pacing, not cryptography
    finally:
        await client.disconnect()  # type: ignore[func-returns-value]

    print(f"\ndone {added}, skipped {skipped}, failed {failed}, notices removed {notices}")
    if not apply:
        print("nothing was changed.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", default="work", help="session doing the adding")
    parser.add_argument("--bot", required=True, help="the bot, e.g. @konnekt_cz_bot")
    parser.add_argument("--chats", type=Path, required=True, help="file of chat ids, one per line")
    parser.add_argument("--title", default="", help=f"admin title shown in the chat, up to {MAX_TITLE} characters")
    parser.add_argument("--sessions-dir", type=Path, default=SESSIONS_DIR)
    parser.add_argument("--journal", type=Path, help="JSONL file recording progress, so a run can resume")
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="also visit chats where the bot is already an admin, to clear notices left there earlier",
    )
    parser.add_argument("--min-delay", type=float, default=MIN_DELAY)
    parser.add_argument("--max-delay", type=float, default=MAX_DELAY)
    parser.add_argument("--apply", action="store_true", help="actually add; without it nothing is sent")
    args = parser.parse_args()

    return asyncio.run(
        run(
            account=args.account,
            bot=args.bot,
            scope=read_scope(args.chats),
            title=args.title,
            directory=args.sessions_dir,
            journal_path=args.journal,
            apply=args.apply,
            sweep=args.sweep,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
