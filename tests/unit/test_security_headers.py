"""Every response from the web UI and the public site carries the security headers (#195)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCKER = Path(__file__).resolve().parents[2] / "docker"
# The Mini App's and the public site's (konnekt.cz, framed by Telegram Web too:
# an old button opens it there, and its page sends the launch on to the app).
CADDYFILES = [DOCKER / "Caddyfile", DOCKER / "site" / "Caddyfile"]


def _site_headers(caddyfile: Path) -> dict[str, str]:
    block = re.search(r"^\theader \{\n(.*?)^\t\}", caddyfile.read_text(), re.M | re.S)
    assert block, "the site-wide header block is gone"
    return dict(re.findall(r'^\t\t([\w-]+) "(.*)"$', block.group(1), re.M))


@pytest.mark.parametrize("caddyfile", CADDYFILES, ids=["webui", "site"])
def test_framing_is_limited_to_the_app_and_telegrams_web_clients(caddyfile: Path) -> None:
    """X-Frame-Options would break the Mini App inside Telegram Web; frame-ancestors does not."""
    headers = _site_headers(caddyfile)

    assert (
        headers["Content-Security-Policy"] == "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"
    )
    assert "X-Frame-Options" not in headers


@pytest.mark.parametrize("caddyfile", CADDYFILES, ids=["webui", "site"])
def test_the_rest_of_the_baseline(caddyfile: Path) -> None:
    headers = _site_headers(caddyfile)

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert headers["Strict-Transport-Security"].startswith("max-age=")
