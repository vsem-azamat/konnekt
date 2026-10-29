# Invariants

Rules a reader would otherwise break, each with the damage it prevents.

Nothing here describes structure, counts anything, or lists capabilities — that
kind of text goes stale without anyone noticing, and this file is only worth
keeping if it stays true. Behaviour is pinned by tests; this is for the rules a
test cannot state, either because they span processes, live in deployment, or
record *why* a design is shaped the way it is.

Add an entry only when all three hold: it cannot be inferred from the code, its
violation causes real damage or silent breakage, and the reason survives the
code moving.

---

## Telegram

**A callback belongs to the bot that sent the message.** Telegram delivers an
inline-keyboard press to the sending identity. A message whose buttons were sent
under a different token renders perfectly and does nothing at all when pressed —
no error, no log. Every inline-keyboard handler lives on the moderator
dispatcher, so any process that sends such a message must send it with the
moderator token, not merely with some working bot token.

**`parse_mode=None` whenever you pass entities.** The moderator bot defaults to
HTML, and that default silently overrides explicit `entities` /
`caption_entities`. The formatting is simply lost; nothing raises. Applies to
every send and edit call, of which there are more than a dozen.

**The deployed application uses the Bot API and nothing else.** Titles, photos,
member counts, message history — all of it either a bot call or a row we wrote
ourselves. The Telegram client API is a maintenance tool that runs from a
developer's machine against a session that lives there; production has no
credentials for it and no session file, and the library is a dev dependency so
that a runtime import fails loudly rather than a runtime feature failing quietly.

That is not a preference. The snapshot loop was built on the client API and
therefore asked nobody: every guard along the way degraded to `None` and logged
at info level, so it wrote not one row for its entire life while every screen
downstream rendered a dash. A client-API dependency is a dependency on a human
being logged in somewhere, and that human is not on call.

**A user session is the whole account.** A bot token grants one bot; a session
grants every private conversation the account can see. This is why the scripts
that do use one stay off the server, why the session file is not a deployment
artefact, and why anything reintroducing one has to justify itself against
these two paragraphs first.

**Never point a development instance at production tokens, the userbot session,
or the production database.** Two pollers on one token make Telegram split
updates between them non-deterministically, and the development bot then
moderates real chats. No test can catch this.

## Mini App

**The app's height is only as fresh as Telegram's last report, so it has to
recover on its own.** Minimising, backgrounding and restoring a Mini App send
events whose order and completeness differ by client. On Android an app sized
by the last *stable* height stayed the height of the minimised bottom bar after
it was expanded again, and the catalogue showed a heading with no list under it
(October 2026; the device's exact event sequence was not captured). So the
viewport is asked for again on `visibility_changed` (Telegram's own script calls
it `activated`) and on `visibilitychange` to visible, and a settled live height
replaces a stale stable one: `web/src/lib/appHeight.ts`. The safe-area insets
are not re-asked yet; if they turn out to go stale the same way, they get the
same treatment.

**Telegram's height is a ceiling on the app, not its size.** Telegram for
Android reports the sheet's whole swipe container, about a header taller than
the webview it draws the app in; Telegram for iOS reports less than the webview
while its bottom button is up. An app sized to Telegram's number alone ran past
the bottom of the window on a Pixel, and the last rows of «Чаты» could not be
scrolled to (October 2026; the cause is read from Telegram's source and
reproduced by imposing its height, not measured on the device). So the app box
ends at the smaller of Telegram's height and the window's (`--visible-height`,
`web/src/styles/tokens.css`), and `pnpm check:devices` measures the end of a
long list with the two disagreeing both ways, in CI.

**A chat's photo is served from our address, and an address names one picture
forever.** The catalog shows `/api/public/avatars/<file_unique_id>` with a
year-long `immutable` cache. That is only safe because Telegram changes the
unique id when the photo changes; serving different bytes at an existing id, or
keying the address by chat, would leave every browser and Telegram WebView
showing the old photo with nothing to invalidate it. A Telegram file URL or file
id must never reach a client instead: the URL carries the bot token. The bytes
live in the database because the bot writes them and the web API, a different
container, reads them. The console's faces (`/api/chats/<id>/photo`,
`/api/users/<id>/photo`) are keyed by id, which is safe only because they are
admin-only and cached `private` for a day: never make them `immutable`.

