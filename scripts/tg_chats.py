"""List the group chats an account is in, arranged by its Telegram folders.

The step before handing administration over: knowing which chats are in scope.
The account that owns them has them sorted into folders already — universities,
dormitories, and so on — and that sorting is a better description of scope than
anything this repository could infer, so it is read rather than guessed at.

    uv run python scripts/tg_chats.py folders --account main
    uv run python scripts/tg_chats.py candidates --account main --folder студ --bot @konnekt_cz_bot

`folders` shows what folders exist and how many groups are in each. `candidates`
lists the groups themselves, with whether this account can appoint admins there
and, when a bot is named, whether that bot is present.

Private conversations are never touched
---------------------------------------
This reads a chat list, not chats. Groups and supergroups are the only thing it
keeps: a peer that is a user is dropped at the point it is read, before it is
looked up, printed or counted. Nothing here calls any method that returns
message contents — the whole file has no way to fetch a message, which is a
stronger guarantee than a rule about not printing them.

What it reports per chat is what an administrator sees in the chat's own
settings: title, id, member count, and who holds which rights.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tg_accounts import SESSIONS_DIR, api_credentials, session_path  # noqa: E402

if TYPE_CHECKING:
    from telethon import TelegramClient

# Telegram's own name for chats that are in no folder.
UNFILED = "(no folder)"


@dataclass
class Group:
    """One group chat, as its administrators see it in the chat's settings."""

    id: int
    title: str
    kind: str
    members: int | None
    i_am_admin: bool
    i_can_appoint: bool
    bot_status: str = ""
    folders: list[str] | None = None

    def row(self) -> list[str]:
        return [
            str(self.id),
            self.title,
            self.kind,
            "" if self.members is None else str(self.members),
            "admin" if self.i_am_admin else "member",
            "yes" if self.i_can_appoint else "no",
            self.bot_status,
            ", ".join(self.folders or []),
        ]


HEADER = ["chat_id", "title", "kind", "members", "my_standing", "can_appoint_admins", "bot", "folders"]


def _client(account: str, directory: Path) -> TelegramClient:
    from telethon import TelegramClient

    api_id, api_hash = api_credentials()
    path = session_path(account, directory=directory)
    if not path.exists():
        raise SystemExit(f"no session for {account!r} at {path} — run `tg_accounts.py login {account}` first")
    return TelegramClient(str(path.with_suffix("")), api_id, api_hash)


def _folder_title(raw: Any) -> str:
    """Folder titles became rich text in a later layer; both shapes appear."""
    return getattr(raw, "text", None) or str(raw)


def _peer_id(peer: Any) -> int | None:
    """The chat id behind a folder entry, or None when the entry is a person.

    This is where private conversations leave the program. A folder can hold
    users as well as groups, and the ones that are users are dropped here —
    before any lookup, so their identity is never resolved at all.
    """
    if hasattr(peer, "channel_id"):
        return int(peer.channel_id)
    if hasattr(peer, "chat_id"):
        return int(peer.chat_id)
    return None


async def read_folders(client: TelegramClient) -> dict[int, list[str]]:
    """Which folders each group belongs to, keyed by chat id.

    A chat can sit in several folders, so this is a list rather than a label.
    """
    from telethon.tl import functions

    result = await client(functions.messages.GetDialogFiltersRequest())
    filters = getattr(result, "filters", result)

    membership: dict[int, list[str]] = {}
    for entry in filters:
        peers = getattr(entry, "include_peers", None)
        if not peers:  # the default "All chats" pseudo-folder has none
            continue
        title = _folder_title(getattr(entry, "title", "?"))
        for peer in peers:
            chat_id = _peer_id(peer)
            if chat_id is not None:
                membership.setdefault(chat_id, []).append(title)
    return membership


async def read_groups(client: TelegramClient, folders: dict[int, list[str]]) -> list[Group]:
    """Every group and supergroup the account is in.

    `iter_dialogs` is the only way to enumerate them, and it returns private
    conversations too. Those are discarded on sight: the loop below keeps a
    title and an id from group entities and nothing else from anything.
    """
    from telethon.tl.types import Channel, Chat

    groups: list[Group] = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        is_supergroup = isinstance(entity, Channel) and entity.megagroup
        is_basic_group = isinstance(entity, Chat)
        if not (is_supergroup or is_basic_group):
            continue

        mine = await standing(client, entity)
        groups.append(
            Group(
                id=int(entity.id),
                title=getattr(entity, "title", "") or "",
                kind="supergroup" if is_supergroup else "group",
                members=getattr(entity, "participants_count", None),
                i_am_admin=mine[0],
                i_can_appoint=mine[1],
                folders=folders.get(int(entity.id), []),
            )
        )
    return groups


