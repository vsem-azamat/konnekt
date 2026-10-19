"""The deploy workflow and compose file must agree on what config to forward.

Configuration lives in GitHub and travels to the host with the deploy command;
nothing is written to a file there. That means the same list of variable names
exists in two places, and a setting added to one but not the other fails at
runtime in production rather than here — silently, since almost every setting
has a default.

So the two are pinned against each other.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yaml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"

# Set by the workflow itself rather than passed to the app, so they appear in
# the deploy step but have no place in a service's environment.
_DEPLOY_ONLY = {"IMAGE_TAG", "MIGRATE"}


def _compose_passthrough() -> set[str]:
    """Names the compose file expects to inherit from the environment.

    A null value in the mapping form is compose's "take this from the host";
    entries with a literal value are baked in and are not our concern.
    """
    raw = COMPOSE.read_text()
    # Anchors and merge keys are not part of the YAML core schema that
    # safe_load resolves for us here, so read the anchor block directly.
    # Entries with a literal value are fixed in the file, not forwarded.
    block = re.search(r"^x-runtime-env: &runtime-env\n((?:  \S.*\n)+)", raw, re.M)
    assert block, "the shared environment anchor is gone or was renamed"
    return set(re.findall(r"^  ([A-Z_]+):\s*$", block.group(1), re.M))


def _webui_passthrough() -> set[str]:
    """Names the webui container inherits: Caddy reads them, the app never does."""
    webui = yaml.safe_load(COMPOSE.read_text())["services"]["webui"]
    return {name for name, value in (webui.get("environment") or {}).items() if value is None}


def _deploy_step() -> dict:
    workflow = yaml.safe_load(DEPLOY.read_text())
    for step in workflow["jobs"]["deploy"]["steps"]:
        if str(step.get("uses", "")).startswith("appleboy/ssh-action"):
            return step
    raise AssertionError("no ssh deploy step found")


def _interpolated() -> set[str]:
    """Names compose substitutes into the file itself: `${NAME}`, `${NAME:-x}`.

    Not `$${NAME}`: that is escaped, and reaches the container's own shell.
    """
    return set(re.findall(r"(?<!\$)\$\{([A-Z_]+)(?::?[-?][^}]*)?\}", COMPOSE.read_text()))


def test_every_forwarded_name_is_declared_in_both_places() -> None:
    step = _deploy_step()
    forwarded = {name.strip() for name in step["with"]["envs"].split(",") if name.strip()}

    assert forwarded - _DEPLOY_ONLY == (_compose_passthrough() | _webui_passthrough() | _interpolated()) - _DEPLOY_ONLY


def test_the_catalog_runs_here_on_the_database_it_already_has() -> None:
    """The catalog's data is in the volume its old stack created, under that name.

    A compose volume is `<project>_<name>`; declared any other way, the catalog
    would come up on a new, empty database — no subjects, no institutions, no
    profiles — and look healthy doing it.
    """
    compose = yaml.safe_load(COMPOSE.read_text())
    postgres = compose["services"]["catalog-postgres"]
    (mount,) = postgres["volumes"]
    volume = compose["volumes"][mount.split(":")[0]]

    assert volume == {"external": True, "name": "konnekt_postgres-data"}
    assert "catalog-api" in compose["services"]
    # The Mini App reaches it inside the stack, not across the internet.
    assert "CATALOG_ORIGIN" not in _webui_passthrough()


def test_nothing_else_holds_the_catalog_database_when_ours_starts() -> None:
    """Two Postgres servers on one data directory corrupt it.

    The teachers-catalog stack mounted the same volume. Before anything here
    can start the catalog's Postgres — `up`, or a `run` whose dependency
    starts it — every other container on that volume is stopped. A no-op once
    the old stack is gone, and the guard against anything bringing it back.
    """
    script = _deploy_step()["with"]["script"]
    guard = script.index("xargs docker stop -t 60")
    starts = [m.start() for m in re.finditer(r"docker compose\b[^\n]*\b(up|run|start)\b", script)]

    assert starts
    assert guard < min(starts)
    # Every deploy after the first has only ours on the volume, and grep then
    # exits 1: without this, set -e ends the deploy there.
    assert '| grep -vx "${ours:-none}" || true' in script
    volume = yaml.safe_load(COMPOSE.read_text())["volumes"]["catalog-postgres-data"]["name"]
    assert set(re.findall(r"--filter volume=([^\s)]+)", script)) == {volume}


def test_the_old_database_proves_the_password_before_it_is_stopped() -> None:
    """`pg_isready` does not authenticate, so a wrong CATALOG_DB_PASSWORD
    would pass the health check and fail only at the migration, with the old
    catalog already stopped. Checked first, while it can still refuse."""
    script = _deploy_step()["with"]["script"]

    assert script.index("select 1") < script.index("docker compose -p students-cz stop")


def test_the_catalog_database_is_mounted_where_postgres_18_keeps_it() -> None:
    compose = yaml.safe_load(COMPOSE.read_text())
    (mount,) = compose["services"]["catalog-postgres"]["volumes"]

    assert mount.endswith(":/var/lib/postgresql")


def test_a_deploy_is_not_cut_off_halfway() -> None:
    """Between stopping the old catalog and starting the new one, a cancelled
    run or a timed-out session leaves no catalog at all."""
    workflow = yaml.safe_load(DEPLOY.read_text())

    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert _deploy_step()["with"]["command_timeout"]


def test_the_catalog_has_what_it_cannot_start_without() -> None:
    workflow = yaml.safe_load(DEPLOY.read_text())
    check = next(
        step
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name") == "Check required configuration is present"
    )
    required = re.search(r"^\s*for name in ([A-Z_ ]+); do$", check["run"], re.M)
    assert required, "the required-names loop is gone or was reshaped"
    for name in ("CATALOG_DB_USER", "CATALOG_DB_NAME", "CATALOG_DB_PASSWORD"):
        assert name in required.group(1).split()
        assert name in check["env"]


def test_every_forwarded_name_has_a_value_to_forward() -> None:
    """`envs` names a variable; without an `env:` entry it forwards nothing."""
    step = _deploy_step()
    forwarded = {name.strip() for name in step["with"]["envs"].split(",") if name.strip()}

    assert forwarded == set(step["env"])


def test_credentials_come_from_secrets_and_the_rest_from_variables() -> None:
    """A variable is printed unmasked in every log of this public repository.

    So everything but what is public anyway comes from secrets: credentials,
    people's Telegram ids, and where the databases are and what they are called.
    """
    step = _deploy_step()
    sensitive = {
        "DB_HOST",
        "DB_USER",
        "DB_NAME",
        "CATALOG_DB_USER",
        "CATALOG_DB_NAME",
        "ADMIN_SUPER_ADMINS",
        "ADMIN_REPORT_CHAT_ID",
        "CATALOG_OWNER_TG_ID",
        "DB_PASSWORD",
        "CATALOG_DB_PASSWORD",
        "MODERATOR_BOT_TOKEN",
        "MODERATOR_BOT_RETIRED_TOKEN",
        "OPENROUTER_API_KEY",
        "BRAVE_API_KEY",
        "TELETHON_API_ID",
        "TELETHON_API_HASH",
        "MCP_TOKEN",
    }

    for name, expression in step["env"].items():
        if name in sensitive:
            assert "secrets." in expression, f"{name} must come from secrets"
        elif name not in _DEPLOY_ONLY:
            assert "vars." in expression, f"{name} should come from variables, not {expression}"


def test_the_deploy_log_shows_status_not_what_the_services_said() -> None:
    """The repository is public, so its workflow logs are published documents.

    Application logs name users and chats; a deploy needs only to say whether
    the containers came up.
    """
    script = _deploy_step()["with"]["script"]

    assert "docker compose logs" not in script
    assert "docker compose ps" in script


def _host_task(name: str) -> str:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "host.yml").read_text())
    script = workflow["jobs"]["run"]["steps"][0]["with"]["script"]
    body = re.search(rf"^\s*{name}\)\n(.*?)^\s*;;", script, re.M | re.S)
    assert body, f"host task {name} is gone"
    return body.group(1)


def test_the_host_diagnosis_shows_only_this_project() -> None:
    """The host is shared: its other containers and open ports are not ours to publish."""
    diagnose = _host_task("diagnose")

    for line in diagnose.splitlines():
        if "docker ps" in line:
            assert "--filter name=supervisor-telegram" in line or "--filter name=caddy" in line, line
    assert "ss -" not in diagnose


def test_the_edge_log_is_reduced_to_status_fields() -> None:
    """Raw edge lines carry visitors' addresses, user agents and URIs."""
    edge = _host_task("edge-tls")
    logs = next(line for line in edge.splitlines() if "docker logs" in line)

    assert "grep -F" in logs
    assert "client_ip" not in edge
    assert re.search(r"\| *python3 -c", edge), "edge log lines must be reduced before printing"


