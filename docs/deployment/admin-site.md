# The admin site

The console opened in a browser, on its own host, signed in with Telegram
OpenID Connect. The code is the Mini App's console (`web/src/console/`) and the
same webapi; the decision and its reasons are in
[docs/invariants.md](../invariants.md) under «Mini App».

## It is on when it is configured

`WEBAPI_ADMIN_URL`, `WEBAPI_OIDC_CLIENT_ID` and `WEBAPI_OIDC_CLIENT_SECRET` all
set. Unset, the sign-in routes answer 404 and the webui's console host matches
nothing. The URL is the only place the host is written down: the deploy works
Caddy's host out from it (`scripts/admin_host.sh`), and the webapi derives the
redirect and its allowed origin. Both refuse a URL that is the Mini App's host,
or has a port, a path or no https: the first would take that site's traffic,
the others would match no request. The sign-in routes are 404 on the Mini App's
host, which sits behind Cloudflare, where the client address a rate limit
needs is not the client's.

## Outside this repository

- **BotFather**: the bot's Login Widget settings hold the Allowed URLs, the
  origin and `<origin>/api/auth/telegram/callback`, and show the Client ID and
  Secret. Telegram refuses any URL not registered there. The bot's name and
  picture are what the consent screen shows.
- **DNS and the edge proxy** (the edge Caddy on the host, not this repository):
  a record for the host that is DNS-only, without Cloudflare's proxy, and a
  block that proxies it to the webui's port with the client address as the
  edge sees it. The webui trusts that header; Cloudflare's own headers are not
  read anywhere. Where the edge's configuration lives, and the traps in
  changing it, are in the knowledge base page for that host.

## After the first deploy

Opening the console host in a browser lands on the sign-in page; a super admin
signs in and a stranger is told they have no access. Eleven callbacks within a
minute, each with a different forged `X-Forwarded-For`, must still end in a 429
on the eleventh: it shows the edge replaces what a client sends rather than
appending to it. The Mini App opens as
before in Telegram on iOS, Android and Desktop: a write that carries the console's
cookie must now name our origin, so a client that stops sending `Origin` would
be refused.