**A Mini App secret is `hmac(key="WebAppData", msg=bot_token)`.** The other
derivation anyone reaches for, `sha256(bot_token)`, belonged to the Login
Widget and fails every signature here. "Fixing" that by relaxing the check is
how a Mini App ends up trusting whatever the caller claims. An empty bot token
must refuse rather than derive a secret from nothing. The check string is every
received field except `hash`, `signature` included: only Telegram's third-party
Ed25519 check leaves `signature` out, and leaving it out here refused every
real launch.

**The console has two doors, and each carries a proof Telegram made.** Inside
Telegram a session is issued for a verified `initData` payload. In a browser it
is issued for an OpenID Connect `id_token` that Telegram signed for this client
(code flow, PKCE S256, `state` and `nonce`), checked against Telegram's
published keys with the algorithm fixed here rather than read from the token.
What was removed should stay removed: the Login Widget asked a browser to
re-prove an identity Telegram had already proven, and a magic link was a
password-less bearer token sent through a chat, forwardable by whoever received
it. The browser door differs from the widget in that nothing reusable reaches
the browser: its `code` is worthless without the verifier in its own cookie and
the client secret held server-side. Any further way in has to carry a signature
that can be checked, or it is not a way in. The browser door exists only while
`WEBAPI_ADMIN_URL`, `WEBAPI_OIDC_CLIENT_ID` and `WEBAPI_OIDC_CLIENT_SECRET` are
all set.

**An OIDC callback finishes only the sign-in its own browser started.** The
`state`, `nonce` and PKCE verifier wait in an httpOnly cookie scoped to the two
sign-in routes; a callback without it is refused, so somebody else's valid
`code` cannot sign the admin's browser in to their account. The identity is the
numeric `id` claim (scope `profile`), not `sub`, because that is what the
super-admin list holds.

**A cookie alone does not authorise a write.** `SameSite=Lax` is same-site, not
same-origin: another host under the same domain still sends the cookie, and a
`text/plain` body skips the CORS preflight yet is read as JSON. So a write that
carries the console's cookie must name one of our origins
(`app/webapi/origin_guard.py`), and the admin site's origin joins the allowed
ones. Writes without the cookie are not this guard's concern; a signed
`initData` decides those.

**A signature is not an authorisation.** `initData` says who is asking; the
super-admin list says whether they may. The check against
`settings.admin.super_admins` runs after verification, on the id Telegram
signed rather than any id the payload volunteers elsewhere.

**Four public endpoints write, and only about the caller.** The join check,
`/api/public/catalog-pass` and `/api/public/seen` take a signed `initData` and act on the id Telegram signed,
never on one the body names. `/seen` is idempotent: the visit is dated by
`auth_date`, which names one launch, so a payload sent again counts once; and
it writes a person at most once per half minute. `/api/public/client-errors`
writes only a log line and a counter, signed so that only a Telegram launch
can fill them, and keeps nothing of the caller: the signed id is a key of its
in-memory rate limit and appears in no line. A new public endpoint that
writes joins this list or is not public.

**The audience holds what Telegram tells us, never what people wrote.** Names,
username, language and when somebody came, per bot and the Mini App; no
message text, and no ids or names in the logs. Being in a moderated group is
not being in the audience: a bot cannot write to someone who never opened a
chat with it.

**A join check belongs to one applicant, and that binding is stored.** Holding
the query id is not the same as being the person it was issued to. Carrying the
applicant in the Mini App's URL would let anyone with the link pass the check
on someone else's behalf — precisely the bot farm a check exists to stop. The
request also arrives in the bot process while the check is answered by the web
API, so the two halves have nowhere else to meet. The captcha sent in a private
message follows the same rule: a tap counts only from the applicant it was
sent to.

