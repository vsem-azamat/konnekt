"""The git hooks in `.githooks/` and the lanes they share with CI.

A lane is a set of checks that a change can make fail: `python` (the bot's
lint, types, migrations and pytest), `web` (the Mini App's) and `catalog`.
`.githooks/lanes` decides which lanes a list of changed paths touches; the
hooks run only those, and so do the PR jobs in `.github/workflows/test.yml`.
A path left out of a lane it can break is a CI failure nobody sees coming, so
the cases below are the ones where a check reads files outside its own tree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".githooks"
ZERO = "0" * 40


def _run(*args: str | Path, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=120, **kwargs)  # noqa: S603 — our own hooks and git


def _lanes(*paths: str) -> set[str]:
    result = _run(HOOKS / "lanes", input="\n".join(paths) + "\n", check=True)
    return {line.removesuffix("=true") for line in result.stdout.split() if line.endswith("=true")}


@pytest.mark.parametrize(
    ("paths", "lanes"),
    [
        (["app/bot.py"], {"python"}),
        (["alembic/versions/x.py"], {"python"}),
        (["docker-compose.yaml"], {"python"}),
        (["docker/Caddyfile"], {"python"}),
        (["web/package.json"], {"web"}),
        (["web/tests/a.test.ts"], {"web"}),
        # tests/unit/test_web_split.py reads the Mini App's sources.
        (["web/src/pages/Ads.tsx"], {"python", "web"}),
        # tests/unit/test_deploy_config.py looks for it.
        (["web/pnpm-workspace.yaml"], {"python", "web"}),
        (["catalog/src/students_cz/api.py"], {"catalog"}),
        # web/ generates its client from it.
        (["catalog/openapi.json"], {"catalog", "web"}),
        # Both projects must lock the same aiogram, which a root test checks.
        (["catalog/uv.lock"], {"catalog", "python"}),
        (["docs/invariants.md", "README.md", "web/README.md", "catalog/docs/x.md"], set()),
        # A change to the checks themselves runs all of them.
        ([".github/workflows/test.yml"], {"python", "web", "catalog"}),
        ([".githooks/pre-push"], {"python", "web", "catalog"}),
        (["app/bot.py", "web/package.json"], {"python", "web"}),
    ],
)
def test_a_change_runs_the_lanes_it_can_break(paths: list[str], lanes: set[str]) -> None:
    assert _lanes(*paths) == lanes


def test_every_lane_is_named_even_when_off() -> None:
    """CI reads each one as a step output; a missing name is an empty string, not false."""
    result = _run(HOOKS / "lanes", input="", check=True)

    assert result.stdout.split() == ["python=false", "web=false", "catalog=false"]


def test_ci_reads_the_lanes_from_the_same_script() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())

    for job in ("test", "catalog"):
        runs = "\n".join(str(step.get("run", "")) for step in workflow["jobs"][job]["steps"])
        assert ".githooks/lanes" in runs, job


def test_the_required_check_always_runs() -> None:
    """Branch protection requires `test (3.12)`; a job skipped as a whole would never report."""
    job = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())["jobs"]["test"]

    assert "if" not in job
    assert "needs" not in job


# The hooks against a scratch repository: a copy of the configuration they
# read, the project's own environment, no network.


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copytree(HOOKS, tmp_path / ".githooks")
    shutil.copy(ROOT / "pyproject.toml", tmp_path)
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    _run("git", "init", "-q", "-b", "main", tmp_path, check=True)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    return tmp_path


def _git(repo: Path, *args: str) -> str:
    identity = ("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false")
    return _run("git", "-C", repo, *identity, *args, check=True).stdout.strip()


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"UV_PROJECT_ENVIRONMENT": sys.prefix, "UV_NO_SYNC": "1", "UV_OFFLINE": "1"})
    env.pop("SKIP_HOOKS", None)
    return env


def _hook(
    repo: Path, name: str, stdin: str = "", env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return _run(repo / ".githooks" / name, cwd=repo, input=stdin, env=env or _env())


def _stage(repo: Path, path: str, text: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)
    _git(repo, "add", path)


def test_pre_commit_refuses_unformatted_python_and_names_the_fix(repo: Path) -> None:
    _stage(repo, "app/bad.py", "x = {  'a':1 }\n")

    result = _hook(repo, "pre-commit")

    assert result.returncode != 0
    assert "uv run ruff format app/bad.py" in result.stdout + result.stderr


def test_pre_commit_passes_formatted_python(repo: Path) -> None:
    _stage(repo, "app/good.py", 'x = {"a": 1}\n')

    result = _hook(repo, "pre-commit")

    assert result.returncode == 0, result.stdout + result.stderr


def test_a_skipped_lane_says_so_in_one_line(repo: Path) -> None:
    _stage(repo, "docs/notes.md", "notes\n")

    result = _hook(repo, "pre-commit")

    assert result.returncode == 0, result.stdout + result.stderr
    lines = (result.stdout + result.stderr).strip().splitlines()
    assert len(lines) == 1
    assert "skip" in lines[0]


def test_skip_hooks_skips_everything(repo: Path) -> None:
    _stage(repo, "app/bad.py", "x = {  'a':1 }\n")

    result = _hook(repo, "pre-commit", env={**_env(), "SKIP_HOOKS": "1"})

    assert result.returncode == 0


def test_pre_push_of_a_branch_deletion_checks_nothing(repo: Path) -> None:
    result = _hook(repo, "pre-push", f"(delete) {ZERO} refs/heads/gone {'1' * 40}\n")

    assert result.returncode == 0
    assert result.stdout + result.stderr == ""


def test_pre_push_checks_what_the_branch_changed_since_main(repo: Path) -> None:
    _stage(repo, "docs/notes.md", "notes\n")
    _git(repo, "commit", "-q", "-m", "docs")
    head = _git(repo, "rev-parse", "HEAD")

    result = _hook(repo, "pre-push", f"refs/heads/docs {head} refs/heads/docs {ZERO}\n")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "skip" in result.stdout + result.stderr
