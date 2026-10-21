"""The web UI's Caddy writes an access line for what passes through it.

It had none: every request to the Mini App and the API went through it and left
no trace there, so a 502 from a backend that was down could only be found by
asking the backend. The line is also the place a secret could leak, since a
sign-in callback's `code` and `state` ride in the query string and the browser
sends cookies and an `Authorization` header with initData.
"""

# A test that runs the real Caddy: fixed docker arguments and a loopback URL, no input.
# ruff: noqa: S603, S607, S310

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = ROOT / "docker" / "Caddyfile"
# The version the Dockerfile builds on; skipped where it is not already pulled.
IMAGE = "caddy:2.11.2-alpine"


def _docker_has_caddy() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False).returncode == 0


pytestmark = pytest.mark.skipif(not _docker_has_caddy(), reason=f"needs docker and {IMAGE}")


@pytest.fixture(scope="module")
def caddy():
    started = subprocess.run(
        [
            "docker", "run", "-d", "--rm", "-p", "127.0.0.1::80",
            "-e", "ADMIN_HOST=admin.example.test",
            "-v", f"{CADDYFILE}:/etc/caddy/Caddyfile:ro",
            IMAGE,
        ],  # fmt: skip
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    container = started.stdout.strip()
    port = subprocess.run(["docker", "port", container, "80/tcp"], capture_output=True, text=True, check=True)
    base = f"http://127.0.0.1:{port.stdout.splitlines()[0].rsplit(':', 1)[1]}"
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/", timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    try:
        yield container, base
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)


def _get(base: str, path: str, **headers: str) -> int:
    request = urllib.request.Request(base + path, headers=headers)
    try:
        return urllib.request.urlopen(request, timeout=5).status
    except urllib.error.HTTPError as err:
        return err.code


def _access_lines(container: str) -> list[dict]:
    time.sleep(0.5)
    out = subprocess.run(["docker", "logs", container], capture_output=True, text=True, check=True)
    lines = []
    for text in (out.stdout + out.stderr).splitlines():
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if str(parsed.get("logger", "")).startswith("http.log.access"):
            lines.append(parsed)
    return lines


def test_a_request_leaves_a_line_without_the_query_or_the_credentials(caddy) -> None:
    container, base = caddy

    status = _get(
        base,
        "/api/chats?code=SECRETCODE&state=SECRETSTATE",
        Authorization="tma SECRETINITDATA",
        Cookie="session=SECRETCOOKIE",
    )

    ours = [line for line in _access_lines(container) if line["request"]["uri"].startswith("/api/chats")]
    assert len(ours) == 1
    line = ours[0]
    assert line["status"] == status == 502  # webapi is not there, which is what the line is for
    assert line["request"]["uri"] == "/api/chats"
    assert line["request"]["method"] == "GET"
    assert "duration" in line
    assert "request_id" in line
    everything = json.dumps(line)
    for secret in ("SECRETCODE", "SECRETSTATE", "SECRETINITDATA", "SECRETCOOKIE"):
        assert secret not in everything


def test_the_health_check_and_static_assets_are_not_logged(caddy) -> None:
    container, base = caddy

    _get(base, "/healthz")
    _get(base, "/assets/missing.js")

    uris = [line["request"]["uri"] for line in _access_lines(container)]
    assert "/healthz" not in uris
    assert "/assets/missing.js" not in uris


def test_the_backends_are_told_the_id_the_line_carries() -> None:
    """Caddy's id reaches webapi and the catalog as X-Request-Id, so one id finds all three lines."""
    text = CADDYFILE.read_text()

    assert text.count("header_up X-Request-Id {http.request.uuid}") == 3
