# Architecture

Three layers and one rule about each. This document is the contract new code
is held to; where the code does not meet it yet, that is written down at the
bottom rather than left to be discovered.

```
api/       HTTP. Parse the request, authorise, delegate, serialise.
services/  The rules. Everything a second caller would need to reuse.
db/        Models, session, migrations. No behaviour.
```

**The bot is not ours to run.** The token this process holds belongs to the
Konnekt moderator bot (`supervisor-telegram`), and that process receives every
update by polling. Telegram gives a token one consumer: a webhook set from here
would stop the moderator's polling, and the moderator's `deleteWebhook` on start
would silence us. So this process never asks for updates. It does not register
a webhook, does not call `getUpdates`, and does not set the command list or the
menu button. It has no `/tg/webhook` route. `/start`, the greeting and the
chat's menu belong to the moderator bot.

It uses the token for two things only. `core/security.py` checks the Mini App's
`initData` against it, which is why the app has to be opened from the moderator
bot. `services/notify.py` sends messages through it. Sending does not compete
with polling, so notifications keep arriving from the same bot people opened
the app from.

**Who may be written to is what Telegram says in `initData`.** A bot may only
message somebody who allowed it, and the record of that is the
`allows_write_to_pm` flag Telegram signs into the app's `initData`, because
`/start` is not ours to see. `current_user` passes it to
`people.remember`, which sets `bot_started_at` (the first time only) and
`bot_can_message`. The flag is absent when the app was opened without that
permission, and then nothing is recorded, so `notify` does not try a send that
Telegram would refuse with a 403.

