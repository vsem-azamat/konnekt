# Sourced by the hooks. A check that runs prints one line; a failing one
# prints its output and the command that fixes it; skipped lanes share one line.

failed=0

on() { grep -qx "$1=true" <<<"$lanes"; }

skipped_lanes() {
  local off
  off=$(grep '=false$' <<<"$lanes" | cut -d= -f1 | paste -sd, - | sed 's/,/, /g')
  [ -z "$off" ] || printf 'skip  %s: %s\n' "$off" "$1"
}

# check <name> <fix> <command...>; an empty <fix> means the output says what to do.
check() {
  local name=$1 fix=$2 start=$SECONDS out
  shift 2
  if out=$("$@" 2>&1); then
    printf 'ok    %s (%ss)\n' "$name" $((SECONDS - start))
  else
    printf '%s\n' "$out"
    printf 'FAIL  %s\n' "$name"
    [ -z "$fix" ] || printf '      fix: %s\n' "$fix"
    failed=1
  fi
}

# Generators the checks run rewrite files in place; what they leave behind
# differs from what is committed.
unchanged() { git diff --quiet -- "$1" && [ -z "$(git ls-files --others --exclude-standard -- "$1")" ]; }

locales_current() { pnpm --dir web exec lingui extract >/dev/null && unchanged web/src/locales; }
api_client_current() { pnpm --dir web api:generate >/dev/null && unchanged web/src/lib/generated; }

# A fresh worktree has no node_modules.
web_ready() {
  [ -d web/node_modules ] && return 0
  printf 'web   installing dependencies\n'
  pnpm --dir web install --frozen-lockfile --reporter=silent >/dev/null 2>&1 || {
    printf 'FAIL  pnpm install\n      fix: pnpm --dir web install --frozen-lockfile\n'
    failed=1
    return 1
  }
}

finish() {
  [ "$failed" -eq 0 ] && return 0
  printf 'Only if you must: git %s --no-verify, or SKIP_HOOKS=1.\n' "$1"
  exit 1
}
