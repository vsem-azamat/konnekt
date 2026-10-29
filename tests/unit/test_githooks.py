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
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".githooks"
ZERO = "0" * 40


def _outside_git() -> dict[str, str]:
    """The environment without git's: run from a hook, as pre-push runs these
    tests, GIT_DIR names the pushing worktree, and a `git init` elsewhere
    would reinitialise that repository as bare."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _run(*args: str | Path, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    kwargs.setdefault("env", _outside_git())
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
        # tests/unit/test_deploy_config.py reads its packageManager.
        (["web/package.json"], {"python", "web"}),
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
        # And the tool versions of these.
        (["catalog/Dockerfile"], {"catalog", "python"}),
        (["catalog/compose.dev.yml"], {"catalog", "python"}),
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

    for job in ("changes", "catalog"):
        runs = "\n".join(str(step.get("run", "")) for step in workflow["jobs"][job]["steps"])
        assert ".githooks/lanes" in runs, job


def test_the_required_check_always_runs() -> None:
    """Branch protection requires `test (3.12)`; a job skipped as a whole would never report."""
    job = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())["jobs"]["test"]

    assert job["if"] == "always()"
    assert job["strategy"]["matrix"]["python-version"] == ["3.12"]


def _gate(results: str, draft: str = "false") -> int:
    """The required check's step, given what the jobs it waits on ended as."""
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())
    (step,) = [
        step
        for step in workflow["jobs"]["test"]["steps"]
        if step.get("name") == "Every lane this change touches passed"
    ]
    env = {**_outside_git(), "RESULTS": results, "DRAFT": draft}
    return _run("bash", "-e", "-c", step["run"], env=env).returncode


def test_the_required_check_waits_on_every_lane_of_the_bots() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())
    lanes = {name for name, job in workflow["jobs"].items() if "if" in job and "changes" in str(job["if"])}

    assert lanes == {"python", "web", "images"}
    assert set(workflow["jobs"]["test"]["needs"]) == {"changes", "routes", "catalog", *lanes}
    (step,) = [
        step
        for step in workflow["jobs"]["test"]["steps"]
        if step.get("name") == "Every lane this change touches passed"
    ]
    assert step["env"]["RESULTS"] == "${{ join(needs.*.result, ' ') }}"


@pytest.mark.parametrize(
    "results",
    [
        "success success success success success skipped",
        "success success skipped skipped success skipped",
        "success success success skipped success skipped",
    ],
)
def test_the_required_check_passes_lanes_that_passed_or_were_not_needed(results: str) -> None:
    assert _gate(results) == 0


@pytest.mark.parametrize(
    "results",
    [
        "success success failure success success skipped",
        "success success cancelled skipped success skipped",
        "failure success skipped skipped success skipped",
        "success success success success failure skipped",
        # Fewer results than jobs: the expression read something else.
        "",
        "success success success",
    ],
)
def test_the_required_check_fails_a_lane_that_did_not_pass(results: str) -> None:
    assert _gate(results) != 0


def test_the_required_check_fails_a_draft() -> None:
    """Its green would stand for the ready run's until that run's lanes finish."""
    assert _gate("success success skipped skipped skipped skipped", draft="true") != 0


# The hooks against a scratch repository: a copy of the configuration they
# read, the project's own environment, no network.


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copytree(HOOKS, tmp_path / ".githooks")
    shutil.copy(ROOT / "pyproject.toml", tmp_path)
    shutil.copy(ROOT / "uv.lock", tmp_path)
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
    env = _outside_git()
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
    assert "uv run ruff format --force-exclude app/bad.py" in result.stdout + result.stderr


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


def _commit(repo: Path, message: str = "change") -> str:
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_lanes_counts_a_renamed_file_where_it_was(repo: Path) -> None:
    (repo / "docs").mkdir()
    _git(repo, "mv", "app/__init__.py", "docs/init.md")
    _commit(repo)

    assert "python=true" in _run(repo / ".githooks" / "lanes", "HEAD^", "HEAD", cwd=repo, check=True).stdout


def test_lanes_reads_a_non_ascii_name_as_it_is(repo: Path) -> None:
    _stage(repo, "docs/заметка.md", "notes\n")
    _commit(repo)

    result = _run(repo / ".githooks" / "lanes", "HEAD^", "HEAD", cwd=repo, check=True)

    assert "=true" not in result.stdout


# The lanes step of each job in test.yml, run as Actions runs it.


def _lanes_steps() -> list[Any]:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())
    steps = []
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if step.get("id") == "lanes":
                workdir = job.get("defaults", {}).get("run", {}).get("working-directory", ".")
                steps.append(pytest.param(workdir, step["run"], id=workdir))
    return steps


