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
    # Its access log filters through the snippet above; its skipped paths differ from the web UI's.
    assert "import without_the_request" in _block(SITE, "(access_log) {")


def test_only_hashed_files_that_exist_are_cached_for_good() -> None:
    hashed = re.search(r"@hashed \{\s*path /_astro/\*\s*file\s*\}", SITE)
    assert hashed, "the immutable rule must match existing hashed files only"
    assert re.findall(r"header (@\w+) Cache-Control \"public, max-age=31536000, immutable\"", SITE) == ["@hashed"]
    assert re.search(r"@page not path /_astro/\*\s*header @page Cache-Control \"no-cache\"", SITE)


def test_a_permanent_redirect_is_kept_a_while_not_for_good() -> None:
    # A browser keeps a 301 with no Cache-Control indefinitely. konnekt.cz/
    # once redirected to the app this way, and when the app began sending
    # browsers back to konnekt.cz, those that kept it went round between the two.
    # A 308 is kept the same way.
    permanent = r"(?:permanent|301|308)\n"
    for name, caddyfile, count in (("site", SITE, 2), ("webui", WEBUI, 4)):
        handles = re.findall(rf"handle[^{{\n]*\{{[^{{}}]*\bredir [^\n]* {permanent}[^{{}}]*\}}", caddyfile)
        assert len(handles) == len(re.findall(rf"\bredir [^\n]* {permanent}", caddyfile)) == count, name
        for handle in handles:
            assert 'header Cache-Control "public, max-age=3600"' in handle, (name, handle)