**Three things skip the captcha, and none of them is a claim the caller makes.**
A captcha passed in another of our chats within `CAPTCHA_TRUST_DAYS`
(status `trusted`); a tap on the chat's join button in the Mini App catalog
(status `catalog`), which Telegram signed, within `CAPTCHA_CATALOG_PASS_HOURS`;
and the chat's own «Пускать всех». A catalog tap leaves a pass keyed by the
signed user and the chat, found by its public link so that no chat id is
published; the chat must be approved with the captcha on. The next join request
spends it, once. Neither `trusted` nor `catalog` is itself a reason to trust:
only a captcha actually answered renews trust. Both are checked after the
blacklist and ban history, and both count towards a join wave. Trust skips a
hold; a pass does not, because a pass is cheap to mint and a held request keeps
it. The pass works where the captcha arrives by private message, not where
this bot guards with the join-check Mini App.

**One bot answers a chat's join requests.** Telegram lets a bot write to an
applicant only until somebody else has, so with a second captcha bot in the
chat (@simplecaptcha_bot, today) whoever writes first wins and the other's
captcha is never delivered. Turn captcha on, or «Пускать всех» in a public
chat (the bot then approves before the other bot asks), in the same step as
taking the other bot out of it.

## Approval

**Being in a chat is not permission to moderate it.** The bot can sync a
group it does not own, and legacy `approved` rows are not evidence of an
agreement with the owner. Until somebody decides about a discovered group, its
listing stays unpublished and its active moderation disabled. When taking a
listing down, clear its public link as well as its status: restoring a status
must not silently republish an old link.

**Listing a chat is not claiming it.** A chat run by somebody else may be
listed so students can find it, as `external`, and the catalogue marks it as
not ours, because its rules are not ours either. That mark is the whole of the
consent question: an unmarked listing would vouch for a room we do not run.
`observed` is a chat of ours where another bot of ours is in charge (NTK's own
bot in @chat_ntk): ours to list and unmarked, never ours to act in, since a
second bot answering there competes with the one already running it. Neither
is reach: nobody buying a post can be sold a room our posts do not go to. The
price of that honesty is accepted: a group's chat count on the ads page can be
smaller than in the catalogue, which shows which of its chats are not
moderated.

**A private chat's catalogue link is the bot's, and the bot never lists a chat.**
`public_link` is both the decision to list and the address served. For a chat
without a username the bot keeps that address a link it made itself, and
replaces it when Telegram says it no longer works; it does so only for chats
already carrying one. A flag beside the link was considered and left out for
the reason on the column: the two would disagree. So a link pasted into the
console for a private chat is only a request to list it — the next sweep swaps
it for the bot's own — and clearing the column still takes the chat down.
Telegram sends no update when a link is revoked, so the sweep is the detector.
`editChatInviteLink` succeeds only for a link the bot created and that is
live, which is why the same call adopts links made by hand with the bot's token
(no recreating, no churn) and finds the dead ones. An error reaches the report
chat only when the bot cannot mend the link, once per problem and not per
sweep, with the chat in the event's name (alerts are throttled per name); a
lost invite right is the usual cause. Only approved chats are swept: observed
ones are another bot's to act in. The sweep writes a new link only where the
row still holds the link and status it started from, because an operator may
unlist the chat while Telegram is being asked, and more than a few dead links
in one sweep halts the sweeps until the process restarts, instead of minting
links across the catalogue. An edit replaces the whole link, so the chat's own
settings are the authority for join requests: turn the captcha on for a
chat, do not set it by hand on the bot's link.

**Moderation is the one meaning of `approved`, read when the action runs.**
Every path that acts in a chat asks whether it is approved at the moment it
acts — a proposal confirmed later or a join check passed later asks again,
since the chat may have been switched to watching in between. The statuses
that only list a chat are other values of the same column rather than a second
column beside it: a second column would have to be remembered at every one of
those checks, and the one that forgets it is the bot moderating a chat it was
told to watch, whereas a new status that nothing checks for is merely a chat
nobody listed.