def test_nothing_writes_configuration_to_the_host() -> None:
    """The point of the exercise: no .env is created, edited or read."""
    script = _deploy_step()["with"]["script"]

    assert ".env" not in script


def test_the_pull_does_not_depend_on_the_host_docker_login() -> None:
    """The images are public and the host is shared with other projects.

    Depending on a login nobody here maintains is how a deploy comes to fail
    with "denied" against images anyone can read: a rejected credential does
    not fall back to anonymous. Our own config directory has nothing in it to
    go stale.
    """
    script = _deploy_step()["with"]["script"]

    assert "DOCKER_CONFIG" in script
    assert script.index("DOCKER_CONFIG") < script.index("docker compose pull")


def test_the_image_build_gets_every_pnpm_config_the_lockfile_was_written_with() -> None:
    """A frozen install refuses when the settings it finds are not the ones recorded.

    pnpm keeps overrides and the build-script allowlist in pnpm-workspace.yaml
    rather than package.json, and writes the overrides into the lockfile too.
    The web stage copies a short list of files by hand, so leaving that one
    out fails the image build — and only the image build, since a checkout has
    the file sitting there either way.
    """
    dockerfile = ROOT.joinpath("Dockerfile").read_text()
    copied = re.search(r"^COPY (web/\S+ .*?)\./$", dockerfile, re.M)
    assert copied, "the web dependency stage no longer copies files one by one"

    if (ROOT / "web" / "pnpm-workspace.yaml").exists():
        assert "web/pnpm-workspace.yaml" in copied.group(1)


