"""Each path the webui serves goes to the backend or build that owns it.

Reads the Caddyfile as Caddy itself understands it (`caddy adapt` output on
stdin), walks the routes the way Caddy picks them, and checks where a sample
path of each kind lands. By behaviour rather than by matcher shape: a path
sent to the wrong place comes back 404 or as the wrong app, and nothing else
in CI would notice. The same goes for a route that falls back to the page
where it must not, or the other way round, for a cookie leaving for the
catalog, and for a browser's X-Catalog-* headers reaching it.

The Caddyfile serves two hosts: the Mini App's, which answers anything, and
the console's, named by ADMIN_HOST, which answers only the console and its API.
Each is checked on its own, because a path that is right for one is a leak or
a dead end for the other.

Usage: caddy adapt ... | python3 docker/check-routes.py
(run with ADMIN_HOST=admin.example.test in the adapting environment)
"""

import fnmatch
import json
import re
import sys

WEBAPI = "webapi:8787"
CATALOG = "catalog-api:8000"
APP = "/srv/app"
ADMIN_HOST = "admin.example.test"

# Who may frame each host: Telegram's clients the Mini App, nobody the console.
FRAMING = {
    None: "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org",
    ADMIN_HOST: "frame-ancestors 'none'",
}


# Paths whose route falls back to the page when no file matches: a client-side
# route reloaded must get the app, and a missing asset must get a 404, never
# the page (which would then be cached as that asset).
FALLS_BACK = {"/", "/chats", "/join", "/console", "/console/chats/-100123", "/login", "/administrator"}


def expectations() -> dict[str | None, dict[str, str]]:
    """Host (None: the Mini App's) → sample path → where it must end up."""
    return {None: mini_app(), ADMIN_HOST: console()}


def console() -> dict[str, str]:
    """The console's own host: itself and its API, and nothing of the Mini App's."""
    return {
        "/api/auth/telegram/login": WEBAPI,
        "/api/auth/me": WEBAPI,
        "/api/stats/home": WEBAPI,
        # Not this host's: the catalog's API, the public half, the catalog's health.
        "/api/v1/me": "404",
        "/api/public/catalog": "404",
        "/healthz": "404",
        "/console": APP,
        "/console/chats/-100123": APP,
        "/login": APP,
        "/assets/index-abc123.js": APP,
        # Everything else is the console's front door, never the landing page.
        "/": "302 /console",
        "/chats": "302 /console",
        "/join": "302 /console",
        "/admin": "302 /console",
    }


def mini_app() -> dict[str, str]:
    """The Mini App's host: sample path → where it must end up."""
    return {
        # The catalog's API: the help screens, profiles, requests.
        "/api/v1/me": CATALOG,
        "/healthz": CATALOG,
        # Everything else under /api is this repository's webapi.
        "/api/public/catalog": WEBAPI,
        "/api/auth/webapp": WEBAPI,
        # The browser's sign-in is the console host's: here the client address is Cloudflare's.
        "/api/auth/telegram/login": "404",
        "/api/auth/telegram/callback": "404",
        # The console is the app's now; the old console's addresses lead there.
        "/console": APP,
        "/console/chats/-100123": APP,
        "/admin": "301 /console",
        "/admin/chats": "301 /console/chats",
        "/admin/chats/-100123": "301 /console/chats/-100123",
        "/admin/chats/graph": "301 /console/chats",
        "/admin/hierarchy": "301 /console/chats",
        "/admin/catalog": "301 /console/chats",
        "/admin/settings": "301 /console/system",
        "/admin/settings/": "301 /console/system",
        "/admin/": "301 /console",
        # Not the old console's, and the app's to answer.
        "/administrator": APP,
        # The Mini App owns every other path, its client-side routes included.
        "/": APP,
        "/chats": APP,
        "/join": APP,
        "/assets/index-abc123.js": APP,
    }


def site_routes(config: dict, host: str | None) -> list[dict]:
    """The routes of the site that answers `host`; None is the one with no host.

    Each site is one terminal route holding a subroute, and Caddy tries the
    named hosts before the catch-all.
    """
    servers = config["apps"]["http"]["servers"]
    (server,) = servers.values()
    for site in server["routes"]:
        hosts = [h for m in site.get("match", []) for h in m.get("host", [])]
        if (host in hosts) if host else not hosts:
            (subroute,) = site["handle"]
            return subroute["routes"]
    return []


def framing(routes: list[dict]) -> str | None:
    """The `Content-Security-Policy` a site sets on every response, if it does."""
    for route in routes:
        for handler in route.get("handle", []):
            if handler.get("handler") == "headers":
                value = handler.get("response", {}).get("set", {}).get("Content-Security-Policy")
                if value:
                    return value[0]
    return None


