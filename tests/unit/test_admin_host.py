"""Which host the console answers on, and the hosts it must never take.

The webui's Caddy serves the console on one host and the Mini App on another.
A console host equal to the Mini App's would take that site's traffic, and one
with a port would match no request at all, so both are refused: where the host
is worked out for Caddy (`scripts/admin_host.sh`, run by the deploy) and where
the webapi reads the same URL (`WebApiSettings`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from app.core.config import WebApiSettings
from pydantic import ValidationError

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "admin_host.sh"
PUBLIC = "https://app.example.test"


def _host(admin_url: str, public_url: str = PUBLIC) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), admin_url, public_url],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_host_is_the_urls_host() -> None:
    done = _host("https://admin.example.test")

    assert done.returncode == 0
    assert done.stdout.strip() == "admin.example.test"


def test_a_trailing_slash_is_not_part_of_the_host() -> None:
    assert _host("https://admin.example.test/").stdout.strip() == "admin.example.test"


def test_unset_is_a_host_nobody_can_send() -> None:
    """Empty would make Caddy's site address `http://`, which answers every request."""
    done = _host("")

    assert done.returncode == 0
    assert done.stdout.strip() == "admin.invalid"


@pytest.mark.parametrize(
    "admin_url",
    [
        PUBLIC,
        PUBLIC + "/",
        "https://APP.example.test",
        "https://admin.example.test:8443",
        "http://admin.example.test",
        "https://admin.example.test/console",
        "admin.example.test",
    ],
    ids=["the-public-host", "the-public-host-slash", "the-public-host-case", "a-port", "http", "a-path", "no-scheme"],
)
def test_a_host_that_would_hijack_or_match_nothing_is_refused(admin_url: str) -> None:
    done = _host(admin_url)

    assert done.returncode != 0
    assert done.stdout.strip() == ""


@pytest.mark.parametrize(
    "admin_url",
    [PUBLIC, "https://admin.example.test:8443", "http://admin.example.test", "https://admin.example.test/console"],
)
def test_the_webapi_refuses_the_same_urls_at_startup(admin_url: str) -> None:
    with pytest.raises(ValidationError):
        WebApiSettings(public_url=PUBLIC, admin_url=admin_url)


def test_the_webapi_accepts_a_console_of_its_own() -> None:
    settings = WebApiSettings(public_url=PUBLIC, admin_url="https://admin.example.test")

    assert settings.allowed_origins == [PUBLIC, "https://admin.example.test"]


def test_local_development_may_name_a_port_on_localhost() -> None:
    assert WebApiSettings(public_url="", admin_url="http://localhost:5173").admin_url == "http://localhost:5173"
