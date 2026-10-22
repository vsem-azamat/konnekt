"""The log shipper on the VPS sends the listed projects' containers and nothing else."""

from __future__ import annotations

# A test that runs the real Alloy: fixed docker arguments, no input.
# ruff: noqa: S603, S607
import json
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


def test_only_the_listed_projects_containers_are_kept() -> None:
    """The host runs other stacks (khromberry, urf, ...); only these two leave it."""
    keeps = re.findall(r'regex\s*=\s*"([^"]*)"\s*action\s*=\s*"keep"', CONFIG)

    assert keeps == ["supervisor-telegram|gov-cz-bot"]
    assert "com_docker_compose_project" in CONFIG.split("action", 1)[0]


def test_each_project_gets_the_project_label_of_its_metrics_after_discovery() -> None:
    """A target label would change the source's position key and re-read every log."""
    discovery, process = CONFIG.split('loki.process "json"', 1)

    assert "project" not in re.findall(r'target_label\s*=\s*"([^"]*)"', discovery)
    pairs = re.findall(
        r'selector = "\{compose_project=\\"([^"\\]+)\\"\}"\s*stage\.static_labels \{\s*values = \{ project = "([^"]+)" \}',
        process,
    )
    assert pairs == [("supervisor-telegram", "konnekt"), ("gov-cz-bot", "gov-cz")]


def test_the_mini_app_init_data_never_leaves_the_host() -> None:
    """gov-cz-bot's Caddy logs request headers; the init data is a login valid for a day."""
    literal = re.search(
        r'stage\.replace \{\s*expression = ("(?:[^"\\]|\\.)*")\s*replace    = ("(?:[^"\\]|\\.)*")', CONFIG
    )
    assert literal
    expression, replacement = (json.loads(part) for part in literal.groups())

    def redact(line: str) -> str:
        return re.sub(expression, lambda match: match.group(0).replace(match.group(1), replacement), line)

    one = '{"request": {"headers": {"X-Telegram-Init-Data": ["query_id=A&hash=b"], "Accept": ["*/*"]}}}'
    two = '{"x-telegram-init-data":["a", "b"],"Other": ["keep"]}'
    assert redact(one) == '{"request": {"headers": {"X-Telegram-Init-Data": ["<redacted>"], "Accept": ["*/*"]}}}'
    assert redact(two) == '{"x-telegram-init-data":["<redacted>"],"Other": ["keep"]}'
    creds = '{"headers": {"Cookie": ["s=1"], "Proxy-Authorization": ["Basic x"], "Authorization": ["Bearer t"]}}'
    assert redact(creds) == (
        '{"headers": {"Cookie": ["<redacted>"], "Proxy-Authorization": ["<redacted>"], "Authorization": ["<redacted>"]}}'
    )
    untouched = '{"level": "INFO", "message": "list [1, 2]"}'
    assert redact(untouched) == untouched


def test_the_credentials_are_read_from_the_environment_and_the_link_is_https() -> None:
    assert 'username = sys.env("LOKI_PUSH_USER")' in CONFIG
    assert 'password = sys.env("LOKI_PUSH_PASSWORD")' in CONFIG
    assert re.search(r'url\s*=\s*"https://', CONFIG)
    assert not re.search(r'password\s*=\s*"', CONFIG)


def test_level_is_lower_case_before_it_becomes_a_label() -> None:
    """gov-cz-bot writes ERROR, Konnekt error; one label value for both."""
    assert CONFIG.index('template = "{{ ToLower .Value }}"') < CONFIG.index("stage.labels")


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