**A chat is approved or it is not — that is a property of the chat, not of an
update type.** The bot records what it observes in unapproved groups but takes
no public action there: no moderation commands, no blacklist ban or unban, no
spam prompt, no ad alert. When a new update type starts carrying public action,
the gate has to learn about it, or the action escapes approval.

**The approval gate must run after history capture.** Reversing them silently
stops passive recording for chats awaiting approval, which is exactly the data
an operator needs in order to decide on approval.

## The two halves of the web

The web is one Mini App in `web/`. Its console is `web/src/console/`, for
super admins; everything else is the public half. The old console's `/admin`
addresses redirect into it (`docker/Caddyfile`).

**The public half calls nothing of ours but `/api/public/*`, and does not
import the console.** Only `web/src/console/` may use webapi's session, so a
public screen cannot make a console request by accident; the shell mounts
the console's routes and nothing more. Those endpoints
return explicit safe projections, so what a stranger may see is decided once,
at the boundary, rather than by a conditional on a page that somebody can
delete. A public screen reaching a protected endpoint is the bug; the 401 it
earns is only the symptom. Its other API, `/api/v1/*`, is the catalog's, a
different backend that never sees this one's session.

**Authorisation is a gate, not a per-page check.** Every screen under
`web/src/console/pages/` renders `ConsoleGate` around itself, and a test says
so, so a new screen cannot forget to ask.

**The browser's guard is the second lock, never the only one.** The API refuses
without a valid super-admin cookie whatever the client believes. What the
front-end guard buys is honesty — a sign-in page instead of a console full of
failed requests.

**A public link is checked for shape before it is stored.** Its value is
rendered as an `href` on a page anybody can open, which makes it the one
admin-supplied field that leaves the console as a link (the institution code,
city and topic leave it too, but only as text) — so it must be a Telegram chat
link and nothing else, refused at the schema rather than at the point of
rendering. A cleared field means "take it down": an empty string would list a
chat whose card leads nowhere, because the catalogue keys off the column being
set.

**A public figure says how much of itself it measured.** Member counts come
from snapshots the bot may not have managed to take, so a reach total can
cover part of the catalogue while naming all of it. The endpoint returns
`measured_chats` beside `members` for exactly that reason, and the page has to
show the gap — a number somebody is about to pay against must not quietly stand
for more than it counted.

**The public half never calls Telegram at request time.** Its endpoints answer
strangers, and a public URL that reaches Telegram on demand is a public URL
somebody can point at our rate limit. Aggregates are read from stored
snapshots, which is also why they can be served to anybody at any rate.

**Every word on a screen goes through Lingui, in all four languages.** Russian
is the source; Czech, English and Ukrainian are filled in before a string
ships, and CI fails on a missing one. A screen half in one language is not a
smaller problem than a screen entirely in another: the mixture is what makes a
reader stop and translate. Plural endings come from `<Plural>`, never from
string concatenation, because Russian and Czech have more than two and a
hand-rolled "5 минуты" is the tell.

**A sentence about a person does not guess their gender.** Russian, Ukrainian
and Czech inflect past tenses, short adjectives and pronouns for it, and we do
not know it: «Свободен», «Готовил», «его сообщения» read wrong for every woman
they describe, in all three languages at once. Word it without the inflected
form («Есть время», «Опыт с этим экзаменом: 3 человека»); if that ever reads
too badly, the API has to send a gender and the message uses ICU `select`.

**One question, one screen.** Two screens that list the same rows from the same
endpoint differ only in which columns they pick, and the second copy is the one
nobody remembers to update. When two screens start converging, merge them and
leave a redirect.

**Every way to publish goes through the console.** A script may fill the
catalogue in bulk, but it must never be the only way to change it — a feature
whose switch lives in a maintainer's terminal is a feature the operator cannot
undo.

**Chats nest one level deep.** A chat goes under a top-level chat, and a chat
others sit under stays at the top itself. Both lists group by the parent and
nothing deeper, so a grandchild would appear under neither its parent nor its
grandparent; the console offers only the parents that keep that true.

