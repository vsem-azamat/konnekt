#!/bin/sh
set -e

# Ensure venv is on PATH (set in Dockerfile but not always inherited by sh)
export PATH="/app/.venv/bin:$PATH"

echo "Running entrypoint..."

# Wait for remote PostgreSQL to be ready
./scripts/wait_for_postgres.sh

case "${1:-bot}" in
  # Migrations are a step of their own, run by the deploy before bot or webapi
  # starts: running them here let the new webapi serve the old schema.
  migrate)
    exec alembic upgrade head
    ;;
  bot)
    echo "Starting bot..."
    exec python -m app.presentation.telegram
    ;;
  webapi)
    echo "Starting webapi..."
    # Behind the web UI's Caddy, and reachable only on the stack's network, so
    # the forwarded client address is believed from any peer there; without it
    # every console session recorded the proxy's Docker address.
    exec uvicorn app.webapi.main:app --host 0.0.0.0 --port 8787 --proxy-headers --forwarded-allow-ips '*'
    ;;
  *)
    exec "$@"
    ;;
esac