def test_the_bots_database_is_dumped_daily_off_its_server() -> None:
    """moderator_prod lives on the shared database server, whose own backup
    jobs do not cover it. A dump a day lands beside this stack instead, on
    another machine, with the credentials the bot already runs with."""
    compose = yaml.safe_load(COMPOSE.read_text())
    backup = compose["services"]["db-backup"]

    assert backup["volumes"] == ["./db-backups:/backups"]
    env = backup["environment"]
    assert (env["PGHOST"], env["PGUSER"], env["PGDATABASE"], env["PGPASSWORD"]) == (
        "${DB_HOST}",
        "${DB_USER}",
        "${DB_NAME}",
        "${DB_PASSWORD}",
    )
    # The file names say whose dump it is; the catalog's predate this service.
    assert env["BACKUP_PREFIX"] == "moderator"
    assert compose["services"]["catalog-backup"]["environment"]["BACKUP_PREFIX"] == "catalog"
    assert backup["command"] == compose["services"]["catalog-backup"]["command"]
    backups_dirs = re.search(r"install -d -m 700 ([^\n]+)", _deploy_step()["with"]["script"])
    assert backups_dirs
    assert "db-backups" in backups_dirs.group(1).split()


def test_backup_retention_touches_only_its_own_dumps() -> None:
    """db-backups/ already held a migration's hand-made dumps in subdirectories.
    Retention reaches only the top level, where the loop writes."""
    raw = COMPOSE.read_text()
    (find,) = re.findall(r"^\s*find /backups.*$", raw, re.M)

    assert "-maxdepth 1" in find


# The marker the loop writes and the healthcheck reads, inside the container.
_MARKER = "/tmp/backup-loop-started"  # noqa: S108


def _for_host(text: str, tmp_path: Path) -> str:
    """A compose shell snippet with its container paths moved under tmp_path."""
    text = text.replace("$$", "$").replace("/backups", str(tmp_path / "backups"))
    return text.replace(_MARKER, str(tmp_path / "started"))


