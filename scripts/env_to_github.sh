#!/usr/bin/env bash
# Load an env file into GitHub repository secrets and variables.
#
# Production configuration lives in GitHub; this is how it gets there, whether
# seeding it the first time from the old VPS .env or changing it later.
#
#   scripts/env_to_github.sh path/to/.env            # show the plan
#   scripts/env_to_github.sh path/to/.env --apply    # write it
#
# Values are never printed, not on success and not on failure. Names are.
#
# Anything not listed below is skipped: those settings fall back to the default
# in app/core/config.py, and copying them here would create a second place to
# keep in step with the first.
set -euo pipefail

# Credentials, and anything not public anyway: this repository is public, and
# a variable is printed unmasked in its workflow logs. Readable by nobody once
# set — rotate rather than recover.
SECRETS="
DB_HOST
DB_USER
DB_NAME
DB_PASSWORD
MODERATOR_BOT_TOKEN
MCP_TOKEN
ADMIN_SUPER_ADMINS
ADMIN_REPORT_CHAT_ID
"

# Public anyway. Printed in every workflow log, so a token landing here by
# mistake is a leak — the split is deliberate.
VARIABLES="
DB_PORT
WEBAPI_PUBLIC_URL
"

env_file="${1:-}"
apply="${2:-}"

if [ -z "$env_file" ] || [ ! -f "$env_file" ]; then
  echo "usage: $0 <env-file> [--apply]" >&2
  exit 2
fi

command -v gh >/dev/null || { echo "gh CLI not found" >&2; exit 2; }
gh auth status >/dev/null 2>&1 || { echo "gh is not authenticated" >&2; exit 2; }

# Read one key without letting its value reach stdout or the shell history.
value_of() {
  sed -n "s/^$1=//p" "$env_file" | head -1 | sed 's/^"\(.*\)"$/\1/; s/^'"'"'\(.*\)'"'"'$/\1/'
}

plan_set() {   # kind name
  local kind="$1" name="$2" value
  value="$(value_of "$name")"

  if [ -z "$value" ]; then
    printf '  skip     %-34s (absent or empty)\n' "$name"
    return
  fi

  if [ "$apply" = "--apply" ]; then
    # Both subcommands read the value from stdin when --body is absent,
    # which keeps it off the command line and out of shell history.
    printf '%s' "$value" | gh "$kind" set "$name" >/dev/null
    printf '  set      %-34s (%s)\n' "$name" "$kind"
  else
    printf '  would set %-33s (%s)\n' "$name" "$kind"
  fi
}

if [ "$apply" != "--apply" ]; then
  echo "Plan only. Re-run with --apply to write."
fi
echo

echo "Secrets:"
for name in $SECRETS; do plan_set secret "$name"; done

echo
echo "Variables:"
for name in $VARIABLES; do plan_set variable "$name"; done

# Settings present in the file that this script deliberately ignores. Worth
# naming: a value someone set on purpose is about to stop taking effect.
echo
echo "Ignored (code defaults apply):"
# Unquoted on purpose: word-splitting collapses the newlines in the lists
# above into the single-space form the case pattern below matches against.
# shellcheck disable=SC2086
known=" $(echo $SECRETS $VARIABLES IMAGE_TAG) "
grep -oE '^[A-Z][A-Z0-9_]*' "$env_file" | sort -u | while read -r name; do
  case "$known" in *" $name "*) ;; *) printf '  %s\n' "$name" ;; esac
done

echo
if [ "$apply" = "--apply" ]; then
  echo "Done. Re-run the deploy workflow to pick the values up."
else
  echo "Nothing was written."
fi
