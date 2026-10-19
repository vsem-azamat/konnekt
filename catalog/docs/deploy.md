# Deployment

The catalog ships with the rest of this repository: the same workflow, the
same host, the same compose file. Its services are the `catalog-*` ones in
the root `docker-compose.yaml`, and the Mini App's router (`docker/Caddyfile`)
sends `/api/v1/*` and `/healthz` to `catalog-api` inside the stack.

```
client → Cloudflare → the host's edge Caddy → webui (docker/Caddyfile)
                                                ├─ /api/v1/*, /healthz → catalog-api → catalog-postgres
                                                ├─ /api/*              → webapi
                                                └─ everything else     → the Mini App
```

Nothing but the bot token and the admin ids is shared with the bot and webapi:
the catalog has its own image, database and settings.

## How a deployment happens

A push to `main` runs **Deploy** (`.github/workflows/deploy.yml`):

1. The test workflow, the catalog job included, must pass.
2. The catalog image is built from `catalog/` and pushed as
   `ghcr.io/vsem-azamat/supervisor-telegram:catalog-<sha>`, a tag of the
   bot's public package: a new package would start private, and the host
   pulls without a login.
3. On the host: pull; prove `CATALOG_DB_*` against whichever Postgres holds
   the data now, before anything stops; stop everything else on the catalog's
   volume (see «The database»); start `catalog-postgres` and wait for it; run
   `catalog-migrate`, then `catalog-embed`, each to completion; then
   `docker compose up -d --wait` for everything. A failed migration stops the
   deploy before the new API serves. A deploy is never cancelled midway: the
   next push waits for it.

Configuration travels with the deploy command, never as a file on the host;
the catalog's names are in `docs/deployment/production-credentials.md`.

### Reference data does not ship with the code

Migrations run on every deploy; `students_cz.db.seed` — subjects,
institutions, service types, languages — never does. It is a development and
CI convenience, and production was seeded once.

So a change to `seed.py` alone reaches every fresh checkout and never reaches
the catalog people are using. Anything that has to take effect in production
needs a migration carrying the same change, and the migration writes the
values out rather than importing the constant: a migration describes the
database at one moment, and one that follows a constant changes meaning the
next time that constant does. `tests/test_service_groups.py` compares the seed
with the migrations.

## The database

`catalog-postgres` runs on the volume the catalog's previous stack created,
`konnekt_postgres-data`, declared external and by that name: a compose volume
is `<project>_<name>`, and any other declaration would be a new, empty
database that the API serves as if nothing were wrong. The role and the
database inside it are `CATALOG_DB_USER` and `CATALOG_DB_NAME`, and
`CATALOG_DB_PASSWORD` is the password they were created with; changing the
secret does not change the database.

Two Postgres servers on one data directory corrupt it, and Postgres's own
lock cannot see across containers. Until 30 September 2026 the catalog ran
from the `teachers-catalog` repository as the compose project `students-cz`,
on this same volume; that repository has no deploy workflow any more. Every
deploy here still stops that project, then any other container on the volume,
before `catalog-postgres` starts — a no-op once they are gone.

The shared database server the bot uses is a different machine; the catalog
does not use it.

## Rolling back

A release of the catalog: revert on `main`, or run the Deploy workflow by hand
with the older sha and *migrate* off; its image is still in the registry under
`catalog-<sha>`. That runs the older catalog, `catalog-embed` included, against
the newer schema, so the catalog's migrations follow the app's rule: each one
leaves a schema the previous release still runs on (docs/invariants.md).
Migrations do not run backwards; reversing a schema change is its own,
deliberate decision.

The pre-move stack is gone: its containers were removed on 30 September 2026,
once the catalog had been checked end to end from here. Undoing the move means
reverting #141 here and teachers-catalog #61, which removed that repository's
deploy, then deploying from there; its data is the same volume, and its last dumps are in
`~/deploy/teachers-catalog/data/backups/`.

## Two ways to break production