def _backup_loop(tmp_path: Path, *, dump_succeeds: bool) -> subprocess.CompletedProcess[bytes]:
    """Run one pass of the compose backup loop against a scratch directory.

    The script is the one compose hands to bash. `sleep` is faked: the first
    call returns, the second ends the loop, so exactly one dump is attempted.
    """
    script = _for_host(yaml.safe_load(COMPOSE.read_text())["services"]["db-backup"]["command"][0], tmp_path)
    (tmp_path / "backups").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "sleep").write_text(
        '#!/bin/bash\nf="$(dirname "$0")/slept"\n[ -e "$f" ] && kill -TERM "$PPID"\ntouch "$f"\n'
    )
    called = 'touch "$(dirname "$0")/dumped"\n'
    pg_dump = called + 'for a; do case $a in --file=*) echo dump > "${a#--file=}";; esac; done\n'
    (bin_dir / "pg_dump").write_text("#!/bin/bash\n" + (pg_dump if dump_succeeds else called + "exit 1\n"))
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)

    old = tmp_path / "backups" / "moderator-20200101T020000Z.dump"
    old.write_text("old")
    month_ago = time.time() - 40 * 86400
    os.utime(old, (month_ago, month_ago))

    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_PREFIX": "moderator",
        "BACKUP_HOUR_UTC": "2",
        "BACKUP_RETENTION_DAYS": "30",
    }
    result = subprocess.run(["bash", "-c", script], env=env, timeout=30, check=False)  # noqa: S603, S607 — our own compose script
    # Ended by the fake sleep, after one attempt, rather than dying on the way.
    assert result.returncode == -signal.SIGTERM
    assert (bin_dir / "dumped").exists()
    return result


def test_a_failed_dump_deletes_nothing(tmp_path: Path) -> None:
    """Pruning after a failure would eat one good dump a day until none were left."""
    _backup_loop(tmp_path, dump_succeeds=False)

    assert sorted(p.name for p in (tmp_path / "backups").glob("*.dump")) == ["moderator-20200101T020000Z.dump"]


def test_a_good_dump_prunes_what_is_past_retention(tmp_path: Path) -> None:
    _backup_loop(tmp_path, dump_succeeds=True)

    names = [p.name for p in (tmp_path / "backups").glob("*.dump")]
    assert len(names) == 1
    assert names[0] != "moderator-20200101T020000Z.dump"


def test_the_loop_marks_its_start_where_the_healthcheck_looks(tmp_path: Path) -> None:
    """A fresh host has no dump yet; without the mark its first deploy fails."""
    _backup_loop(tmp_path, dump_succeeds=False)

    assert (tmp_path / "started").exists()


def _healthy(
    tmp_path: Path, *, newest_dump_hours: float | None, loop_started_hours: float, foreign_dump: bool = False
) -> bool:
    check = _for_host(yaml.safe_load(COMPOSE.read_text())["services"]["db-backup"]["healthcheck"]["test"][1], tmp_path)
    backups = tmp_path / "backups"
    backups.mkdir()

    def _aged(path: Path, hours: float) -> None:
        path.write_text("")
        then = time.time() - hours * 3600
        os.utime(path, (then, then))

    _aged(tmp_path / "started", loop_started_hours)
    if newest_dump_hours is not None:
        _aged(backups / "moderator-x.dump", newest_dump_hours)
    if foreign_dump:
        _aged(backups / "copied-by-hand.dump", 0)
    env = {"PATH": os.environ["PATH"], "BACKUP_PREFIX": "moderator"}
    return subprocess.run(["sh", "-c", check], env=env, check=False).returncode == 0  # noqa: S603, S607 — our own healthcheck


@pytest.mark.parametrize(
    ("newest_dump_hours", "loop_started_hours", "healthy"),
    [
        (20, 500, True),
        # One missed night is a warning in the logs; two is a broken backup.
        (30, 500, True),
        (47, 500, True),
        (50, 500, False),
        (None, 500, False),
        # A container with no dump yet has two days to write its first one.
        (None, 1, True),
        # A restart must not hide a stale backup behind a fresh grace period.
        (50, 1, False),
    ],
)
def test_a_stale_backup_shows_as_unhealthy(
    tmp_path: Path, newest_dump_hours: float | None, loop_started_hours: float, healthy: bool
) -> None:
    """Nothing else watches the dumps, so the container's health has to."""
    assert _healthy(tmp_path, newest_dump_hours=newest_dump_hours, loop_started_hours=loop_started_hours) is healthy


