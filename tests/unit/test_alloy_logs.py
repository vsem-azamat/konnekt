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


def test_the_agent_is_pinned_read_only_on_the_socket_and_publishes_nothing() -> None:
    service = COMPOSE["services"]["alloy"]

    assert re.fullmatch(r"grafana/alloy:v\d+\.\d+\.\d+", IMAGE)
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in service["volumes"]
    assert "ports" not in service
    assert any("127.0.0.1" in arg for arg in service["command"] if "listen-addr" in arg)
    assert service["env_file"] == ".env"


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