def _ci_step(
    repo: Path, workdir: str, script: str, draft: str = "false", event: str = "pull_request", tested: str = ""
) -> tuple[int, str]:
    (repo / workdir).mkdir(exist_ok=True)
    output = repo / "github_output"
    output.write_text("")
    env = {
        **_env(),
        "GITHUB_EVENT_NAME": event,
        "GITHUB_OUTPUT": str(output),
        "DRAFT": draft,
        "TESTED": tested,
    }
    result = _run("bash", "-e", "-c", script, cwd=repo / workdir, env=env)
    return result.returncode, output.read_text()


def test_both_jobs_have_a_lanes_step() -> None:
    assert [param.id for param in _lanes_steps()] == [".", "catalog"]


@pytest.mark.parametrize(("workdir", "script"), _lanes_steps())
def test_the_ci_lanes_step_fails_when_it_cannot_diff(tmp_path: Path, workdir: str, script: str) -> None:
    """Every lane off would pass the required check with nothing checked."""
    shutil.copytree(HOOKS, tmp_path / ".githooks")

    code, output = _ci_step(tmp_path, workdir, script)

    assert code != 0
    assert "=false" not in output


@pytest.mark.parametrize(("workdir", "script"), _lanes_steps())
def test_the_ci_lanes_step_reads_the_pull_requests_change(repo: Path, workdir: str, script: str) -> None:
    (repo / "docs").mkdir()
    _git(repo, "mv", "app/__init__.py", "docs/init.md")
    _commit(repo)

    code, output = _ci_step(repo, workdir, script)

    assert code == 0
    assert "python=true" in output.split()


@pytest.mark.parametrize(("workdir", "script"), _lanes_steps())
def test_a_draft_runs_no_lane_and_still_reports(repo: Path, workdir: str, script: str) -> None:
    """Marking it ready (ready_for_review) runs the lanes its change touches."""
    _stage(repo, ".github/workflows/test.yml", "on: push\n")
    _commit(repo)

    code, output = _ci_step(repo, workdir, script, draft="true")

    assert code == 0
    assert sorted(output.split()) == ["catalog=false", "python=false", "web=false"]


@pytest.mark.parametrize(("workdir", "script"), _lanes_steps())
def test_main_runs_every_lane(repo: Path, workdir: str, script: str) -> None:
    """A push or the deploy's workflow_call has no pull request, so no draft flag."""
    code, output = _ci_step(repo, workdir, script, draft="", event="push")

    assert code == 0
    assert sorted(output.split()) == ["catalog=true", "python=true", "web=true"]


def test_ci_reruns_when_a_draft_is_marked_ready() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())

    assert "ready_for_review" in workflow[True]["pull_request"]["types"]


@pytest.mark.parametrize(("workdir", "script"), _lanes_steps())
def test_a_change_to_the_checks_runs_every_lane_in_ci(repo: Path, workdir: str, script: str) -> None:
    _stage(repo, ".github/workflows/test.yml", "on: push\n")
    _commit(repo)

    _, output = _ci_step(repo, workdir, script)

    assert sorted(output.split()) == ["catalog=true", "python=true", "web=true"]


def test_pre_commit_checks_the_staged_content_not_the_working_tree(repo: Path) -> None:
    _stage(repo, "app/bad.py", "x = {  'a':1 }\n")
    (repo / "app" / "bad.py").write_text('x = {"a": 1}\n')

    result = _hook(repo, "pre-commit")

    assert result.returncode != 0, result.stdout + result.stderr
    assert "would reformat: app/bad.py" in result.stdout


def test_pre_commit_passes_staged_content_that_is_clean(repo: Path) -> None:
    _stage(repo, "app/good.py", 'x = {"a": 1}\n')
    (repo / "app" / "good.py").write_text("x = {  'a':1 }\n")

    result = _hook(repo, "pre-commit")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "unstaged edits in: app/good.py" in result.stdout


def test_pre_commit_runs_the_lane_a_file_was_moved_out_of(repo: Path) -> None:
    (repo / "docs").mkdir()
    _git(repo, "mv", "app/__init__.py", "docs/init.md")

    result = _hook(repo, "pre-commit")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok    ty" in result.stdout


def test_pre_commit_reads_a_non_ascii_name_as_it_is(repo: Path) -> None:
    _stage(repo, "docs/заметка.md", "notes\n")

    result = _hook(repo, "pre-commit")

    assert result.stdout.strip().splitlines() == [
        "skip  all checks: nothing staged that python, web or catalog read"
    ], result.stdout + result.stderr


def test_the_fix_quotes_a_path_for_the_shell(repo: Path) -> None:
    _stage(repo, "app/my module.py", "x = {  'a':1 }\n")

    result = _hook(repo, "pre-commit")

    assert "uv run ruff format --force-exclude app/my\\ module.py" in result.stdout