def test_a_dump_copied_in_by_hand_does_not_count(tmp_path: Path) -> None:
    assert not _healthy(tmp_path, newest_dump_hours=50, loop_started_hours=500, foreign_dump=True)


def test_both_backups_share_the_healthcheck() -> None:
    services = yaml.safe_load(COMPOSE.read_text())["services"]

    assert services["db-backup"]["healthcheck"] == services["catalog-backup"]["healthcheck"]


def test_app_migrations_run_before_anything_new_serves() -> None:
    """Migrating inside the bot let the new webapi serve against the old schema.

    A one-shot job, like the catalog's, finishes before either service is
    recreated, and a failed migration stops the deploy with the old release up.
    """
    compose = yaml.safe_load(COMPOSE.read_text())
    migrate = compose["services"]["migrate"]
    assert migrate["command"] == ["migrate"]
    assert migrate["profiles"] == ["tools"]
    assert set(migrate["environment"]) >= {"DB_HOST", "DB_USER", "DB_NAME", "DB_PASSWORD"}

    script = _deploy_step()["with"]["script"]
    assert script.index("docker compose run --rm -T migrate") < script.index("docker compose up -d --remove-orphans")

    entrypoint = (ROOT / "scripts" / "entrypoint.sh").read_text()
    bot_case = re.search(r"^  bot\)\n(.*?);;", entrypoint, re.M | re.S)
    assert bot_case
    assert "alembic" not in bot_case.group(1)
    assert re.search(r"^  migrate\)\n\s*exec alembic upgrade head", entrypoint, re.M)


def test_a_release_can_be_deployed_again_by_its_sha() -> None:
    """Going back must not wait for a revert to pass the whole pipeline."""
    workflow = yaml.safe_load(DEPLOY.read_text())
    dispatch = workflow[True]["workflow_dispatch"]["inputs"]
    assert dispatch["sha"]["required"] is True
    # Rolling back past a migration: the older alembic does not know the newer
    # revision, and expand-only migrations leave a schema the old code reads.
    assert dispatch["migrate"]["type"] == "boolean"

    step = _deploy_step()
    assert "inputs.sha" in step["env"]["IMAGE_TAG"]
    assert "MIGRATE" in step["with"]["envs"]
    jobs = workflow["jobs"]
    assert "workflow_dispatch" in jobs["test"]["if"]
    assert "workflow_dispatch" in jobs["build-and-push"]["if"]


def test_ci_runs_the_app_migrations() -> None:
    """Tests build the schema with create_all; only alembic proves the history."""
    steps = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())["jobs"]["test"]["steps"]
    runs = "\n".join(str(s.get("run", "")) for s in steps)

    assert "alembic upgrade head" in runs
    assert "alembic check" in runs


def test_the_bot_and_webapi_report_their_own_health() -> None:
    """`pgrep -f` matched its own shell, so both were always healthy."""
    services = yaml.safe_load(COMPOSE.read_text())["services"]

    bot_check = " ".join(services["bot"]["healthcheck"]["test"])
    assert "heartbeat" in bot_check
    webapi_check = " ".join(services["webapi"]["healthcheck"]["test"])
    assert "/api/health" in webapi_check
    assert "pgrep" not in (ROOT / "Dockerfile").read_text()


_SHELLS = [
    "bash",
    # The deploy user's login shell, which appleboy runs the script in. It does
    # not split unquoted variables, and the first prune removed nothing.
    # Skipped only off CI: in CI a missing zsh must fail, not pass quietly.
    pytest.param(
        "zsh",
        marks=pytest.mark.skipif(shutil.which("zsh") is None and not os.environ.get("CI"), reason="zsh not installed"),
    ),
]