**Asking for updates with this token.** The token is the moderator bot's, and
the bot service receives its updates by polling. Telegram gives a token one
consumer. A `setWebhook` from anywhere stops that polling, and a second
`getUpdates` makes the two pollers fail each other with `409 Conflict`. The
catalog never does either. The legacy bot polls, so never run it with this
token. See [legacy-bot.md](legacy-bot.md).

**More than one Uvicorn worker.** The connection pool is per process, and the
`--workers 1` pin in the Dockerfile is what makes `db_pool_size` and
`db_max_overflow` the whole budget against Postgres — 15 connections by
default. Raising the worker count multiplies it.

## Backups

`catalog-backup` runs `pg_dump --format=custom` daily at 03:00 UTC into
`~/deploy/supervisor-telegram/catalog-backups/` and keeps two weeks. A dump is
written to a `.part` file and renamed only on success, so a partial file is
never taken for a usable one. The dumps from before the move are in
`~/deploy/teachers-catalog/data/backups/`.

They sit on the same disk as the database, which protects against a bad
migration and not against losing the machine. Copying them off the host is not
set up yet.

Old dumps are pruned only after a successful one, and the container turns unhealthy
once its newest dump is two days old; see `docs/deployment/database.md`.

To restore, prove the dump first in a throwaway container with no network,
which cannot reach the live database:

```sh
ssh azamat 'cd ~/deploy/supervisor-telegram && bash -s -- catalog-backups/<file>.dump' \
  < scripts/restore_drill.sh
```

Then restore beside the live database, never over it, and swap. On the host,
from `~/deploy/supervisor-telegram`; the catalog's role is a superuser, which
`CREATE EXTENSION vector` needs:

```sh
docker exec supervisor-telegram-catalog-postgres sh -c 'createdb -U "$POSTGRES_USER" catalog_restore'
docker exec -i supervisor-telegram-catalog-postgres sh -c 'pg_restore --exit-on-error --no-owner \
  --no-privileges -U "$POSTGRES_USER" -d catalog_restore' < catalog-backups/<file>.dump
docker stop supervisor-telegram-catalog-api       # nothing may hold the live database
# One transaction: a rename that fails leaves both names where they were.
docker exec supervisor-telegram-catalog-postgres sh -c 'psql -v ON_ERROR_STOP=1 -1 -U "$POSTGRES_USER" -d postgres \
  -c "ALTER DATABASE \"$POSTGRES_DB\" RENAME TO catalog_before_restore" \
  -c "ALTER DATABASE catalog_restore RENAME TO \"$POSTGRES_DB\""'
docker start supervisor-telegram-catalog-api
```

`catalog_before_restore` stays until the restored database has proved itself,
then is dropped, or the next swap has nowhere to put the old one. Hold deploys
meanwhile: a deploy starts whatever was stopped.

Drill on 2026-10-19 (supervisor-telegram#188): `catalog-20261019T030000Z.dump`,
4.5 MB, restored in under a second into 34 tables at the current migration
head, 135 institutions and 98 subjects.

## Checking on it

```sh
curl https://konnekt.azamat.io/healthz                 # API and database
docker ps --filter name=supervisor-telegram-catalog
docker logs -f supervisor-telegram-catalog-api
```

`docker compose` by hand on the host needs the deploy's variables exported
and refuses without them; `docker` alone does not.

`/healthz` answers `status`, `database` and `uptime_seconds`. It says nothing
about Telegram: the catalog holds no webhook. Whether the bot hears people is
the bot's own health check.

A person who opens the app from the bot is recorded with `bot_can_message`
true, from Telegram's `allows_write_to_pm`; nobody can be notified otherwise.
After a change to sign-in, check one fresh row in `users`.

`tutors.azamat.io`, the catalog's old address, answers 301 to the same path on
konnekt.azamat.io from the host's edge Caddy. That was set by hand after the
first deploy from here, which had to succeed first: until then the app's
router still proxied to it. The edge Caddyfile is shared, so change it with a
backup, `caddy validate` and a reload.
