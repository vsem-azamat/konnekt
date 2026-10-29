"""Which lanes the deploy may leave out: those the merged pull request's run passed on this very tree.

`scripts/tested_lanes.sh` runs in the deploy (deploy.yml, job `tested`) against
GitHub's API through `gh`. Here `gh` is a stand-in that answers from a table,
so every way the lookup can go wrong is a case.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "tested_lanes.sh"

MERGED = "a" * 40
TREE = "t" * 40
HEAD = "h" * 40

# The stand-in: each API path answers with the file of the same name, the
# artifact download copies the run's record, anything else fails as gh does.
FAKE_GH = r"""#!/usr/bin/env bash
set -euo pipefail
answers=${FAKE_GH_DIR:?}
if [ "$1" = api ]; then
  shift
  while [ "${1#-}" != "$1" ]; do shift; done
  key=$(printf '%s' "$1" | tr '/?&=' '____')
  [ -f "$answers/$key" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
  cat "$answers/$key"
  exit 0
fi
if [ "$1" = run ] && [ "$2" = download ]; then
  run=$3; shift 3
  dir=.
  while [ $# -gt 0 ]; do
    case "$1" in -D) dir=$2; shift 2 ;; *) shift ;; esac
  done
  [ -f "$answers/run_$run" ] || { echo "no artifact" >&2; exit 1; }
  mkdir -p "$dir"
  cp "$answers/run_$run" "$dir/tested.txt"
  exit 0
fi
exit 1
"""


def _key(path: str) -> str:
    return path.translate(str.maketrans("/?&=", "____"))


@pytest.fixture
def gh(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "gh").chmod(0o755)
    answers = tmp_path / "answers"
    answers.mkdir()
    return answers


def _answer(answers: Path, path: str, body: str) -> None:
    (answers / _key(path)).write_text(body)


def _merged_pull_request(answers: Path, *, runs: list[int]) -> None:
    repo = "o/r"
    _answer(answers, f"repos/{repo}/git/commits/{MERGED}", TREE + "\n")
    _answer(answers, f"repos/{repo}/commits/{MERGED}/pulls", "7\n")
    _answer(answers, f"repos/{repo}/pulls/7", HEAD + "\n")
    _answer(answers, f"repos/{repo}/pulls/7/files", "app/bot.py\nweb/src/App.tsx\n")
    path = f"repos/{repo}/actions/workflows/test.yml/runs?event=pull_request&head_sha={HEAD}"
    _answer(answers, path, "".join(f"{run}\n" for run in runs))


def _record(answers: Path, run: int, tree: str, **lanes: bool) -> None:
    body = f"tree={tree}\n" + "".join(f"{lane}={str(on).lower()}\n" for lane, on in lanes.items())
    (answers / f"run_{run}").write_text(body)


def _lanes(answers: Path) -> tuple[int, str]:
    env = {
        "PATH": f"{answers.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "FAKE_GH_DIR": str(answers),
        "REPO": "o/r",
        "SHA": MERGED,
        "HOME": str(answers.parent),
    }
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=answers.parent,
    )
    return result.returncode, result.stdout.strip()


def test_lanes_the_pull_request_passed_on_this_tree_are_left_out(gh: Path) -> None:
    _merged_pull_request(gh, runs=[11])
    _record(gh, 11, TREE, python=True, web=False, catalog=True)

    assert _lanes(gh) == (0, "lanes=python catalog")


def test_a_run_on_another_tree_counts_for_nothing(gh: Path) -> None:
    """Merged behind main: what was tested is not what main holds now."""
    _merged_pull_request(gh, runs=[11])
    _record(gh, 11, "x" * 40, python=True, web=True, catalog=True)

    assert _lanes(gh) == (0, "lanes=")


def test_the_run_on_this_tree_is_found_among_others(gh: Path) -> None:
    _merged_pull_request(gh, runs=[12, 11])
    _record(gh, 12, "x" * 40, python=True, web=True, catalog=True)
    _record(gh, 11, TREE, python=False, web=True, catalog=False)

    assert _lanes(gh) == (0, "lanes=web")


def test_a_run_without_a_record_counts_for_nothing(gh: Path) -> None:
    _merged_pull_request(gh, runs=[11])

    assert _lanes(gh) == (0, "lanes=")


def test_a_push_that_no_pull_request_merged_runs_everything(gh: Path) -> None:
    _answer(gh, f"repos/o/r/git/commits/{MERGED}", TREE + "\n")
    _answer(gh, f"repos/o/r/commits/{MERGED}/pulls", "")

    assert _lanes(gh) == (0, "lanes=")


def test_any_failure_of_the_lookup_runs_everything(gh: Path) -> None:
    """The API down must not stop a deploy, nor let one through untested."""
    assert _lanes(gh) == (0, "lanes=")


def test_a_record_naming_unknown_lanes_is_not_trusted(gh: Path) -> None:
    _merged_pull_request(gh, runs=[11])
    (gh / "run_11").write_text(f"tree={TREE}\npython=true\nweb=true\ncatalog=true\nrm -rf=true\n")

    assert _lanes(gh) == (0, "lanes=")


def test_a_record_with_a_value_other_than_true_or_false_is_not_trusted(gh: Path) -> None:
    _merged_pull_request(gh, runs=[11])
    (gh / "run_11").write_text(f"tree={TREE}\npython=yes\nweb=true\ncatalog=true\n")

    assert _lanes(gh) == (0, "lanes=")


@pytest.mark.parametrize("changed", [".github/workflows/test.yml", "scripts/tested_lanes.sh", ".githooks/lanes"])
def test_a_pull_request_that_changed_the_checks_is_tested_in_full(gh: Path, changed: str) -> None:
    """Its record was written by the checks it changed; the deploy does not take their word."""
    _merged_pull_request(gh, runs=[11])
    _answer(gh, "repos/o/r/pulls/7/files", f"app/bot.py\n{changed}\n")
    _record(gh, 11, TREE, python=True, web=True, catalog=True)

    assert _lanes(gh) == (0, "lanes=")
