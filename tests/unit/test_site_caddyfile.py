"""The public site's own Caddy (docker/site/Caddyfile), beside what docker/check-routes.py --site checks.

Its log leaves out what the web UI's leaves out: browsers still send cookies
of the old app origin to konnekt.cz, and a request's line could name a person.
Its hashed files are cached for good and its pages never, as the app's are.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCKER = Path(__file__).resolve().parents[2] / "docker"
WEBUI = (DOCKER / "Caddyfile").read_text()
SITE = (DOCKER / "site" / "Caddyfile").read_text()


def _block(text: str, opening: str) -> str:
    """The block that starts at `opening`, braces matched."""
    start = text.index(opening)
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError(f"{opening!r} is not closed")


def test_the_site_logs_what_the_webui_logs_and_nothing_more() -> None:
    assert _block(SITE, "(without_the_request) {") == _block(WEBUI, "(without_the_request) {")
    # Caddy's own log, in the global block, filters the same fields.
    assert _block(SITE, "\tlog {") == _block(WEBUI, "\tlog {")
    assert "import access_log" in SITE


def test_only_hashed_files_that_exist_are_cached_for_good() -> None:
    hashed = re.search(r"@hashed \{\s*path /_astro/\*\s*file\s*\}", SITE)
    assert hashed, "the immutable rule must match existing hashed files only"
    assert re.findall(r"header (@\w+) Cache-Control \"public, max-age=31536000, immutable\"", SITE) == ["@hashed"]
    assert re.search(r"@page not path /_astro/\*\s*header @page Cache-Control \"no-cache\"", SITE)
