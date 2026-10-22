"""The public half of the web must stay public.

The web is one Mini App in `web/`: its console is `web/src/console/`, and
everything else is the public half. A directory is exactly the kind of
convention that erodes: somebody
needs a member count on a public screen, reaches for the endpoint that already
returns one, and a page anybody can open starts asking for an admin session.
Nothing in the type system notices.

So the boundary is asserted here instead. These read the sources as text on
purpose — what needs checking is which imports and which URLs appear, which the
text answers exactly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "web" / "src"
# The console's screens inside the Mini App, and the only code in it that may
# use webapi's session. Everything else in the app is the public half.
CONSOLE = APP / "console"
# The shell: it mounts the console's routes and reads its retry rule, and
# does nothing else with it.
SHELL = {APP / "router.tsx", APP / "main.tsx"}

# `fetch('/api/…')` and friends, also after a template's base: `${BASE}/api/…`.
# Only literal paths are findable, which is the point: a computed endpoint on a
# public screen would be unreviewable anyway.
API_CALL = re.compile(r"""(?:['"`]|\})(/api/[^'"`\s$]*)""")

# What the Mini App may reach under /api: this repository's public endpoints,
# and the catalog's API, which Caddy sends to another backend altogether.
ALLOWED = ("/api/public", "/api/v1")


def _app_sources() -> list[Path]:
    generated = APP / "lib" / "generated"
    return sorted(p for p in [*APP.rglob("*.ts"), *APP.rglob("*.tsx")] if generated not in p.parents)


def _public_sources() -> list[Path]:
    return [p for p in _app_sources() if CONSOLE not in p.parents]


def _console_pages() -> list[Path]:
    return sorted((CONSOLE / "pages").rglob("*.tsx"))


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


class TestTheHalvesExist:
    def test_there_is_no_second_web_app(self) -> None:
        """The Svelte console was retired; a second build is a second site to keep safe.

        Its sources, not the directory: a checkout from before keeps its
        ignored node_modules there, which is nothing anybody ships.
        """
        assert not (ROOT / "webui" / "package.json").exists()
        assert not (ROOT / "webui" / "src").exists()

    def test_the_mini_app_is_there(self) -> None:
        assert (APP / "lib" / "api.ts").is_file()
        assert _console_pages(), "the console's screens live in web/src/console/pages"


class TestThePublicHalfAsksNothingOfAnybody:
    @pytest.mark.parametrize("source", _public_sources(), ids=_rel)
    def test_it_only_calls_public_endpoints(self, source: Path) -> None:
        called = API_CALL.findall(source.read_text(encoding="utf-8"))
        private = [path for path in called if not any(path == a or path.startswith(f"{a}/") for a in ALLOWED)]

        assert not private, f"{_rel(source)} reaches {private}, which needs a session"

    @pytest.mark.parametrize("source", sorted(set(_public_sources()) - SHELL), ids=_rel)
    def test_it_does_not_pull_in_the_console(self, source: Path) -> None:
        """A public screen that imports the console can make its session requests."""
        text = source.read_text(encoding="utf-8")

        assert "@/console" not in text
        assert "/console/" not in re.sub(r"navigate\('/console[^']*'\)", "", text)


class TestTheConsoleIsGuardedByWhereItSits:
    @pytest.mark.parametrize("page", _console_pages(), ids=_rel)
    def test_every_console_screen_is_behind_the_gate(self, page: Path) -> None:
        """ConsoleGate says who may look before any of the screen's requests run."""
        assert re.search(r"<ConsoleGate(\s[^>]*)?>", page.read_text(encoding="utf-8"))