A `bot_started_at` recorded under an earlier bot (`@student_cz_bot`, then
`@konnekt_moder_bot`) does not say which bot it was. Such a person counts as
reachable until the first send through the moderator bot comes back as a 403.
`mark_unreachable` then records it as `BOT_BLOCKED`, although they never
blocked anything (the event keeps Telegram's reason, "bot can't initiate
conversation", which tells it apart from a real block), and their next visit
through the moderator bot makes them reachable again. That notification is
lost either way, because they have not started the moderator bot. The only
cost is one misleading event per person.

**The token is also a trust boundary we share.** Every Mini App on the
moderator bot checks `initData` against the same token, and that includes the
`supervisor-telegram` console, which signs super admins in from it. Valid
`initData` for one app is valid for all of them, so a leaked `initData`
string or an XSS in any of these apps reaches the others.

**Nothing attributes a visit yet.** `users.source` is the first `start_param`
we see, and Telegram sends one only through a Mini App deep link such as
`t.me/konnekt_cz_bot/<app>?startapp=<source>`. The catalog is not
registered as a named Mini App of the moderator bot, so no such link reaches
it. A `?start=<source>` link goes to the moderator bot's `/start`.

**What we say is part of what we do.** A sentence telling somebody how to undo
something, or who can see their request, or how fast an answer comes, is a
claim about the code — and it is the kind that rots quietly, because nobody
tests prose and the person who finds out is the one who tried it. The rule is
that copy names only what exists: no command nothing implements, no section the
catalog cannot show, no filter that does not filter. When a promise and the
code disagree, cutting the promise is a fix, not a retreat.

The rule is younger than the copy, and the copy has not all been brought to it
yet — what is still owed is listed at the bottom of this document.

**Opting out has no door here.** `users.unsubscribed_at` stays, and
`notify` still does not read it: an answer to your own request is not us
writing to you unprompted. The `/stop` that wrote it went with the bot's
handlers, and nothing sends broadcasts yet. Whichever process sends the first
one owns the way out of it.

Nothing here is DDD. There are no aggregates, no repository per model, no
command bus. This is a catalog with two dozen endpoints, a borrowed bot token and one
database; layering it further would cost more than it returns.

## One name

The product is **Students CZ**, and so is everything that can be renamed
without moving data: the Python package `students_cz`, the images
`students-cz-api`, the compose project, the containers,
`deploy/students-cz`. `konnekt` was the working title and it is gone from
everywhere a person reads.

Three places keep it, each for a reason and each said out loud where it sits:

| Where | Why |
| --- | --- |
| The docker volumes | The data is in them. A compose volume is `<project>_<name>`, so a rename is a move, not an edit — see `docs/deploy.md`. |
| `LEGACY_STORAGE_KEY` / `LEGACY_OVERRIDE_KEY` in the web app (`web/`) | Somebody's saved theme and language. Read once and moved across, so the rename does not reset everyone to their phone's defaults. |
| The Postgres role and database | Invisible, and renaming them costs a dump and a restore. |

The catalog lived in the `teachers-catalog` repository until 30 September
2026, and its history is there; it is `catalog/` in `supervisor-telegram` now,
beside the bot, the webapi and the Mini App.

## One origin, two APIs

The Mini App is `web/`, served at `PUBLIC_BASE_URL` (konnekt.azamat.io) beside the
moderator console. It reads from two APIs. `/api/v1/*` is the catalog's;
`/api/public/*` is the webapi's: the chat directory (`catalog`), the
advertising reach (`reach`) and the join check (`join-check`). Telegram lets a
Mini App call only its own origin, so the router in front of the app
(`docker/Caddyfile`) sends `/api/v1/*` and `/healthz` to the catalog inside
the stack. For the browser it is one host.

The catalog has no host of its own. Its old one, `tutors.azamat.io`, answers
301 to the same path under `PUBLIC_BASE_URL`, so a link shared before the move lands
on the app. The bot's buttons open `PUBLIC_BASE_URL` too.

The rules below about the app's screens, and «The web shell scrolls in exactly
one place», govern that `web/` directory. They stay here because the product
they describe is this one.

The catalog API never calls `/api/public/*`, and the app reads only what those
endpoints publish: a chat's title, link, group, university code, activity,
member count and whether it has topics, and reach summed per group.
The fields are supervisor's contract. `group` is the section's title: the
parent chat's, or the chat's own when others sit under it. It changes
whenever supervisor changes how it groups chats. No group name is written in
the app. A section's address carries its name, and a name that no
longer exists shows as gone. The app checks what arrives: an item without a
title or a `t.me` link is dropped, and an activity it does not know counts as
`unknown`.

Every `/api/v1/*` request reaches the catalog from the router, not from the
user's address, so the limit is per person, not per IP: a per-IP limit, or a
Cloudflare rate rule in front of this host, would throttle every Mini App user
as one client. `/search/parse` takes 30 calls a minute per person (it writes
two rows and may run the model) and `/search` 120; past that, 429 with
`Retry-After`. The window is kept in memory, which holds while the API runs
one worker (`--workers 1` in the Dockerfile).

**The chat directory reads the order it is given.** `/chats` is one of three
tabs: Помощь, Чаты and Заявки. The directory keeps supervisor's order, save
one thing, and builds its entries in `lib/chats.ts`:

- the reader's own university comes first. Supervisor names each chat's
  university by the code in `/taxonomy/institutions` (`cvut`), set in the
  console on the chat at the top and carried by the chats under it; the
  reader's is the institution in `/me`, or its university when it is a
  faculty. Everything else keeps supervisor's order, and a reader with no
  institution, or outside Telegram, sees that order unchanged;

- chats that share a `group` form a section, which opens its own screen;
- a group with one chat is not a section, and its chat stands as a row of its
  own, because a screen with one line behind it is a tap for nothing;
- chats without a group come last, under «Остальные», supervisor's own word
  for them;
- the entries above them have no heading: supervisor's groups are top-level
  chats, not a category the app could name;
- a search is flat: the chats whose title or group contains the words, with
  case and diacritics ignored, so `cvut` finds `ČVUT`;
- activity is a chip for `busy`, `active` and `quiet`, and nothing for
  `unknown`, because supervisor says `unknown` when it has not measured enough
  to say anything.

A tap on a chat opens a preview sheet, not Telegram: the chat's university
and city, its member count when supervisor measured one, its activity and
whether it has topics. Only «Открыть чат» in the sheet opens the Telegram link,
so looking at a chat never leaves the app. The rows themselves show no member
counts.

**The ads page is a showcase, not a shop.** `/ads` is for a business that
wants students to see it. It shows two formats and how far they reach, then
hands the conversation to a person in Telegram. It never shows a price: a
price depends on the chats and the season, and nothing here can take a
payment.

- A post in chats: the reach comes from supervisor's `/api/public/reach`,
  summed per group. The member total carries «≈» when fewer chats were
  measured than exist, with a line saying over how many, and is left out when
  none were, because "0 people" would be read and believed. The per-group
  sums are lower bounds in the same way. Group names are shown as supervisor
  sends them, including its own Russian «Остальные» for chats without a group:
  the app writes no group name, and a translated label would need supervisor
  to send a code instead.
- A card in the app: a partner placement as the catalog already shows it, and
  where it appears. Today that is «Не про учёбу» only, because it is the one
  screen that asks for placements; the other slots are named on the page when
  a screen renders them. Targeting by month and interface language works;
  targeting by service needs a screen that sends the service, so the page does
  not offer it yet. The example is fetched with `preview=true`
  and drawn without a button: listing placements records an impression and
  tapping one a click, and a business looking at the showcase is neither. It
  must not be billed to the partner.
- Contact: `ADS_CONTACT`, a Telegram username, served by `GET /api/v1/ads`.
  Unset, the page offers no button, so it does not promise a conversation
  nobody will answer.

The page is reached from the profile and from the note under «Документы и
жизнь» on the offer screen. That note tells a company where to go instead of
warning private people about fees: private people offer those services for
free.

**The join check answers one question and then shows the way on.** `/join`
is where a person lands from a join request to a moderated chat: supervisor
sends them a Mini App button with `?q=<query id>`. The page sends the signed
`initData` and that id to supervisor's `POST /api/public/join-check`, which
approves the request. It needs both. Opened without them, it says to open it
from the join request instead of offering a button that cannot work. After
it passes, it does not close itself: it offers the chat directory and the help
catalog, because for many people this is the first screen of the app they
see. The dead ends (opened without a request, or refused) offer the same two
ways on. Supervisor answers with a status only, so the page does not name the
chat, and only an `approved` status counts.

Only a 403 means refused: the request expired or belongs to another account.
Any other failure (the network, the proxy, supervisor or Telegram) keeps the
button, says it did not get through, and lets the person try again, because
telling somebody to reapply over our own outage sends them away for nothing.
Supervisor marks a check spent before it asks Telegram, so a 403 after a retry
may mean the first attempt went through. The page says so and points to the
chat instead of telling the person to reapply.

The outcome is kept for the tab's session under its query id. Coming back to
`/join` by any route (the back button, the avatar) shows the settled answer,
not a button for a check that is already spent. History is not rewritten:
`/join` is often the first entry, and replacing it would leave Telegram's back
button with nowhere to go.

Opening the app registers the person like any other visit, so everyone who
passes a join check becomes a catalog user with no `source`. That is
intended: it is their first screen of the app.

## `api/v1`, one module per domain

Each module owns a slice of the URL space and nothing else. The prefix is
declared once, in `api/v1/__init__.py`, so a module cannot disagree with its
neighbours about where it lives.

| Module | What it serves |
| --- | --- |
| `public.py` | `/open` — the only route without init data |
| `me.py` | the account behind the init data |
| `taxonomy.py` | service types, subjects, institutions, languages |
| `search.py` | free-text parse — the rule is `services/search.py` — and the search it feeds |
| `browse.py` | the home screen, a person's page, starting a contact |
| `cabinet.py` | a helper's own profile: reading it and saving it |
| `requests.py` | the catalog in reverse — post, answer, accept, close |
| `placements.py` | partner placements |
| `admin.py` | what the operator reads in the console, and the partner cards they run; see below |
| `health.py` | `/healthz`, on its own router with no prefix |

`health.py` is deliberately outside the versioned router: `/healthz` is what
the deploy and the shared edge Caddy watch, and it must not move when the API
version does.

**The operator reads the catalog and runs the partner cards.** The moderator
console (in `supervisor-telegram`'s app) shows the catalog to the people named
in `ADMIN_TG_IDS`, the same Telegram ids as supervisor's `ADMIN_SUPER_ADMINS`.
They sign in with the same init data as anybody else; `/me` says `is_admin`,
and `/admin/*` answers 403 to everybody not on the list. The console writes two
things: a profile's moderation (kept or hidden) and the partner cards, because
otherwise the only way to do either is the database.

- `/admin/catalog`: listed profiles no operator has kept or hidden yet,
  however old, newest first (those out before the console moderated were
  counted as looked at), and the profiles an operator hid;
  requests nobody has answered that can still be answered (open and before
  their deadline), oldest first; and searches that found nothing in the last
  30 days, grouped by their text ignoring case and leading or trailing spaces, most frequent
  first. Each list is capped; the counts give each list's full length, and the
  number of requests posted this week.
- `GET /admin/profiles/{id}`: one profile as the operator moderates it.
  `POST …/review` keeps it: `reviewed_at` is set and it leaves the new list,
  still listed. `POST …/hide` sets it `banned`, which its owner cannot lift
  by publishing again, and `POST …/restore` lists it again. Only a published
  profile can be hidden and only a banned one restored (409 otherwise), so
  restoring never undoes an owner's own «hide me». Each is one conditional
  `UPDATE`, and the owner's save locks the row, so neither side overwrites
  the other in a race. The owner is not told.
- `/admin/partners`: every placement, active or not, with its impressions and
  clicks over the last 30 days.
- `POST /admin/placements`: a new card on the Life screen, the one slot the
  app draws. It takes the partner's name, an `https` link, the title and,
  optionally, a subtitle, a price, a note and a monogram of up to four
  letters. A partner is reused when one of that name, ignoring case, exists.
  The new card goes first, above every card there is: a slot shows three at
  most, by priority and then newest first, so the operator sees what they
  just added, and the lowest card drops off until another is switched off.
  The text is stored in the operator's language; a reader in another language
  sees it too, since a card shows the first text it has when none is in theirs.
- `PATCH /admin/placements/{id}`: switches a card on or off. Stopping is how
  a card ends; nothing is deleted, so its impressions and clicks stay.

It names people as the catalog does, a first name and an initial: no handle,
no Telegram id, no contact. The console opens a profile in a sheet of its own,
and «Как видят ученики» opens it through the app like anybody else; it lists
only the services the catalog lists.

There is no shared-helpers module here. What two domains both need is a rule,
and a rule belongs in `services/` — that is what stops this package growing a
second god module to replace the one it was split out of.

## What belongs where

**An endpoint** reads the request, checks who is asking, calls one service,
and renders a schema. If it contains a rule — a permission check beyond
"logged in", a multi-step write, ranking, a state machine — that rule belongs
in a service, where a test can reach it without an HTTP client and a live
database.

**A write is a rule**, even a one-line one. An endpoint does not add a row: a
row added in a handler is a fact about the product that only an HTTP test can
reach. The two that read like exceptions
are not: `catalog.open_home` and `catalog.view_helper` are the plain readers
plus the event each records, kept apart from `home_sections` and
`helper_detail` so that reading the sections is not itself a claim that
somebody opened the app.

**A service** takes a session and plain values, and returns DTOs. It does not
raise `HTTPException`: an HTTP status is a fact about a protocol, and a
service that knows about protocols cannot be called from anywhere else.

What it raises instead lives in `services/errors.py` — `NotFound`,
`Forbidden`, `Conflict`, `Invalid`, `BadRequest` — and one handler in
`main.py` turns each into its status code, walking the class hierarchy so a
subclass keeps its family's answer.

**A name is a rule too.** Every reference table keeps its names in a side
table, one row per language, and `services/naming.py` is the only place that
reads them: which translation to show, what to fall back to when the asked
language has none, and how to fetch a page's worth of them in one query. Five
modules need that, which is what makes it a rule rather than a helper belonging
to whichever module wrote it first.

**What a handler needs arrives as a dependency.** A route does not reach into
`app.state`. What the process was started with — the bot, the settings — is
composed into something usable in `api/deps.py` and asked for by type:
`SessionDep`, `UserDep`, `LangDep`, `NotifierDep`. The reason is not tidiness.
`app.state` is populated by the lifespan, which does not run under the test
client, so every route reaching for it had to decide what "it is not there"
means — and each of them decided quietly, with a `getattr` default. There is
one answer to that question per thing, it belongs where the thing is built, and
a dependency is also the only shape a test can substitute.

**Two notifications and one ping.** `services/notify.py` writes to people
about something they set in motion — an answer to their request, an acceptance
of their answer. `Notifier.tell_owner` is the other kind and is kept apart from
it: one message to one address, `OWNER_TG_ID`, about a profile or a request
appearing. It is not product copy — nobody reading it chose a language, and it
is addressed to whoever runs this — so it lives in `bot/texts.py` as a plain
string rather than a table per language, and it is off unless that setting
names somebody. It carries one button, «Открыть в консоли», which opens the
console's catalog screen (`PUBLIC_BASE_URL/console/catalog`), where recent profiles
and unanswered requests are listed: the ping is the reason to look, the
console is where to look. The owner should be one of `ADMIN_TG_IDS`, or the
button opens a refusal. No button when the app's address is not https, as for the others. A
ping that cannot be sent, like a notification that cannot, costs the action
nothing: both are queued after the response and neither may raise.

**State the process keeps is a service, not an attribute.** `Notifier` is one:
a bot and an address, decided once. `telegram.BotHandle` is the other, and it
was the harder case — it holds the bot's own handle and the cooldown that
stops a failing Telegram being asked again on every landing visit, which is
per-process state rather than a value. `api/deps.py` builds it on the first
request that needs it and keeps it on `app.state`; a route asks for
`HandleDep` and cannot tell whether there is a bot at all, because a handle
with no bot answers `None`.

Built in `deps.py` and not in the lifespan, deliberately: the lifespan does
not run under the test client, so a handle built there would leave the tested
path and the production path as different code.

**A schema** is a leaf. `students_cz/schemas.py` — the package root, not inside
`api/` — describes what goes over the wire. A service may return one without
that pointing the domain layer at the HTTP layer, which is the whole reason it
sits there.
Screens are assembled server-side — the client renders what it is given rather
than joining data itself — so a schema often mirrors a screen, and that is
intended.

**The document is committed**, as `catalog/openapi.json`, and CI fails when it
is out of date (`make contract` rewrites it): a schema changed without it
leaves the app's client typed against an endpoint the API does not serve. It
is the contract for the Mini App in `web/`, which generates its client from
this file and fails CI when regenerating changes the committed client — so a
schema change and the client it needs arrive in one pull request. The API does
serve `/openapi.json`, but the router sends only `/api/v1/*` and `/healthz` to
it, and a live endpoint cannot be pinned to a revision anyway. A checked-in
file can.

The app's client covers what has moved across, and that is not yet the whole
wire: its `src/lib/types.ts` still declares most types by hand, and nothing
compares those to the API.

## One engine, one pool

`db/session.py` holds the engine and the sessionmaker as module singletons,
created once and lazily. Not on `app.state`, deliberately: the API is not the
only door. The notifier's background task and the seed
scripts all need a session and none of them has a FastAPI app to reach
through, and a second engine would double the connection count against
Postgres without anybody deciding to.

A session is not a connection. Each request gets its own `AsyncSession`; the
connection underneath it is checked out on the first query and handed back
when the session closes, so a screen that runs four queries uses one
connection, not four. FastAPI caches dependencies within a request, so
`SessionDep`, `UserDep` and `LangDep` all resolve to the same session.

`db_pool_size` and `db_max_overflow` are therefore the whole connection budget
for the process — and the Dockerfile pins `--workers 1`, so process and
deployment are the same thing here. Raise them together with the worker count,
never one without looking at the other.

## One transaction per request

**Services never commit. The request commits.**

`db/session.py::session_scope` is the unit of work: it commits when the
handler returns and rolls back when the handler raises. So a request either
happened or it did not, and no endpoint has to remember which of its writes
came before the failure.

The rule is worth more than the tidiness. Answering a request wrote the
response row, committed, and only then rendered the notification to its
author — so a rendering error left an answer in the database that the author
was never told about, and the helper saw a 500 and assumed nothing had
happened. That state is now unreachable by construction rather than by
everybody remembering to put the commit last.

The scope is asked for with `scope="function"`. FastAPI tears a
request-scoped `yield` dependency down *after* the response has been sent and
after its background tasks have run, which would answer 201 to a request whose
commit then failed, and would notify somebody about a row that never landed.
The function stack closes earlier — after the handler has returned and its
response model has been validated, and before the response is sent — so a
serialisation error rolls back too.

Everything that commits outside it:

- `api/deps.py::current_user` commits the person's own row before the handler
  runs, so that first sight of someone — and the `source` that says where they
  came from — survives whatever the handler goes on to do.
- `services/notify.py` opens its own session: it runs in a background task,
  after the response, and therefore after this transaction has closed. Nothing
  is handed an ORM row across that line — a background task gets a
  `notify.Recipient`, a snapshot taken while the session was still open.
  Passing the row itself works only for as long as nothing expires it, and the
  thing that would notice is a `MissingGreenlet` inside a task whose exception
  nobody is waiting for.
- `db/seed.py` and `db/demo.py` are scripts, not requests. They commit because
  nothing else will.

Tests share one session per test, rolled back at the end, and the override in
`tests/conftest.py` commits and rolls back exactly where `session_scope`
does. A test fixture that is more forgiving than production is a fixture that
hides the bugs this rule exists to prevent.

## The web shell scrolls in exactly one place

The Mini App is a screen, not a document. `#root` is the app: it is exactly one
screenful tall and it is the only element that scrolls. `body` carries
`overflow: hidden`, which the viewport takes its own overflow from, so the
document has nothing to scroll and cannot invent travel of its own.

**One screenful is Telegram's number, not the webview's.** `--app-height`,
published by `bindAppHeight` in `main.tsx` from the viewport's stable height,
with `100dvh` only as the fallback. On iOS and Android the SDK does not trust
`window.innerHeight` either — it asks the client and waits for
`viewport_changed` — and `100dvh` is that same untrusted number. Where they
disagree, an app sized to the webview puts its last rows below the visible edge
with nothing able to scroll to them. Zero is not an answer and is skipped: the
signal reads `0` until the client replies, and a CSS variable set to `0px` is
defined, so the fallback would not fire.

Four rules follow, and they are what to check before changing layout:

- **A scroll must end on content.** Not "a screen that fits must not scroll" —
  for any layout there is a band of viewport heights where the content is a
  few pixels too tall, so that rule only moves the failing size around. What
  makes it a bug is emptiness at the end of the travel. The screen's own
  `padding-bottom` is the only breathing room at the foot of a page; a spacer
  under the last element is a stretch of nothing that someone has to scroll
  through to reach.
- **Anything pinned to an edge is `position: fixed`** — the tab bar, the sheet,
  the scrim. They are descendants of `#root` but are laid out against the
  viewport: a scroll container is not a containing block for fixed elements.
  That is what lets the tab bar stay put while the screen behind it moves.
- **A fixed bar is opaque behind its own controls.** Whatever a bar is pinned
  over is moving; the controls on it are not, and a person reading them must
  not also be reading a card sliding underneath. The tab bar's background was a
  gradient that reached full opacity only over the lower part of its height,
  while its contents were centred over the whole of it — so the top of every
  icon and the whole of the round button were painted onto passing text. A fade
  is the right idea and the wrong place for it: it belongs *above* the bar,
  where content is meant to disappear, not across the part that holds controls.
- **Telegram's vertical swipe is off** (`swipeBehavior`, Mini Apps 7.7). The
  gesture drags the whole app towards dismissal, and on a screen with nothing
  to scroll a drag and a scroll are the same movement, so the app appears to
  scroll where there is nothing to see. Because that same gesture is how a
  part-height Mini App is grown, the app asks for the whole screen with
  `viewport.expand()` at startup rather than leaving someone in a half sheet
  with no way out of it. It is dismissed with Telegram's close button.

`pnpm check:scroll` in `web/` is the first rule, executable. At three phone
sizes it measures the gap between the lowest thing that paints and the bottom
of the screen's content box — the screen's own `padding-bottom` is subtracted,
which is also what keeps the number right on a phone with a home indicator. A
container does not count as painting on behalf of its children, so a spacer
nested inside a card list is as visible to it as one at the foot of the page.

It needs the dev server, the API and signed init data, and it stops rather than
measuring a home screen that came back without its categories, because that
means the API is rejecting the init data and every screen behind it is an error
state. A page it cannot recognise as a screen at all is a hard stop too, and a
screen it could not reach is named in the summary: a check that reports an
unmeasured screen as a clean one has stopped being a check.

What it takes on trust is the screen's own `padding-bottom` — that is the
number it subtracts, so a screen that reserves room for a tab bar it does not
render will pass with a blank strip at its foot. Nothing runs it automatically;
it wants a browser and a database, which CI here does not give it.

`pnpm check:tabbar` is the third rule, executable, and needs the same running
stack. It photographs the tab bar with a list scrolled to the top and again
with that list moved under it, and requires the two pictures to be the same
pixels: a bar that is opaque behind its controls cannot be changed by what
passes beneath it, and one that is not changes wherever it is see-through.
Measured on the three screens that have a list long enough to move (`/`,
`/results`, `/chats`), at the same three phone sizes. `/chats` needs
supervisor's webapi behind the dev server; without it the screen shows its
error row and the check reports it unmeasured. It says nothing about how the bar looks — only that what is
under it stays under it.

## The embedding model ships inside the image

`subject_embeddings` is filled by a model, and the model is a 197 MB file. It is
downloaded at **build** time, from a pinned commit revision and verified against
a checksum, and copied into the runtime image — not pulled when the container
starts.

The image is the unit of deploy and of rollback: `prod-<sha7>` is what CI pushes
and what `rollback.yml` puts back. A model fetched at startup would make one tag
behave differently on different days, and a rollback would restore the code
without restoring the model. It would also need a writable cache in a container
whose Dockerfile says the application writes nothing to disk, and it would make
every restart depend on Hugging Face being up. This repository already has one
piece of state that lives outside the image — the seed, which the deploy does
not run — and the cost of that is documented in `docs/data-model.md`.

Two dependencies carry it: `onnxruntime` and `tokenizers`. No torch and no
transformers, which is the difference between 200 MB and two gigabytes.

The weights are **EmbeddingGemma-300m**, quantised to q4, from the ungated ONNX
mirror. They are licensed under the Gemma Terms of Use rather than Apache-2.0:
commercial use is allowed, with use restrictions that have to be passed on
downstream. That is a deliberate trade — it was the only model of the seven
measured that answered the whole fixture, and its scores are the only ones that
separate confident answers from guesses — and it is written here so the choice
is visible if the licence ever matters.

## Where the code does not follow this yet

Written down because an agent greps this tree and builds against what it
finds, and a rule with silent exceptions is worse than no rule.

- **Nothing tells a helper that a request exists.** `requests.feed_for` filters
  on status, authorship, expiry and whether you already answered, and uses the
  subject only for *ranking*, so every helper profile sees every open request —
  which the screens now say, rather than promising the subject narrows it. What
  is still missing is the push: the notifications that exist are about a
  response and an acceptance, so a request waits to be found rather than
  arriving. The product decision it waits on is whether to narrow the feed
  first, since notifying every helper about every request is how a feed becomes
  something people mute — and that decision cannot be made from data yet: the
  catalog holds no profiles and no requests. `Notifier.tell_owner`, described
  under "What belongs where", exists so that the first ones are noticed without
  anybody reading the database.

Each of these is a separate change with its own tests. None of them is a
reason to write new code the old way.