def test_pre_push_refuses_while_uncommitted_edits_would_be_checked(repo: Path) -> None:
    _stage(repo, "app/x.py", "x = 1\n")
    head = _commit(repo)
    (repo / "app" / "x.py").write_text("x = 2\n")

    result = _hook(repo, "pre-push", f"refs/heads/b {head} refs/heads/b {ZERO}\n")

    assert result.returncode != 0
    assert "app/x.py" in result.stdout
    assert "pytest" not in result.stdout


def test_pre_push_of_a_commit_not_checked_out_says_it_checked_nothing(repo: Path) -> None:
    _stage(repo, "app/x.py", "x = 1\n")
    _commit(repo)
    base = _git(repo, "rev-parse", "HEAD^")

    result = _hook(repo, "pre-push", f"refs/heads/b {base} refs/heads/b {ZERO}\n")

    assert result.returncode == 0
    assert result.stdout == "skip  refs/heads/b: not checked out here\n"


def test_these_tests_leave_the_repository_that_runs_them_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pushing = tmp_path / "pushing"
    _run("git", "init", "-q", pushing, check=True)
    monkeypatch.setenv("GIT_DIR", str(pushing / ".git"))

    _run("git", "init", "-q", tmp_path / "scratch", check=True)

    assert _run("git", "-C", pushing, "config", "core.bare").stdout.strip() == "false"


def test_a_check_in_a_subdirectory_reads_this_repository(repo: Path) -> None:
    """git hands a hook GIT_DIR; with it set, `make -C catalog` would take catalog/ for the top."""
    script = 'cd "$1" && . .githooks/_lib.sh && cd app && git rev-parse --show-toplevel'
    env = {**_outside_git(), "GIT_DIR": str(repo / ".git")}

    result = _run("bash", "-c", script, "-", repo, env=env, check=True)

    assert result.stdout.strip() == str(repo)


@pytest.mark.parametrize(("workdir", "script"), _lanes_steps())
def test_the_ci_lanes_step_fails_unless_lanes_names_all_three(repo: Path, workdir: str, script: str) -> None:
    (repo / ".githooks" / "lanes").write_text("#!/usr/bin/env bash\necho python=true\n")
    _stage(repo, "app/x.py", "x = 1\n")
    _commit(repo)

    code, output = _ci_step(repo, workdir, script)

    assert code != 0
    assert output == ""