async def standing(client: TelegramClient, chat: Any) -> tuple[bool, bool]:
    """Whether we are an admin there, and whether we may appoint others.

    The second half is the one that matters: a chat where this account cannot
    appoint admins is a chat the handover cannot touch, and finding that out now
    is better than failing on it halfway through.
    """
    try:
        permissions = await client.get_permissions(chat, "me")
    except Exception:  # noqa: BLE001 — reported as "not an admin", never fatal
        return False, False
    is_admin = bool(permissions.is_admin or permissions.is_creator)
    can_appoint = bool(permissions.is_creator or getattr(permissions, "add_admins", False))
    return is_admin, can_appoint


async def check_bot(client: TelegramClient, groups: list[Group], bot: str) -> None:
    """Fill in where the bot already is, so the rollout knows what is left."""
    from telethon.errors import UserNotParticipantError

    entity = await client.get_entity(bot)
    for group in groups:
        try:
            permissions = await client.get_permissions(group.id, entity)
        except UserNotParticipantError:
            group.bot_status = "absent"
        except Exception:  # noqa: BLE001 — an unreadable member list is not a failure
            group.bot_status = "unknown"
        else:
            group.bot_status = "admin" if permissions.is_admin else "member"


def matches(group: Group, needle: str | None, excluded: list[str] | None = None) -> bool:
    """Whether this group is in scope.

    Exclusion wins over inclusion. The account keeps a personal folder, and a
    group filed there is out of scope however well it matches something else —
    a rule the program follows is worth more than one an operator has to
    remember while reading a list of sixty chats.
    """
    folders = group.folders or []
    for skip in excluded or []:
        lowered = skip.casefold()
        if any(lowered in folder.casefold() for folder in folders):
            return False
    if not needle:
        return True
    lowered = needle.casefold()
    return any(lowered in folder.casefold() for folder in folders)


async def run_folders(account: str, directory: Path) -> int:
    client = _client(account, directory)
    await client.start()  # type: ignore[func-returns-value]
    try:
        folders = await read_folders(client)
        counts: dict[str, int] = {}
        for titles in folders.values():
            for title in titles:
                counts[title] = counts.get(title, 0) + 1

        if not counts:
            print("this account has no folders")
            return 0
        width = max(len(title) for title in counts)
        for title, count in sorted(counts.items(), key=lambda item: -item[1]):
            print(f"{title:<{width}}  {count:>3} chats")
        return 0
    finally:
        await client.disconnect()  # type: ignore[func-returns-value]


async def run_candidates(
    account: str,
    directory: Path,
    *,
    folder: str | None,
    exclude: list[str] | None,
    bot: str | None,
    out: Path | None,
) -> int:
    client = _client(account, directory)
    await client.start()  # type: ignore[func-returns-value]
    try:
        folders = await read_folders(client)
        groups = await read_groups(client, folders)
        groups = [group for group in groups if matches(group, folder, exclude)]
        groups.sort(key=lambda group: (-(group.members or 0), group.title))

        if bot:
            await check_bot(client, groups, bot)

        title_width = min(44, max((len(group.title) for group in groups), default=10))
        print(f"{'chat_id':>15}  {'members':>7}  {'me':<7} {'appoint':<8} {'bot':<8} title")
        for group in groups:
            print(
                f"{group.id:>15}  {group.members or 0:>7}  "
                f"{'admin' if group.i_am_admin else 'member':<7} "
                f"{'yes' if group.i_can_appoint else 'NO':<8} "
                f"{group.bot_status or '-':<8} {group.title[:title_width]}"
            )
        print(
            f"\n{len(groups)} groups"
            f"{f' in folders matching {folder!r}' if folder else ''}"
            f", {sum(1 for g in groups if not g.i_can_appoint)} where this account cannot appoint admins"
        )

        if out:
            with out.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(HEADER)
                writer.writerows(group.row() for group in groups)
            print(f"written to {out}")
        return 0
    finally:
        await client.disconnect()  # type: ignore[func-returns-value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sessions-dir", type=Path, default=SESSIONS_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("folders", help="what folders this account has, and how many groups in each")
    listing.add_argument("--account", default="main")

    candidates = sub.add_parser("candidates", help="the group chats themselves")
    candidates.add_argument("--account", default="main")
    candidates.add_argument("--folder", help="only folders whose name contains this, case-insensitive")
    candidates.add_argument(
        "--exclude-folder",
        action="append",
        default=["Личные"],
        help="skip folders whose name contains this; repeatable, and it wins over --folder",
    )
    candidates.add_argument("--bot", help="also report whether this bot is present, e.g. @konnekt_cz_bot")
    candidates.add_argument("--out", type=Path, help="also write the list as CSV")

    args = parser.parse_args()

    if args.command == "folders":
        return asyncio.run(run_folders(args.account, args.sessions_dir))
    return asyncio.run(
        run_candidates(
            args.account,
            args.sessions_dir,
            folder=args.folder,
            exclude=args.exclude_folder,
            bot=args.bot,
            out=args.out,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