**A chat names its university by the catalog's code.** `institution_code` is
the catalog's code for a university (`cvut`), set in the console on a chat
at the top; the chats under it carry their parent's, so the server refuses a
code on a child and drops one when a chat moves under a parent. The public
catalogue publishes it as `institution` so the app can put a student's own
university first. The console offers universities only, never a faculty: a
faculty's students are found through their university.

**Times are read where the reader is.** Webapi stores and counts in UTC; the
console shows every time, and the hours of its activity grid, in the reader's
own zone. A Prague evening drawn as UTC looks like the afternoon.

**`/join` belongs to the public half.** The join check is opened inside
Telegram by an applicant who has no session and must not be sent to get one;
it proves who they are with the signature it was opened with, sent to
`/api/public/join-check`.

## Who may moderate

**Being an administrator of a Telegram chat grants nothing.** That crown is
handed out so a name shows up in the member list; it is not a statement about
who may ban people. The bot answers the question from its own tables and has
never done otherwise — a filter that consulted `get_chat_member` would quietly
hand forty-five chats to whoever asked a friend for a title.

**An administrator's rights stop at the chats named in `admin_chats`.** A flat
list of administrators means trusting somebody with one faculty chat trusts them
with the other forty-four, which is not what anybody agreed to when they took
the job. Every guard asks "may this person act *here*", never "is this person an
administrator".

**Super administrators live in configuration, not in the database.** They are
the only people who can grant moderator rights, so the set of them must not be
changeable by writing a row — an attacker with one `INSERT` would otherwise
promote themselves. `ADMIN_SUPER_ADMINS` is also the only thing the web console
admits.

**Commands are split by how far a mistake travels.** A ban, mute, kick, pin or
deletion spoils one chat, so a moderator of that chat may run it. `/banall`
reaches every chat at once and can wipe what the person wrote, teaching the
shared spam corpus on the way, so it stays with the super administrators. A new
command belongs on the global side unless its blast radius is provably one chat.

**Two commands must not differ only by prefix or by an ending.** Both `!` and
`/` are live, so `/spam` — a member asking moderators to look at a message —
sat one character from `!spam`, which banned that member out of every chat and
deleted everything they had written. `!black` and `!blacklist` were four letters
apart and one of them was irreversible. A name that reads as a near-miss of
another name is a name that will be typed by mistake, and no confirmation
dialog helps when the dialog is identical either way.

**A destructive choice is made on the button, not in the spelling.** `!black`
and `!spam` differed by whether the person's messages were also wiped, and
their confirmation dialogs were byte-identical — so the screen an administrator
read before pressing Yes could not tell them which outcome they had asked for.
Where one command has two endings, both belong on labelled buttons in the same
dialog.

**A moderator does not act on another moderator of the same chat.** Removing
somebody trusted with a chat is a dispute for the person who trusted them, so
only a super admin may ban, kick or mute a moderator there; and nobody, through
any path, removes a super admin.

**A stand-in sender is nobody.** Telegram signs posts sent as a channel, by an
anonymous admin, or forwarded from a linked channel with one shared user each.
Blacklisting, muting or trusting that user acts on every such message in every
chat at once, so no path accepts one as a person, and a command's target is
resolved through `author_of`, never `reply_to_message.from_user`. The one
exception is `!unadmin`, which may take a grant back from a stand-in, because
taking back is always safe.

**The answer is read fresh on every command.** Scoped rights were cached for
five minutes when they were the same everywhere; per-chat they must not be, or a
moderator removed from a chat keeps it until the cache expires.

## The moderation record

**A moderator's action is written down after it succeeds, never before.** The
row is the claim that something happened, so an attempt that Telegram refused
must not leave one — and a proposal a human rejected leaves nothing at all.

**Failing to write the row never fails the action.** By the time the record is
written the person is already banned; an error surfacing to the admin at that
point would report the opposite of what happened. The write is logged and
swallowed, which is the one place in this codebase where losing data is
preferable to raising.