def test_pre_push_checks_a_tag_on_the_checked_out_commit(repo: Path) -> None:
    _stage(repo, "docs/notes.md", "notes\n")
    head = _commit(repo)
    _git(repo, "tag", "-a", "v1", "-m", "v1")
    tag = _git(repo, "rev-parse", "v1")

    result = _hook(
        repo, "pre-push", f"refs/heads/b {head} refs/heads/b {ZERO}\nrefs/tags/v1 {tag} refs/tags/v1 {ZERO}\n"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "not checked out" not in result.stdout
    assert "nothing changed since main" in result.stdout


def test_pre_push_still_checks_head_beside_a_ref_that_is_not_checked_out(repo: Path) -> None:
    _stage(repo, "docs/notes.md", "notes\n")
    head = _commit(repo)
    base = _git(repo, "rev-parse", "HEAD^")

    result = _hook(
        repo, "pre-push", f"refs/heads/old {base} refs/heads/old {ZERO}\nrefs/heads/b {head} refs/heads/b {ZERO}\n"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[0] == "skip  refs/heads/old: not checked out here"
    assert "nothing changed since main" in result.stdout


def test_pre_push_ignores_new_files_where_no_check_reads(repo: Path) -> None:
    _stage(repo, "app/x.py", "x = 1\n")
    head = _commit(repo)
    (repo / "notes.txt").write_text("scratch\n")

    result = _hook(repo, "pre-push", f"refs/heads/b {head} refs/heads/b {ZERO}\n")

    assert "uncommitted" not in result.stdout


def test_pre_commit_leaves_what_ruff_excludes_alone(repo: Path) -> None:
    """The catalog's migrations are generated and excluded; on stdin ruff only knows if told to look."""
    (repo / "catalog").mkdir()
    shutil.copy(ROOT / "catalog" / "pyproject.toml", repo / "catalog")
    shutil.copy(ROOT / "catalog" / "uv.lock", repo / "catalog")
    (repo / "catalog" / "tests").mkdir()
    (repo / "catalog" / "tests" / "__init__.py").write_text("")
    _stage(repo, "catalog/src/students_cz/db/migrations/versions/x.py", "import os\nx = {  'a':1 }\n")

    result = _hook(repo, "pre-commit")

    assert "ok    catalog ruff check" in result.stdout, result.stdout + result.stderr
    assert "ok    catalog ruff format" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize(("workdir", "script"), _lanes_steps())
def test_the_deploy_leaves_out_the_lanes_already_passed_on_its_tree(repo: Path, workdir: str, script: str) -> None:
    code, output = _ci_step(repo, workdir, script, draft="", event="push", tested="python catalog")

    assert code == 0
    assert sorted(output.split()) == ["catalog=false", "python=false", "web=true"]


def _record_steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())
    steps = workflow["jobs"]["test"]["steps"]
    return [step for step in steps if "tested" in str(step.get("run", "")) or "tested" in str(step.get("with", ""))]


def _record(**env: str) -> str:
    """The pull request run's record of what it proved, as its step writes it."""
    (step,) = [step for step in _record_steps() if "run" in step]
    with tempfile.TemporaryDirectory() as tmp:
        _run("bash", "-e", "-c", step["run"], cwd=tmp, env={**_outside_git(), **env}, check=True)
        return (Path(tmp) / "tested.txt").read_text()


def test_the_record_names_the_lanes_that_passed() -> None:
    record = _record(TREE="t" * 40, PYTHON="success", WEB="skipped", CATALOG_LANE="true", CATALOG="success")

    assert record.split() == [f"tree={'t' * 40}", "python=true", "web=false", "catalog=true"]


def test_the_record_does_not_count_a_failed_lane() -> None:
    record = _record(TREE="t" * 40, PYTHON="failure", WEB="cancelled", CATALOG_LANE="true", CATALOG="failure")

    assert record.split()[1:] == ["python=false", "web=false", "catalog=false"]


def test_the_record_does_not_count_a_catalog_whose_steps_all_skipped() -> None:
    """The catalog job succeeds with its lane off: nothing ran, so nothing was proved."""
    record = _record(TREE="t" * 40, PYTHON="success", WEB="success", CATALOG_LANE="false", CATALOG="success")

    assert record.split()[-1] == "catalog=false"


def test_the_record_is_written_before_the_required_check_reports() -> None:
    """A merge as soon as the check is green must find it, and only a pull request's run records."""
    steps = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())["jobs"]["test"]["steps"]
    names = [step.get("name") or step.get("uses") for step in steps]
    record = _record_steps()

    assert len(record) == 2
    assert all("github.event_name == 'pull_request'" in step["if"] for step in record)
    assert names.index("Every lane this change touches passed") > max(steps.index(step) for step in record)
    (upload,) = [step for step in record if "uses" in step]
    assert upload["continue-on-error"] is True


def test_the_deploy_reads_the_record_the_pull_request_wrote() -> None:
    """The artifact's name and file are shared by the upload and scripts/tested_lanes.sh."""
    (upload,) = [step for step in _record_steps() if "uses" in step]
    script = (ROOT / "scripts" / "tested_lanes.sh").read_text()

    assert f"-n {upload['with']['name']} " in script
    assert f'/{upload["with"]["path"]}"' in script


def _images_step() -> str:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())
    (step,) = [step for step in workflow["jobs"]["changes"]["steps"] if step.get("id") == "images"]
    return step["run"]


@pytest.mark.parametrize(
    "path",
    [
        "Dockerfile",
        "catalog/Dockerfile",
        "docker/Caddyfile",
        "uv.lock",
        "catalog/uv.lock",
        "pyproject.toml",
        "web/pnpm-lock.yaml",
        "web/package.json",
        ".dockerignore",
        ".github/workflows/deploy.yml",
    ],
)
def test_a_change_to_what_the_images_are_built_from_builds_them(repo: Path, path: str) -> None:
    _stage(repo, path, "changed\n")
    _commit(repo)

    code, output = _ci_step(repo, ".", _images_step())

    assert code == 0
    assert output.split() == ["images=true"]


@pytest.mark.parametrize("path", ["app/bot.py", "web/src/App.tsx", "catalog/src/x.py", "docs/x.md"])
def test_other_changes_build_no_image(repo: Path, path: str) -> None:
    _stage(repo, path, "changed\n")
    _commit(repo)

    code, output = _ci_step(repo, ".", _images_step())

    assert code == 0
    assert output.split() == ["images=false"]


def test_main_and_drafts_build_no_image_here(repo: Path) -> None:
    """main builds and pushes them in the deploy; a draft runs nothing."""
    _stage(repo, "Dockerfile", "changed\n")
    _commit(repo)

    assert _ci_step(repo, ".", _images_step(), draft="", event="push")[1].split() == ["images=false"]
    assert _ci_step(repo, ".", _images_step(), draft="true")[1].split() == ["images=false"]
