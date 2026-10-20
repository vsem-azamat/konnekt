# Sourced by the hooks and by lanes. A check that runs prints one line; a
# failing one prints its output and the command that fixes it; skipped lanes
# share one line.

failed=0

# git hands a hook GIT_DIR, and with it set and no GIT_WORK_TREE, a git run
# from a subdirectory (make -C catalog, pnpm --dir web) takes that directory
# for the top of the tree. Found again from the working directory instead.
unset GIT_DIR GIT_WORK_TREE

# Paths a diff touches. A rename is its old path and its new one, or moving a
# file out of a lane would hide it from that lane; and names stay unquoted, or
# a non-ASCII one would start with a quote and match no lane.
changed() { git -c core.quotePath=false diff --no-renames --name-only "$@"; }

on() { grep -qx "$1=true" <<<"$lanes"; }

# Arguments quoted to paste back into a shell.
quoted() { local q; q=$(printf '%q ' "$@"); printf '%s' "${q% }"; }

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
    [ -z "$out" ] || printf '%s\n' "$out"
    printf 'FAIL  %s\n' "$name"
    [ -z "$fix" ] || printf '      fix: %s\n' "$fix"
    failed=1
  fi
}

# ruff on what is staged rather than on the working tree, so a partly staged
# file is checked as it will be committed: ruff_staged <project dir> check|format <paths...>
ruff_staged() {
  local dir=$1 mode=$2 path rc=0
  shift 2
  for path in "$@"; do
    if [ "$mode" = format ]; then
      git show ":$path" | uv run --locked --directory "$dir" ruff format --check -q --force-exclude --stdin-filename "${path#"$dir"/}" - \
        >/dev/null 2>&1 || { printf 'would reformat: %s\n' "$path"; rc=1; }
    else
      git show ":$path" | uv run --locked --directory "$dir" ruff check -q --force-exclude --stdin-filename "${path#"$dir"/}" - || rc=1
    fi
  done
  return "$rc"
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
