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
a dead end for the other. The app's screens, which search engines must not
keep, say so with X-Robots-Tag.

With --site it reads the public site's own Caddyfile (docker/site/, the site
container on konnekt.cz) instead: the site's paths are its pages, the
catalog pages reach its Node server without a browser's cookies, «Открыть
Konnekt» reaches the catalog the same way, and every other path is a 301 to
the app's host (APP_URL) that keeps the path and the query.

Usage: caddy adapt ... | python3 docker/check-routes.py
(run with ADMIN_HOST=admin.example.test in the adapting environment)
       caddy adapt ... | python3 docker/check-routes.py --site
(the site's Caddyfile, with APP_URL=https://app.example.test)
"""

import fnmatch
import json
import re
import sys

WEBAPI = "webapi:8787"
CATALOG = "catalog-api:8000"
APP = "/srv/app"
SITE = "/srv/site"
RENDER = "site-render:4321"
ADMIN_HOST = "admin.example.test"
APP_URL = "https://app.example.test"

# Who may frame each host: Telegram's clients the Mini App, nobody the console.
FRAMING = {
    None: "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org",
    ADMIN_HOST: "frame-ancestors 'none'",
}


# Paths whose route falls back to the page when no file matches: a client-side
# route reloaded must get the app, and a missing asset must get a 404, never
# the page (which would then be cached as that asset).
FALLS_BACK = {"/", "/home", "/chats", "/join", "/console", "/console/chats/-100123", "/login", "/administrator"}

# The public site, which search engines read: a page it does not have is a 404,
# never the app's page, and it carries no noindex.
SITE_PATHS = {
    "/",
    "/uk",
    "/uk/",
    "/cs/",
    "/en/articles/student-visa/",
    "/articles",
    "/articles/",
    "/articles/primer/",
    "/robots.txt",
    "/sitemap-index.xml",
    "/sitemap-0.xml",
    "/_astro/Base.abc123.css",
    "/favicon.ico",
    "/favicon.svg",
    "/apple-touch-icon.png",
}

# What each host says to search engines on every response, apart from each
# route's own: nothing site-wide on the Mini App's; never index the console's.
ROBOTS = {None: None, ADMIN_HOST: "noindex"}

# The app's, on the site's host: a 301 to the app keeping the path and query.
TO_APP = f"301 {APP_URL}{{http.request.uri}}"
# A catalog address without its final slash: to the same with it, query kept.
SLASHED = "308 {}/{{http.request.uri.prefixed_query}}"


def public_site() -> dict[str, str]:
    """The site container's one host: its pages, the way into the bot, and the app's paths sent on."""
    return {
        **dict.fromkeys(SITE_PATHS, SITE),
        # The catalog pages, rendered on request.
        "/universities/": RENDER,
        "/universities/cvut/": RENDER,
        "/uk/universities/": RENDER,
        "/en/universities/cvut/": RENDER,
        "/chats/": RENDER,
        "/cs/chats/": RENDER,
        "/sitemap-catalog.xml": RENDER,
        "/universities": SLASHED.format("/universities"),
        "/uk/universities": SLASHED.format("/uk/universities"),
        "/en/chats": SLASHED.format("/en/chats"),
        "/universities/cvut": SLASHED.format("/universities/cvut"),
        "/en/universities/cvut": SLASHED.format("/en/universities/cvut"),
        "/api/v1/open": CATALOG,
        # The guides' old addresses, to the articles' in the same language.
        "/guides": "301 /articles/{http.request.uri.prefixed_query}",
        "/uk/guides": "301 /uk/articles/{http.request.uri.prefixed_query}",
        "/guides/": "301 /articles/{http.request.uri.prefixed_query}",
        "/guides/primer/": "301 /articles/primer/{http.request.uri.prefixed_query}",
        "/uk/guides/": "301 /uk/articles/{http.request.uri.prefixed_query}",
        "/en/guides/visa/": "301 /en/articles/visa/{http.request.uri.prefixed_query}",
        # Not a guide: a word that merely starts so is the app's.
        "/guidesx": TO_APP,
        # Old buttons in Telegram name this host; the app is on its own now.
        "/home": TO_APP,
        "/chats": TO_APP,
        "/chats/cvut": TO_APP,
        "/join": TO_APP,
        "/console/chats/-100123": TO_APP,
        "/ukraine": TO_APP,
        # Nothing else of the API is the site's.
        "/api/public/catalog": TO_APP,
        "/api/v1/me": TO_APP,
        "/healthz": TO_APP,
        "/assets/index-abc123.js": TO_APP,
    }


def expectations() -> dict[str | None, dict[str, str]]:
    """Host (None: the Mini App's) → sample path → where it must end up."""
    return {None: mini_app(), ADMIN_HOST: console()}


def console() -> dict[str, str]:
    """The console's own host: itself and its API, and nothing of the Mini App's."""
    return {
        "/api/auth/telegram/login": WEBAPI,
        "/api/auth/me": WEBAPI,
        "/api/stats/home": WEBAPI,
        # The catalog's screens, asked of the catalog by webapi for this host's session.
        "/api/catalog/admin/catalog": WEBAPI,
        # Not this host's: the catalog's API, the public half, the catalog's health.
        "/api/v1/me": "404",
        "/api/public/catalog": "404",
        "/healthz": "404",
        # Prometheus reads the metrics on the Mini App's host; this one has no business with them.
        "/api/internal/metrics": "404",
        "/api/v1/internal/metrics": "404",
        "/console": APP,
        "/console/chats/-100123": APP,
        "/login": APP,
        "/assets/index-abc123.js": APP,
        # The browser's tab asks for the icon at the root, whatever the page names.
        "/favicon.ico": APP,
        "/favicon.svg": APP,
        "/apple-touch-icon.png": APP,
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
        # What Prometheus scrapes (each closed by its own bearer token): the web API's and the catalog's.
        "/api/internal/metrics": WEBAPI,
        "/api/v1/internal/metrics": CATALOG,
        # The browser's sign-in is the console host's: here the client address is Cloudflare's.
        "/api/auth/telegram/login": "404",
        "/api/auth/telegram/callback": "404",
        # So are the catalog's screens through webapi: only a session of the
        # console's own host may ask for them.
        "/api/catalog/admin/catalog": "404",
        "/api/catalog/taxonomy/institutions": "404",
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
        "/home": APP,
        "/chats": APP,
        "/join": APP,
        "/assets/index-abc123.js": APP,
    }


def site_routes(config: dict, host: str | None) -> list[dict]:
    """The routes of the site that answers `host`; None is the one with no host.

    Each site is one terminal route holding a subroute, and Caddy tries the
    named hosts before the catch-all. A Caddyfile with one site and no host
    (the site container's) is laid out flat instead: its routes are the server's.
    """
    servers = config["apps"]["http"]["servers"]
    (server,) = servers.values()
    wrapped = all(
        route.get("terminal") and [h.get("handler") for h in route.get("handle", [])] == ["subroute"]
        for route in server["routes"]
    )
    if not wrapped:
        return [] if host else server["routes"]
    for site in server["routes"]:
        hosts = [h for m in site.get("match", []) for h in m.get("host", [])]
        if (host in hosts) if host else not hosts:
            (subroute,) = site["handle"]
            return subroute["routes"]
    return []


def site_header(routes: list[dict], name: str) -> str | None:
    """A header a site sets on every response, if it does."""
    for route in routes:
        if route.get("match"):
            continue
        for handler in route.get("handle", []):
            if handler.get("handler") == "headers":
                value = handler.get("response", {}).get("set", {}).get(name)
                if value:
                    return value[0]
    return None


def framing(routes: list[dict]) -> str | None:
    """The `Content-Security-Policy` a site sets on every response, if it does."""
    return site_header(routes, "Content-Security-Policy")


def robots(route: dict) -> str | None:
    """The X-Robots-Tag a route sets, if it does."""
    for handler in handlers(route):
        if handler.get("handler") == "headers":
            value = handler.get("response", {}).get("set", {}).get("X-Robots-Tag")
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
    """Fill a redirect's `{http.regexp.<name>.<n>}` from the path it matched (empty, as in Caddy, when a group took no part)."""
    for match in route.get("match", []):
        regexp = match.get("path_regexp")
        found = regexp and re.search(regexp["pattern"], path)
        if found:
            for index, group in enumerate(found.groups(), start=1):
                location = location.replace(f"{{http.regexp.{regexp['name']}.{index}}}", group or "")
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


def try_files(route: dict) -> list[str]:
    """The files a route tries, in order, if it tries any."""
    for handler in handlers(route):
        for sub in handler.get("routes", []):
            for match in sub.get("match", []):
                if "try_files" in match.get("file", {}):
                    return match["file"]["try_files"]
    return []


def falls_back(route: dict) -> bool:
    """Whether a route rewrites a missing file to the app's page, or always does."""
    return "/index.html" in try_files(route) or any(
        h.get("handler") == "rewrite" and h.get("uri") == "/index.html" for h in handlers(route)
    )


def not_found(route: dict) -> bool:
    """Whether a route answers 404 when no file matches."""
    return any(
        h.get("handler") == "static_response" and h.get("status_code") in (404, "404") for h in handlers(route)
    ) or ("=404" in try_files(route))


# What only the console's server may tell the catalog: it signs an operator in
# with them over the containers' own network. From a browser they are a guess
# at the token, and the catalog must never see one.
SERVICE_HEADERS = ("X-Catalog-Service", "X-Catalog-Operator", "X-Catalog-Lang")


def service_headers_kept(proxy: dict) -> list[str]:
    """The service headers a proxy would pass on from the client."""
    deleted = proxy.get("headers", {}).get("request", {}).get("delete", [])
    return [name for name in SERVICE_HEADERS if name not in deleted]


def catalog_proxies(node: object) -> list[dict]:
    """Every reverse_proxy in the config that dials the catalog, wherever it sits.

    Not only the ones a sample path reaches: a second route to the catalog,
    on any host, must strip the same headers.
    """
    found: list[dict] = []
    if isinstance(node, dict):
        if node.get("handler") == "reverse_proxy" and any(u.get("dial") == CATALOG for u in node.get("upstreams", [])):
            found.append(node)
        for value in node.values():
            found.extend(catalog_proxies(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(catalog_proxies(item))
    return found


def cookie_free(proxy: dict) -> bool:
    """Whether a proxy drops cookies in both directions."""
    headers = proxy.get("headers", {})
    return "Cookie" in headers.get("request", {}).get("delete", []) and "Set-Cookie" in (
        headers.get("response", {}).get("delete", [])
    )


def problems(route: dict, path: str, expected: str, inherited: str | None = None) -> list[str]:
    """What is wrong with how `route` serves `path`, if anything.

    `inherited` is the X-Robots-Tag the whole site sets, which every route carries.
    """
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
    if expected == RENDER and not cookie_free(proxy):
        out.append("is proxied with cookies")
    if expected == CATALOG and not cookie_free(proxy):
        # The console's session is valid on this whole origin, and the
        # catalog authenticates by initData alone: not its to receive.
        out.append("is proxied with cookies")
    if expected == CATALOG and (kept := service_headers_kept(proxy)):
        out.append(f"passes on {', '.join(kept)} from the client")
    if not proxy and expected == APP and falls_back(route) != (path in FALLS_BACK):
        out.append("falls back to the page" if falls_back(route) else "does not fall back to the page")
    if expected == SITE and falls_back(route):
        out.append("falls back to the app's page")
    if expected == SITE and not not_found(route):
        out.append("does not answer 404 for a page the site lacks")
    if path in FALLS_BACK and expected == APP and (robots(route) or inherited) != "noindex":
        out.append("lets search engines index an app screen")
    if expected == SITE and robots(route):
        out.append(f"tells search engines {robots(route)}")
    return out


def main() -> int:
    config = json.load(sys.stdin)
    failed = False
    on_site = "--site" in sys.argv[1:]
    proxies = catalog_proxies(config)
    if not proxies:
        print("no proxy to the catalog found: the walk is looking in the wrong place")
        failed = True
    for index, proxy in enumerate(proxies, start=1):
        kept = service_headers_kept(proxy)
        if kept:
            print(f"catalog proxy #{index} passes on {', '.join(kept)} from the client")
            failed = True
        if not cookie_free(proxy):
            print(f"catalog proxy #{index} is proxied with cookies")
            failed = True
    for host, samples in ({None: public_site()} if on_site else expectations()).items():
        label = host or ("site" if on_site else "mini app")
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
        told = site_header(site, "X-Robots-Tag")
        if told != ROBOTS[host]:
            print(f"{label}: X-Robots-Tag is {told}, not {ROBOTS[host]}", file=sys.stderr)
            failed = True
        for path, expected in samples.items():
            chosen = next((r for r in terminal if matches(r, path)), None)
            found = problems(chosen, path, expected, told) if chosen else ["is handled by nothing"]
            for problem in found:
                print(f"{label} {path} {problem}", file=sys.stderr)
            failed = failed or bool(found)
            if not found:
                print(f"{label} {path} → {expected}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
