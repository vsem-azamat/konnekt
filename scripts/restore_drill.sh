#!/usr/bin/env bash
# Restore a dump into a throwaway Postgres and show what came back.
#
#   scripts/restore_drill.sh db-backups/moderator-<stamp>.dump
#   scripts/restore_drill.sh catalog-backups/catalog-<stamp>.dump
#
# Run on the host, from ~/deploy/supervisor-telegram. The container has no
# network and is removed on exit, so this cannot reach the live databases
# whatever the dump contains: it proves a dump restores without touching
# anything that serves. Fails on the first restore error.
set -euo pipefail

dump=${1:?usage: restore_drill.sh <file.dump>}
[ -f "$dump" ] || { echo "no such dump: $dump" >&2; exit 1; }

docker run --rm --network none --memory 2g \
  -v "$(realpath "$dump"):/in/backup.dump:ro" \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  --entrypoint bash pgvector/pgvector:0.8.6-pg18-bookworm -c '
    set -euo pipefail
    docker-entrypoint.sh postgres > /tmp/pg.log 2>&1 &
    for _ in $(seq 60); do psql -U postgres -tAc "select 1" > /dev/null 2>&1 && break; sleep 1; done
    createdb -U postgres drill
    start=$(date +%s)
    pg_restore --no-owner --no-privileges --exit-on-error -U postgres -d drill /in/backup.dump
    echo "restored in $(( $(date +%s) - start ))s"
    q() { psql -U postgres -d drill -tAc "$1"; }
    q "analyze" > /dev/null
    echo "tables: $(q "select count(*) from information_schema.tables where table_schema = '"'public'"'")"
    echo "alembic: $(q "select version_num from alembic_version")"
    q "select relname || '"' '"' || n_live_tup from pg_stat_user_tables order by n_live_tup desc limit 8"
  '
