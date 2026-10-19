"""Every response from the web UI carries the security headers (#195)."""

from __future__ import annotations

import re
from pathlib import Path

CADDYFILE = Path(__file__).resolve().parents[2] / "docker" / "Caddyfile"


def _site_headers() -> dict[str, str]:
    block = re.search(r"^\theader \{\n(.*?)^\t\}", CADDYFILE.read_text(), re.M | re.S)
    assert block, "the site-wide header block is gone"
    return dict(re.findall(r'^\t\t([\w-]+) "(.*)"$', block.group(1), re.M))


def test_framing_is_limited_to_the_app_and_telegrams_web_clients() -> None:
    """X-Frame-Options would break the Mini App inside Telegram Web; frame-ancestors does not."""
    headers = _site_headers()

    assert headers["Content-Security-Policy"] == "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"
    assert "X-Frame-Options" not in headers


def test_the_rest_of_the_baseline() -> None:
    headers = _site_headers()

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert headers["Strict-Transport-Security"].startswith("max-age=")
