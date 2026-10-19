# Production Credentials

Production configuration lives in **GitHub**, as repository secrets and
variables. The VPS holds no copy: the deploy workflow forwards everything over
SSH with the deploy command, so a value changes in one place and reaches the
host on the next deploy.

Nothing here belongs in commits, issues, agent transcripts, screenshots, or a
file on the server.

## Secrets

Credentials, and anything that is not public anyway. The repository is public,
so its workflow logs are too, and a variable is printed in them unmasked: the
ids of the people who run this, and where the databases are and what they are
called, belong here as much as passwords do. Once set, GitHub will not show
them again — rotate rather than recover.

| Secret | What it is |
| --- | --- |
| `DB_HOST`, `DB_USER`, `DB_NAME` | The shared PostgreSQL server, which listens publicly, and the bot's role and database on it |
| `DB_PASSWORD` | PostgreSQL password. The database runs beside this stack rather than in it, so this is the password that database already has — see [The Database](database.md). |
| `MODERATOR_BOT_TOKEN` | Bot token from BotFather |
| `MCP_TOKEN` | Bearer token for the control plane |
| `ADMIN_SUPER_ADMINS` | Comma-separated Telegram IDs |
| `ADMIN_REPORT_CHAT_ID` | Optional. Defaults to the first super admin |
| `CATALOG_DB_USER`, `CATALOG_DB_NAME` | Required. The catalog database's role and name, as its data directory has them |
| `CATALOG_DB_PASSWORD` | The catalog database's password: the one its data directory was created with (teachers-catalog's `POSTGRES_PASSWORD`). Changing it here does not change it there — see catalog/docs/deploy.md. |
| `CATALOG_OWNER_TG_ID` | Optional. Who the catalog tells about a first profile or request; should be one of `ADMIN_SUPER_ADMINS` so the ping's console button opens |
| `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY` | Deploy target and key |

`MCP_TOKEN` is the entire protection on a plane that can mute, unmute, unban and
read what the bot recorded. Generate with `openssl rand -hex 32`.

There is no Telegram **user session** in this deployment, deliberately. The
maintenance scripts under `scripts/` use one and run from a developer's
machine; nothing the deployed application does needs an account, and putting a
session on the server would make the most sensitive artefact in Telegram — one
that reads every private conversation the account can see — a deployment
artefact.

## Variables

What is public anyway. Printed in every public workflow log.

| Variable | Notes |
| --- | --- |
| `DB_PORT` | Optional, 5432 by default |
| `WEBAPI_PUBLIC_URL` | Required. The allowed CORS origin, and where the catalog's buttons and notifications open the app |
| `CATALOG_ADS_CONTACT` | Optional. The Telegram username the ads page offers |

## Features switch themselves on

Nothing here is switched on by a flag. A feature is on when it is configured
and off otherwise:

| Feature | On when |
| --- | --- |
| MCP control plane | `MCP_TOKEN` is set |

Everything the application does runs on the bot token. Titles, photos and
member counts are Bot API calls; message history and search read the rows the
bot recorded as it moderated. There is nothing left to switch on with an
account.

A separate flag could disagree with the configuration it gates, and only ever in
the direction that fails quietly: a flag saying a subsystem is on, over
credentials that are absent, produces one that starts, fails, and says nothing.

Some values are fixed in `docker-compose.yaml` rather than configured, because
they cannot differ without breaking something: the MCP port and path are pinned
to the container port mapping.

Anything absent falls back to the default in `app/core/config.py`. The list is
deliberately not a second copy of every setting — thresholds and intervals are
code, and changing them should be a reviewed change rather than a click.

## What the deploy checks

The deploy workflow's first step refuses to touch the host when a setting
without a default is empty; the list is in `.github/workflows/deploy.yml`,
not repeated here. A test pins the forwarded list against
`docker-compose.yaml`, so a setting added to one and not the other fails in
CI rather than in production.

## Seeding and changing values

`scripts/env_to_github.sh` loads an env file into this repository's secrets and
variables — the old VPS `.env` for the first migration, or any file afterwards.
It prints a plan and writes nothing until `--apply`, never prints a value, and
names anything it ignored so a setting that is about to stop taking effect is
visible rather than silently dropped.

```bash
scripts/env_to_github.sh ~/deploy/supervisor-telegram/.env
scripts/env_to_github.sh ~/deploy/supervisor-telegram/.env --apply
```

Run it from a machine that can read the file. Once the values are in GitHub,
delete the `.env` from the VPS: it is no longer read, and a stale copy of
production credentials is worth less than nothing.

## Rotation

1. Generate the new value.
2. Update the secret or variable in GitHub.
3. Re-run the deploy workflow — the new value reaches the host with the command.
4. Revoke the old value at its source: BotFather for bot tokens, the provider
   console for API keys, `ALTER ROLE` for the database.
5. Confirm the containers came up: the deploy log shows `docker compose ps`;
   read the services' logs on the host, since the workflow log is public.

Rotating `MCP_TOKEN` also means updating whatever client holds it.

## If a value leaks

Rotate first, investigate after. For `MCP_TOKEN`, check `pending_actions` for
proposals nobody made — the plane cannot ban on its own, so a leak shows up as
requests awaiting confirmation rather than as damage already done.