**The actor is always a person.** The source says how the action was asked for —
a command in a chat, the console, or the control plane — but a token can never be the answer
to "who banned this person", so a confirmed proposal is recorded against the
admin who pressed confirm.

**The blacklist cache may be stale, never wrong about a return.** The bot keeps
the blacklisted ids for five minutes, and not every path that changes the list
can reset that cache — the console runs in another process. A cached id is confirmed against
its row before the bot bans anyone: a stale cache may let a fresh ban wait for
Telegram's own, but never throws out a person who was let back in.

## MCP control plane

**The boundary is what a leaked token can do, not which tools exist.** The
original rule was that the toolset must never grow. That held while the plane
only touched content, and stopped holding when the operator's moderation work
moved here, because the point of that work is privileged mutation. What
replaced it: reads never reach outside managed chats, bounded writes are
reversible or self-expiring, and removals are only ever proposed.

**Removing a person is never performed by a tool call.** `propose_ban` and
`propose_blacklist` create a pending action and return. A super admin presses
confirm in the moderator bot or on the console's Сигналы screen, or it expires
having done nothing. Both presses go through the same claim, so of two at once
exactly one runs, and the console's press takes the buttons off the bot's
message so it cannot offer a decision already made. Any tool that
bans directly re-opens this — as would any tool that decides and acts in one
call, which is what the removed assistant's `analyze_message` did.

**A ban is attributable, and the token is not a person.** Every proposal records
the admin it acts for — the first super admin, the same one escalations and
reports answer to. With no admin configured the proposal tools refuse
rather than log an action against nobody.

**Tool errors are masked because they land in an operator's chat history.** An
unmasked exception travels to the external runtime and from there into a
conversation log; a failed database connection would carry its DSN along.
`mask_error_details` is not a debugging convenience to toggle.

**The control plane is not published to the internet, and that is a decision
rather than an oversight.** It is served by the bot, published on the host's
loopback only, and inside the stack the bot sits on a network no other
container joins: the catalog API parses untrusted input and must not be one
leaked token away from it. The edge has no rule for it. This was not always
so: the endpoint used to live on the web API behind the existing `/api/*`
proxy, where enabling the flag was enough to expose it. Do not restore that
convenience — the toolset now includes privileged moderation, and its safety
rests on more than a bearer token.

## Observability

**Telemetry names kinds, never people.** A metric label is a route template, an
update type, an outcome: never a chat or a user id, and no search on a person
needs one, because the logs carry the ids that moderation itself names. The
update context bound into every log line (`update_id`, `update_type`,
`chat_id` of a group or channel, handler) leaves the user out on purpose, for
the same reason the audience's ids stay out of the logs, and leaves the chat out
of a private conversation, where its id is the person's. An access line names a
route template, not a path, for the same reason. A label that can carry an id makes a series
for everyone who ever wrote, in a store that outlives the chat's own retention.

**The scrape token is also the switch.** `OBSERVABILITY_METRICS_SECRET` unset
means the endpoints answer nothing (404), and the bot starts no server. There
is no flag beside it: one that disagreed with the secret could only fail in the
direction that leaves a door open. The same token reads all three endpoints;
rotating it is one repository secret and one file on the monitoring host.

**The bot's metrics are not the control plane's port.** The bot has no web
front, so its scrape has a port of its own (8789), which the edge may proxy to
Prometheus. The MCP plane (8788) must stay unproxied, see «Approval».

## Deployment

**The web UI port is loopback-only.** It is reached by the server-level edge
proxy. Dropping the `127.0.0.1:` prefix exposes the UI around the edge, past TLS
and any edge rules, and logs nothing.

**A migration leaves a schema the previous release can still run on.** The
deploy migrates while the old bot and webapi are still serving, and going back
is a redeploy of an older sha without its migrations, because the older alembic
does not know the newer revision. Both rely on the same thing: add first, use
the addition in the next release, and remove what the old code read only once
no release that reads it can come back. A migration that renames or drops in
one step breaks the running release during every deploy and makes the previous
one impossible to return to.
