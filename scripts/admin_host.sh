#!/usr/bin/env bash
# The host the console answers on, for the webui's Caddy, from WEBAPI_ADMIN_URL.
#
#   admin_host.sh <WEBAPI_ADMIN_URL> <WEBAPI_PUBLIC_URL>
#
# Unset gives a name no request carries: an empty one would make Caddy's site
# address `http://`, which answers every request. Refused, with nothing on
# stdout: a host equal to the Mini App's, which would take that site's traffic,
# and one with a port, a path or no https, which would match no request at all.
# The webapi checks the same URL when it starts (WebApiSettings).
set -euo pipefail

admin=${1:-}
public=${2:-}

if [ -z "$admin" ]; then
  echo admin.invalid
  exit 0
fi

fail() {
  echo "WEBAPI_ADMIN_URL $1" >&2
  exit 1
}

case "$admin" in
  https://*) ;;
  *) fail "must start with https://" ;;
esac
host=${admin#https://}
host=${host%/}
case "$host" in
  "" | */* | *:*) fail "must be a bare host: no port, no path" ;;
esac
host=$(printf '%s' "$host" | tr '[:upper:]' '[:lower:]')

public_host=${public#*://}
public_host=${public_host%%/*}
public_host=$(printf '%s' "$public_host" | tr '[:upper:]' '[:lower:]')
[ "$host" != "$public_host" ] || fail "must not be the Mini App's host"

printf '%s\n' "$host"
