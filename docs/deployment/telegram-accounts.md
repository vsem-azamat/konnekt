# Telegram accounts

These are for the maintenance scripts under `scripts/`, which run from a
developer's machine. The deployed application has no user session and does not
want one — see [production credentials](production-credentials.md).

Two user accounts are involved in running these chats, and they are not
interchangeable:

- **main** — the personal account that owns the chats today.
- **work** — the account that is to take administration over, so the personal
  one can step back from day-to-day management.

They exist as separate sessions on purpose. Telethon keeps an authorisation key
in the session file, so one file for both accounts means whichever signed in
last quietly replaced the other — and the failure only shows up later, as the
wrong account doing something.

## Signing in

Needs an application registered at <https://my.telegram.org>; the same
`api_id`/`api_hash` pair serves both accounts, because it identifies the
application rather than the account.

```bash
export TELETHON_API_ID=...
export TELETHON_API_HASH=...

uv run python scripts/tg_accounts.py login main
uv run python scripts/tg_accounts.py login work
```

Each prompts for a phone number, the code Telegram sends to that account, and a
two-step password if one is set — so it has to be run by whoever can read the
code. Signing in again on an account that is already authorised does nothing.

## Checking

```bash
uv run python scripts/tg_accounts.py status
```

```
main       authorised    @azamat (id 268388996)
work       authorised    @work_azamat (id ...)
```

This one never prompts. It is what anything unattended runs before acting, to
confirm it is the account it believes it is; a session that was revoked from
Telegram's own device list shows up here as `NOT AUTHORISED` rather than as a
confusing permission error halfway through a job.

## What a session file is

`.creds/sessions/<account>.session` is not a token scoped to this tool. Whoever
holds it can read every chat and message that account can, send as it, and change
its settings — Telegram sees no difference between the file and the person.

- `.creds/` is ignored by git, and nothing there belongs in a backup that leaves
  this machine.
- Deleting the file only makes it unusable here. Actually revoking access means
  ending the session from Telegram's **Devices** list.
- The deployment has no session of its own to confuse these with. It used to
  mount one; nothing in the application needs an account any more.

## Handing administration over

Which chats are in scope comes from the account's own Telegram folders — it has
them sorted by university already, and that sorting describes the perimeter
better than anything this repository could infer:

```bash
uv run python scripts/tg_chats.py folders --account main
uv run python scripts/tg_chats.py candidates --account main --bot @konnekt_cz_bot --out chats.csv
```

Discovery reads a chat list, never a chat. Private conversations are dropped
where the folder is parsed, and the file contains no call that returns message
contents. The personal folder is excluded by default, and exclusion beats any
`--folder` match.

Then the promotion pass, over a scope file of chat ids:

```bash
uv run python scripts/tg_promote.py --account main --target @work_azamat --chats scope.txt        # plan
uv run python scripts/tg_promote.py --account main --target @work_azamat --chats scope.txt --apply
```

It grants every administrator right, including `add_admins` — the second account
has to be able to invite the bot back and to hand over in turn. It never
transfers ownership, and it never demotes, removes or leaves anything: the
personal account keeps what it has until a person removes it by hand.

Pacing is the part that matters. Telegram reads a burst of membership changes as
spam and limits the account doing the appointing — the one that owns the chats.
Delays between writes are randomised, a flood wait is obeyed rather than retried
through, and `PEER_FLOOD` stops the run. Pass `--journal` so a stopped run
resumes instead of starting over.

Only once the second account is verified to work does it make sense to take
anything away from the first.
