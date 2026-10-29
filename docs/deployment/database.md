# The database

It is not part of this stack. It is a database on the shared PostgreSQL
server, another machine than the one this stack runs on, and it holds the
production data, so `docker-compose.yaml` starts no `db` service and
where the database lives is deployment configuration: `DB_HOST`, `DB_USER`,
`DB_NAME` and `DB_PASSWORD` come from GitHub secrets and `DB_PORT` from a
variable. Only the password is a credential, but a variable is printed
unmasked in every log of this public repository, and the server listens
publicly.

That was a choice, made to keep one PostgreSQL server for several projects,
and it costs one thing worth knowing about — see *Exposure*.

## The database predates the migration squash

Thirty-six migrations were replaced by a single initial schema, and production,
built by the old history, was adopted onto it once, on 2026-07-31: the tables
the squash adds were created, then `alembic stamp fbeb70328d81 --purge`,
`alembic upgrade head` and `alembic check`. `--purge` is what makes the stamp
possible: without it Alembic first resolves the recorded revision, which no
longer exists. The stamp was a true statement rather than a promise: production
had every table of the squashed schema, apart from the column differences
below. Another database that predates the squash needs the same steps; `git log`
has the script that created the missing tables (`scripts/adopt_existing_db.py`,
removed once production was adopted).

Two follow-ups came out of it, both in `c8d5e2f47a19`: five columns the models
declare NOT NULL were nullable in production (no row violated them), and two
primary keys were `bigint` there against `Integer` in the models — production
was right, and the models moved.

## Tables this repository does not own

Production carried eight tables from features that had left: the content
pipeline's, the moderation agent's and the cost ledger's. `b6e1f4a8c203` dropped
them on 2026-10-29. The five that held rows were exported first, as a data-only
`pg_dump` and a CSV per table, to `~/data-archive/supervisor-telegram-2026-10-29/`
on the server and to Azamat's `~/Media/konnekt-requests/2026-10-29/data-archive/`.

`alembic/env.py` still keeps unmapped tables out of autogenerate, so a table
somebody adds by hand is never proposed for deletion.

## Exposure

The database server listens on its public interface, behind a source allowlist
and a password. Keeping that allowlist to the hosts that need it is the
database server's job; nothing in this repository can do it.

If it is ever moved inside the compose network, the data has to move with it —
`git log` has the import that does this, removed once this route was chosen.

## Migrations and going back

The deploy runs `alembic upgrade head` as a one-shot `migrate` job before bot
or webapi is recreated, so a failed migration stops the deploy with the old
release still serving. To go back, run the Deploy workflow by hand with the
sha of the release to return to and *migrate* switched off: its images already
exist, and the schema it finds was written to stay readable by it (see
docs/invariants.md). The workflow refuses a sha that is not on main or has no
published images.

Only releases from the one that introduced this job onward can be returned to
this way: an older image still migrates in its own entrypoint and would fail
on the newer revision. A push to main while a rollback waits for the deploy
lock cancels the rollback, and the next push redeploys main's head over it.

## Backups

The shared database server's own backup jobs do not cover this database. The
stack's `db-backup` service dumps it daily at 02:00 UTC with `pg_dump
--format=custom`, using the bot's own connection settings, into
`~/deploy/supervisor-telegram/db-backups/` (0700) on the application host, and
keeps 30 days. That is another machine than the database's, so losing either
one leaves the other. A dump is written to a `.part` file and renamed only on
success, and old dumps are pruned only after a successful one, so a database
that stops answering does not cost the dumps already taken.

The container turns unhealthy when its newest dump is two days old. Nothing
else watches the backups, so `docker ps` showing `unhealthy` is the signal. A
deploy's `--wait` fails on it too, but only after the new release is already
running: a red deploy with a backup container named in it is a backup problem,
not a reason to roll back. Once the cause is fixed, a dump by hand clears it
rather than waiting for the night's:

```sh
docker exec supervisor-telegram-db-backup sh -c \
  'pg_dump --format=custom --file=/backups/moderator-$(date -u +%Y%m%dT%H%M%SZ).dump'
```

### Restoring

First prove the dump restores, in a throwaway container with no network
(`scripts/restore_drill.sh` lives in the repository, not on the host):

```sh
ssh azamat 'cd ~/deploy/supervisor-telegram && bash -s -- db-backups/<file>.dump' \
  < scripts/restore_drill.sh
```

Then restore into a new database on the database server, next to the live one,
never over it: `createdb` a scratch name, `pg_restore --exit-on-error
--no-owner --no-privileges -d <scratch>`, check it, and only then stop `bot`
and `webapi` and swap the names in one transaction (`psql -v ON_ERROR_STOP=1
-1` with both `ALTER DATABASE ... RENAME TO`). The bot's role may lack
`CREATEDB` on the shared server, so this is done by whoever administers that
server. Hold deploys meanwhile, since a deploy starts what was stopped. The old
database stays under its new name until the restored one has proved itself,
then is dropped.

Drill on 2026-10-19 (supervisor-telegram#188): `moderator-20261019T020000Z.dump`,
13 MB, restored in 1–2 s into 21 tables at the current migration head, 73,606
messages and 2,688 users.