def _prune_script(tmp_path: Path, *, images: list[str], previous: str, shell: str = "bash") -> list[str]:
    """Run the deploy's prune step against a fake docker; return what it removed."""
    script = _deploy_step()["with"]["script"]
    block = re.search(r"# --- prune ---\n(.*?)# --- /prune ---", script, re.S)
    assert block, "the deploy no longer prunes its old images"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    removed = tmp_path / "removed"
    listing = "\\n".join(images)
    (bin_dir / "docker").write_text(
        "#!/bin/bash\n"
        f'if [ "$1" = images ]; then printf "{listing}\\n"; exit 0; fi\n'
        # Like docker: removes what it can, refuses an image in use, exits 1 if any was refused.
        f'if [ "$1" = image ] && [ "$2" = rm ]; then shift 2; rc=0; for i; do\n'
        f'  case "$i" in *in-use*) echo "Error: image is being used" >&2; rc=1;;\n'
        f'  *) echo "$i" >> {removed}; echo "Untagged: $i";; esac; done; exit $rc; fi\n'
        "exit 0\n"
    )
    (bin_dir / "docker").chmod(0o755)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "IMAGE_TAG": "new", "PREVIOUS_TAG": previous}
    # -e, as the deploy runs it: a refused removal must not fail the deploy.
    subprocess.run([shell, "-ec", block.group(1)], env=env, check=True)  # noqa: S603 — our own deploy script
    return sorted(removed.read_text().split()) if removed.exists() else []


@pytest.mark.parametrize("shell", _SHELLS)
def test_a_deploy_keeps_this_release_and_the_last_and_removes_the_rest(tmp_path: Path, shell: str) -> None:
    """99 GB of images had piled up on a disk shared with other projects."""
    repo = "ghcr.io/vsem-azamat"
    images = [
        f"{repo}/supervisor-telegram:new",
        f"{repo}/supervisor-telegram:catalog-new",
        f"{repo}/supervisor-telegram-webui:new",
        f"{repo}/supervisor-telegram:old",
        f"{repo}/supervisor-telegram:catalog-old",
        f"{repo}/supervisor-telegram-webui:old",
        f"{repo}/supervisor-telegram:older",
        f"{repo}/supervisor-telegram:catalog-older",
        f"{repo}/supervisor-telegram-webui:older",
        f"{repo}/supervisor-telegram:in-use",
        "ghcr.io/someone-else/app:older",
        "pgvector/pgvector:0.8.6-pg18-bookworm",
    ]

    removed = _prune_script(tmp_path, images=images, previous="old", shell=shell)

    assert removed == sorted(
        [
            f"{repo}/supervisor-telegram:older",
            f"{repo}/supervisor-telegram:catalog-older",
            f"{repo}/supervisor-telegram-webui:older",
        ]
    )


def test_a_first_deploy_with_nothing_running_keeps_only_this_release(tmp_path: Path) -> None:
    repo = "ghcr.io/vsem-azamat"
    images = [f"{repo}/supervisor-telegram:new", f"{repo}/supervisor-telegram:old"]

    assert _prune_script(tmp_path, images=images, previous="") == [f"{repo}/supervisor-telegram:old"]


def test_pruning_happens_only_after_the_new_release_is_up() -> None:
    script = _deploy_step()["with"]["script"]

    assert script.index("PREVIOUS_TAG=") < script.index("docker compose pull")
    assert script.index("docker compose up -d --remove-orphans") < script.index("# --- prune ---")
    assert "system prune" not in script


def test_the_previous_release_is_read_from_the_running_bot(tmp_path: Path) -> None:
    script = _deploy_step()["with"]["script"]
    (line,) = [line for line in script.splitlines() if line.strip().startswith("PREVIOUS_TAG=")]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(
        '#!/bin/bash\n[ "$1" = inspect ] && [ "${@: -1}" = supervisor-telegram-bot ] && '
        "echo ghcr.io/vsem-azamat/supervisor-telegram:abc123\n"
    )
    (bin_dir / "docker").chmod(0o755)

    command = ["bash", "-ec", f'{line.strip()}\necho "$PREVIOUS_TAG"']  # noqa: S607
    result = subprocess.run(  # noqa: S603 — our own deploy script
        command,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "abc123"
    assert yaml.safe_load(COMPOSE.read_text())["services"]["bot"]["container_name"] == "supervisor-telegram-bot"


def test_the_deploy_never_passes_a_list_as_one_unquoted_variable() -> None:
    """zsh, the deploy user's shell, hands `docker x $list` over as a single argument."""
    script = _deploy_step()["with"]["script"]

    for name in ("holders", "others", "stale"):
        assert not re.search(rf"(docker [^\n]*|\bin) \${name}\b", script), name