def matches(route: dict, path: str) -> bool:
    """Whether Caddy would pick this route for `path`. No matcher matches all.

    Path globs and path_regexp, the two kinds this Caddyfile uses; Caddy
    compares paths case-insensitively, and so does this.
    """
    if not route.get("match"):
        return True
    for match in route["match"]:
        if any(fnmatch.fnmatch(path.lower(), p.lower()) for p in match.get("path", [])):
            return True
        regexp = match.get("path_regexp")
        if regexp and re.search(regexp["pattern"], path):
            return True
    return False


def expand(location: str, route: dict, path: str) -> str:
    """Fill a redirect's `{http.regexp.<name>.<n>}` from the path it matched."""
    for match in route.get("match", []):
        regexp = match.get("path_regexp")
        found = regexp and re.search(regexp["pattern"], path)
        if found:
            for index, group in enumerate(found.groups(), start=1):
                location = location.replace(f"{{http.regexp.{regexp['name']}.{index}}}", group)
    return location


def handlers(route: dict) -> list[dict]:
    """Every handler under a route, however deeply nested in subroutes."""
    out: list[dict] = []
    stack = list(route.get("handle", []))
    while stack:
        handler = stack.pop()
        out.append(handler)
        for sub in handler.get("routes", []):
            stack.extend(sub.get("handle", []))
    return out


def falls_back(route: dict) -> bool:
    """Whether a route rewrites a missing file to the page (`try_files`), or always does."""
    return any(
        "try_files" in match.get("file", {})
        for handler in handlers(route)
        for sub in handler.get("routes", [])
        for match in sub.get("match", [])
    ) or any(h.get("handler") == "rewrite" and h.get("uri") == "/index.html" for h in handlers(route))


# What only the console's server may tell the catalog: it signs an operator in
# with them over the containers' own network. From a browser they are a guess
# at the token, and the catalog must never see one.
SERVICE_HEADERS = ("X-Catalog-Service", "X-Catalog-Operator", "X-Catalog-Lang")


def service_headers_kept(proxy: dict) -> list[str]:
    """The service headers a proxy would pass on from the client."""
    deleted = proxy.get("headers", {}).get("request", {}).get("delete", [])
    return [name for name in SERVICE_HEADERS if name not in deleted]


def cookie_free(proxy: dict) -> bool:
    """Whether a proxy drops cookies in both directions."""
    headers = proxy.get("headers", {})
    return "Cookie" in headers.get("request", {}).get("delete", []) and "Set-Cookie" in (
        headers.get("response", {}).get("delete", [])
    )


def problems(route: dict, path: str, expected: str) -> list[str]:
    """What is wrong with how `route` serves `path`, if anything."""
    found = handlers(route)
    proxy = next((h for h in found if h.get("handler") == "reverse_proxy"), None)
    redirect = next((h for h in found if h.get("handler") == "static_response"), None)
    if redirect and not proxy:
        given = redirect.get("headers", {}).get("Location")
        # A response with no Location is a refusal, not a redirect.
        where = (
            f"{redirect.get('status_code')} {expand(given[0], route, path)}"
            if given
            else str(redirect.get("status_code"))
        )
        return [] if where == expected else [f"goes to {where}, not {expected}"]
    if proxy:
        where = ",".join(u.get("dial") for u in proxy.get("upstreams", []))
    else:
        roots = [h["root"] for h in found if h.get("handler") == "vars" and "root" in h]
        serves = any(h.get("handler") == "file_server" for h in found)
        where = roots[0] if roots and serves else None
    if where != expected:
        return [f"goes to {where or 'nothing'}, not {expected}"]
    out = []
    if expected == CATALOG and not cookie_free(proxy):
        # The console's session is valid on this whole origin, and the
        # catalog authenticates by initData alone: not its to receive.
        out.append("is proxied with cookies")
    if expected == CATALOG and (kept := service_headers_kept(proxy)):
        out.append(f"passes on {', '.join(kept)} from the client")
    if not proxy and falls_back(route) != (path in FALLS_BACK):
        out.append("falls back to the page" if falls_back(route) else "does not fall back to the page")
    return out


def main() -> int:
    config = json.load(sys.stdin)
    failed = False
    for host, samples in expectations().items():
        label = host or "mini app"
        # `handle` blocks share a group and exactly one of them runs: the
        # first whose matcher fits. Routes outside a group (encode) pass through.
        site = site_routes(config, host)
        if not site:
            print(f"{label}: no site answers this host", file=sys.stderr)
            failed = True
            continue
        terminal = [r for r in site if "group" in r]
        wanted = FRAMING[host]
        if framing(site) != wanted:
            print(f"{label}: framing is {framing(site)}, not {wanted}", file=sys.stderr)
            failed = True
        for path, expected in samples.items():
            chosen = next((r for r in terminal if matches(r, path)), None)
            found = problems(chosen, path, expected) if chosen else ["is handled by nothing"]
            for problem in found:
                print(f"{label} {path} {problem}", file=sys.stderr)
            failed = failed or bool(found)
            if not found:
                print(f"{label} {path} → {expected}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
