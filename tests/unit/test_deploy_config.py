"""The deploy workflow and compose file must agree on what config to forward.

Configuration lives in GitHub and travels to the host with the deploy command;
nothing is written to a file there. That means the same list of variable names
exists in two places, and a setting added to one but not the other fails at
runtime in production rather than here — silently, since almost every setting
has a default.

So the two are pinned against each other.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yaml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"

# Set by the workflow itself rather than passed to the app, so they appear in
# the deploy step but have no place in a service's environment.
_DEPLOY_ONLY = {"IMAGE_TAG"}


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
    guard = script.index("docker stop -t 60 $others")
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
    """A token in `vars` is readable by anyone with repository access."""
    step = _deploy_step()
    sensitive = {
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
        elif name != "IMAGE_TAG":
            assert "vars." in expression, f"{name} should come from variables, not {expression}"


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
