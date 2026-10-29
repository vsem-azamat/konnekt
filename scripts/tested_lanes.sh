#!/usr/bin/env bash
# The lanes the deploy may leave out, as `lanes=<names>` for $GITHUB_OUTPUT:
# those the merged pull request's run of test.yml passed on the very tree that
# main now holds (its job `tested` records them).
#
#   REPO=owner/name SHA=<commit pushed to main> tested_lanes.sh
#
# Anything short of that proof prints `lanes=` and the deploy runs every lane:
# a push no pull request merged, a pull request merged behind main (another
# tree), a run without a record, a record it cannot read, or the API failing.
# Never exits non-zero, so a lookup that fails cannot stop a deploy.
set -uo pipefail

lookup() {
  local tree pr head runs run dir record lanes line name value
  tree=$(gh api "repos/$REPO/git/commits/$SHA" --jq .tree.sha) || return 1
  pr=$(gh api "repos/$REPO/commits/$SHA/pulls" --jq '[.[] | select(.merged_at != null)][0].number // empty') || return 1
  [ -n "$pr" ] || return 1
  head=$(gh api "repos/$REPO/pulls/$pr" --jq .head.sha) || return 1
  runs=$(gh api "repos/$REPO/actions/workflows/test.yml/runs?event=pull_request&head_sha=$head" \
    --jq '.workflow_runs[].id') || return 1

  for run in $runs; do
    dir=$(mktemp -d)
    gh run download "$run" -R "$REPO" -n tested -D "$dir" > /dev/null 2>&1 || continue
    record="$dir/tested.txt"
    [ -f "$record" ] || continue
    [ "$(sed -n 's/^tree=//p' "$record")" = "$tree" ] || continue

    lanes=""
    while IFS= read -r line; do
      name=${line%%=*}
      value=${line#*=}
      case "$name" in
        tree) ;;
        python | web | catalog)
          case "$value" in
            true) lanes="$lanes $name" ;;
            false) ;;
            *) return 1 ;;
          esac
          ;;
        *) return 1 ;;
      esac
    done < "$record"
    echo "${lanes# }"
    return 0
  done
  return 1
}

if lanes=$(lookup); then
  echo "lanes=$lanes"
else
  echo "lanes="
fi
