"""The log shipper on the VPS sends this project's containers and nothing else."""

from __future__ import annotations

# A test that runs the real Alloy: fixed docker arguments, no input.
# ruff: noqa: S603, S607
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

DIR = Path(__file__).resolve().parents[2] / "deploy" / "alloy-logs"
CONFIG = (DIR / "config.alloy").read_text()
COMPOSE = yaml.safe_load((DIR / "docker-compose.yaml").read_text())
IMAGE = COMPOSE["services"]["alloy"]["image"]


def test_only_this_projects_containers_are_kept() -> None:
    """The host runs other stacks; their logs are not this project's to send."""
    keeps = re.findall(r'regex\s*=\s*"([^"]*)"\s*action\s*=\s*"keep"', CONFIG)

    assert keeps == ["supervisor-telegram"]
    assert "com_docker_compose_project" in CONFIG.split("action", 1)[0]


def test_the_credentials_are_read_from_the_environment_and_the_link_is_https() -> None:
    assert 'username = sys.env("LOKI_PUSH_USER")' in CONFIG
    assert 'password = sys.env("LOKI_PUSH_PASSWORD")' in CONFIG
    assert re.search(r'url\s*=\s*"https://', CONFIG)
    assert not re.search(r'password\s*=\s*"', CONFIG)


def test_a_restart_does_not_backfill_old_logs() -> None:
    assert 'older_than          = "24h"' in CONFIG


def test_alloy_never_sees_the_docker_socket_only_a_proxy_that_refuses_writes() -> None:
    """Alloy runs as root, and `:ro` on the socket does not limit the API."""
    services = COMPOSE["services"]
    alloy, proxy = services["alloy"], services["socket-proxy"]

    assert not any("docker.sock" in volume for volume in alloy["volumes"])
    assert "docker.sock" in " ".join(proxy["volumes"])
    assert re.fullmatch(r"tecnativa/docker-socket-proxy:\d+\.\d+\.\d+", proxy["image"])
    # Containers and their networks to read; nothing else, and no POST at all.
    enabled = {name for name, value in proxy["environment"].items() if str(value) == "1"}
    assert enabled == {"CONTAINERS", "NETWORKS"}
    assert str(proxy["environment"]["POST"]) == "0"
    assert COMPOSE["networks"]["docker-api"]["internal"] is True
    assert proxy["networks"] == ["docker-api"]
    assert "tcp://socket-proxy:2375" in CONFIG
    assert "unix://" not in CONFIG


def test_the_agent_is_pinned_and_publishes_nothing() -> None:
    for service in COMPOSE["services"].values():
        assert "ports" not in service
        assert service["image"].split(":")[1] != "latest"
    assert re.fullmatch(r"grafana/alloy:v\d+\.\d+\.\d+", IMAGE)
    assert COMPOSE["services"]["alloy"]["env_file"] == ".env"


def test_the_filter_follows_a_project_name_the_stack_states_itself() -> None:
    stack = yaml.safe_load((DIR.parents[1] / "docker-compose.yaml").read_text())

    assert stack["name"] == "supervisor-telegram"


@pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False).returncode != 0,
    reason=f"needs docker and {IMAGE}",
)
def test_alloy_accepts_the_config() -> None:
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{DIR / 'config.alloy'}:/c.alloy:ro", "-e", "LOKI_PUSH_USER=u",
         "-e", "LOKI_PUSH_PASSWORD=p", IMAGE, "validate", "/c.alloy"],  # fmt: skip
        capture_output=True, text=True, check=False,
    )  # fmt: skip

    assert result.returncode == 0, result.stderr
